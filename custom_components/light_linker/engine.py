"""Runtime engine: dispatcher, profiles and executor."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from . import z2m
from .adapters import SourceAdapter, create_adapters
from .adapters.device_maps import slot_event
from .const import (
    ACTIVITY_BUFFER,
    DEBOUNCE_S,
    DOMAIN,
    EVENT_TRIGGERED,
    EXPECTED_STATE_TTL_S,
    GATE_VERIFY_TIMEOUT_S,
    HOLD_EVENTS,
    MULTI_PRESS_S,
    PANEL_URL_PATH,
    RAMP_ACTIONS,
    REPEAT_GAP_S,
    SIGNAL_LINKS_CHANGED,
    SIGNAL_MOTION_STATE,
    TARGET_DOMAINS,
    ActionType,
    Adapter,
    EventKind,
    MotionState,
    Profile,
    SlotEvent,
    ToggleMode,
)
from .devices import DeviceLibrary
from .models import GROUP_SCHEMA, Link, NormalizedEvent, Source
from .motion import MotionController
from .ramp import Ramp, brightness_pct
from .store import LinkStore

_LOGGER = logging.getLogger(__name__)

_SERVICE_TIMEOUT_S = 15


class LinkNotFound(KeyError):
    """Raised when a link id is unknown."""


@dataclass(slots=True)
class _Hold:
    """A button being held: the ramp it runs and how it ends."""

    binding: dict[str, Any]
    ramp: Ramp | None
    policy: str
    timer: asyncio.TimerHandle | None = None


class Engine:
    """Holds the links and turns button events into actions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: LinkStore) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.store = store
        self._index: dict[str, list[tuple[Link, Source]]] = {}
        self._adapters: list[SourceAdapter] = []
        self._debounce: dict[tuple[str, ...], float] = {}
        self._holds: dict[tuple[str, str, str], _Hold] = {}
        # sources whose hold events repeat while held (learned at runtime)
        self._hold_style: dict[str, str] = {}
        self._dim_dir: dict[tuple[str, str], str] = {}
        self._cycle: dict[tuple[str, str], int] = {}
        # presses counted for double / triple click: (source, button) -> (count, timer)
        self._presses: dict[tuple[str, str], tuple[int, asyncio.TimerHandle | None]] = {}
        self._multi_native: dict[str, bool] = {}
        self._observers: dict[str, set[Callable[[dict[str, Any]], None]]] = {}
        self.library = DeviceLibrary(hass)
        # Last commanded state per link and target set: (on, valid_until).
        # Devices report their new state with a delay; a second press inside
        # that window must toggle back instead of repeating the first command.
        self._expected: dict[str, tuple[bool, float]] = {}
        self._verify_tasks: dict[str, asyncio.Task[None]] = {}
        self._learn_subs: set[Callable[[dict[str, Any]], None]] = set()
        self._activity_subs: set[Callable[[dict[str, Any]], None]] = set()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._started = False
        self._motion: dict[str, MotionController] = {}
        self.z2m = z2m.Z2MGroups(hass)
        self.activity: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_BUFFER)
        self.last_triggered: dict[str, str] = {}
        self.last_error: dict[str, dict[str, str]] = {}
        self.rebuild_index()

    # ------------------------------------------------------------------ setup

    @property
    def links(self) -> dict[str, Link]:
        """All links by id."""
        return self.store.links

    @property
    def learning(self) -> bool:
        """Whether a learn session is open."""
        return bool(self._learn_subs)

    @callback
    def async_start(self) -> None:
        """Start adapters and registry tracking (called once HA is running)."""
        self._adapters = create_adapters(self)
        self._started = True
        self._push_watched()
        self._sync_motion()
        self.async_update_device_info()
        if z2m.update_hints(self.hass, list(self.links.values()), self.store.ieee_hints):
            self.store.async_schedule_save()
        self.entry.async_create_background_task(
            self.hass, self.z2m.async_start(), f"{DOMAIN} z2m groups"
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED, self._handle_device_update
            )
        )
        self.async_update_issues()

    @callback
    def async_stop(self) -> None:
        """Stop everything."""
        for adapter in self._adapters:
            adapter.async_stop()
        self._adapters = []
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for session_key in list(self._holds):
            self._end_session(session_key)
        for _count, handle in self._presses.values():
            if handle:
                handle.cancel()
        self._presses.clear()
        for task in self._verify_tasks.values():
            task.cancel()
        self._verify_tasks.clear()
        for ctrl in self._motion.values():
            ctrl.async_stop()
        self._motion.clear()
        self.z2m.async_stop()
        self._started = False

    @callback
    def rebuild_index(self) -> None:
        """Rebuild the (source -> links) index; disabled links are left out."""
        self._index = {}
        for link in self.links.values():
            if not link.enabled:
                continue
            for src in link.sources:
                self._index.setdefault(src.key, []).append((link, src))
        self._push_watched()
        if self._started:
            self._sync_motion()
            self.async_update_device_info()

    @callback
    def _sync_motion(self) -> None:
        """One controller per enabled motion link; keep unchanged ones running."""
        wanted = {
            link.id: link
            for link in self.links.values()
            if link.enabled and link.profile == Profile.MOTION
        }
        for link_id in list(self._motion):
            ctrl = self._motion[link_id]
            if wanted.get(link_id) is not ctrl.link:
                ctrl.async_stop()
                del self._motion[link_id]
        for link_id, link in wanted.items():
            if link_id not in self._motion:
                ctrl = MotionController(self, link)
                self._motion[link_id] = ctrl
                ctrl.async_start()
        # links that were switched off still need their state sensor updated
        for link in self.links.values():
            if link.profile == Profile.MOTION and link.id not in self._motion:
                async_dispatcher_send(self.hass, SIGNAL_MOTION_STATE, link.id)

    @callback
    def motion_status(self, link_id: str) -> dict[str, Any] | None:
        """Status of a motion link, None for other profiles."""
        link = self.links.get(link_id)
        if link is None or link.profile != Profile.MOTION:
            return None
        if ctrl := self._motion.get(link_id):
            return ctrl.as_dict()
        return {"state": str(MotionState.INACTIVE), "timer_end": None, "occupied": None, "dark": None}

    @callback
    def async_occupancy_changed(self, entity_id: str) -> None:
        """Called by the occupancy adapter."""
        for link, _src in self._index.get(f"{Adapter.OCCUPANCY}:{entity_id}", ()):
            if ctrl := self._motion.get(link.id):
                ctrl.async_occupancy_changed()

    @callback
    def async_record_motion(self, link: Link, kind: str) -> None:
        """Activity entry for automatic and detected manual switching."""
        now = dt_util.utcnow().isoformat()
        record = {
            "link_id": link.id,
            "link_name": link.name,
            "entity_id": None,
            "button": None,
            "kind": kind,
            "origin": "motion",
            "time": now,
        }
        self.activity.appendleft(record)
        self.last_triggered[link.id] = now
        self.hass.bus.async_fire(EVENT_TRIGGERED, record)
        for cb in list(self._activity_subs):
            cb(record)

    async def async_turn_for_motion(
        self, link: Link, on: bool, lights: list[str], switches: list[str], context: Context
    ) -> None:
        """Switch for a motion controller: never through a Z2M group, so every
        lamp reports the controller's own context."""
        await self._turn(link, on, lights, switches, context, group=False, key=f"{link.id}|motion")

    @callback
    def _push_watched(self) -> None:
        if not self._adapters:
            return
        watched: dict[Adapter, set[str]] = {adapter: set() for adapter in Adapter}
        for entries in self._index.values():
            for _link, src in entries:
                watched[src.adapter].add(src.ident)
        for key in self._observers:
            adapter, _, ident = key.partition(":")
            if adapter in watched:
                watched[Adapter(adapter)].add(ident)
        for adapter in self._adapters:
            adapter.async_set_watched(watched[adapter.adapter])

    # ------------------------------------------------------------------- CRUD

    @callback
    def _changed(self) -> None:
        self.rebuild_index()
        z2m.update_hints(self.hass, list(self.links.values()), self.store.ieee_hints)
        self.store.async_schedule_save()
        if self._started:
            try:
                self.async_update_issues()
            except Exception:  # a health check must never make a save fail
                _LOGGER.exception("Could not update repair issues")
        async_dispatcher_send(self.hass, SIGNAL_LINKS_CHANGED)

    @callback
    def async_create_link(self, data: dict[str, Any]) -> Link:
        """Create a link."""
        data = {k: v for k, v in data.items() if k not in ("id", "created_at", "updated_at")}
        link = Link.from_dict(data)
        self._validate(link)
        self.links[link.id] = link
        self._changed()
        return link

    @callback
    def async_update_link(self, link_id: str, data: dict[str, Any]) -> Link:
        """Replace a link (keeps id and creation time)."""
        old = self._get(link_id)
        merged = {**data, "id": link_id, "created_at": old.created_at}
        merged["updated_at"] = dt_util.utcnow().isoformat()
        link = Link.from_dict(merged)
        self._validate(link)
        self.links[link_id] = link
        self._forget(link_id)
        self._changed()
        return link

    @callback
    def async_delete_link(self, link_id: str) -> None:
        """Delete a link."""
        self._get(link_id)
        self._forget(link_id)
        del self.links[link_id]
        ir.async_delete_issue(self.hass, DOMAIN, f"link_broken_{link_id}")
        self._changed()

    # ------------------------------------------------------- groups

    @callback
    def async_save_group(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a Light Linker group."""
        clean = GROUP_SCHEMA(data)
        group_id = clean.get("id") or ulid_now()
        if clean.get("id") and group_id not in self.store.groups:
            raise vol.Invalid("Unbekannte Gruppe")
        members: list[str] = []
        for member in clean["members"]:
            if member in members:
                continue
            if member.startswith("group:"):
                ref = member[6:]
                if ref not in self.store.groups:
                    raise vol.Invalid(f"Unbekannte Gruppe {ref}")
                if ref == group_id or group_id in self._group_refs(ref):
                    raise vol.Invalid("Eine Gruppe kann sich nicht selbst enthalten.")
            elif member.split(".", 1)[0] not in TARGET_DOMAINS:
                raise vol.Invalid(f"{member} lässt sich nicht schalten")
            members.append(member)
        if not members:
            raise vol.Invalid("Eine Gruppe braucht mindestens ein Gerät.")
        is_new = group_id not in self.store.groups
        group = {"id": group_id, "name": clean["name"], "area_id": clean["area_id"], "members": members}
        self.store.groups[group_id] = group
        adopted = self._adopt_group(group_id) if is_new else []
        self._restart_users(self._links_using_group(group_id))
        self._changed()
        return {**group, "adopted": adopted}

    def _adopt_group(self, group_id: str) -> list[str]:
        """A new group replaces its members wherever all of them are targeted together.

        Returns the names of the links that now use the group.
        """
        members = set(self.group_members(group_id))
        direct = [m for m in self.store.groups[group_id]["members"] if not m.startswith("group:")]
        if len(members) < 2 or len(direct) != len(members):
            return []  # only plain device groups are taken over automatically
        changed: list[str] = []
        for link in self.links.values():
            hit = False
            for spec in self._all_target_specs(link):
                ids = spec.get("entity_id", [])
                if members <= set(ids):
                    spec["entity_id"] = [e for e in ids if e not in members]
                    spec["group_id"] = [*spec.get("group_id", []), group_id]
                    hit = True
            if hit:
                # a name that only listed the lamps becomes the group name
                names = set()
                for entity_id in members:
                    state = self.hass.states.get(entity_id)
                    names.add(state.name if state else entity_id)
                if {part.strip() for part in link.name.split(",")} == names:
                    link.name = self.store.groups[group_id]["name"]
                link.updated_at = dt_util.utcnow().isoformat()
                if ctrl := self._motion.pop(link.id, None):
                    ctrl.async_stop()
                self._forget(link.id)
                changed.append(link.name)
        return changed

    @callback
    def _restart_users(self, link_ids: list[str]) -> None:
        """Links whose group changed: drop runtime state, restart motion controllers."""
        for link_id in link_ids:
            self._forget(link_id)
            if ctrl := self._motion.pop(link_id, None):
                ctrl.async_stop()

    def _group_refs(self, group_id: str, _seen: frozenset[str] = frozenset()) -> set[str]:
        """All groups nested inside a group."""
        group = self.store.groups.get(group_id)
        if group is None or group_id in _seen:
            return set()
        result: set[str] = set()
        for member in group["members"]:
            if member.startswith("group:"):
                result.add(member[6:])
                result |= self._group_refs(member[6:], _seen | {group_id})
        return result

    def _links_using_group(self, group_id: str) -> list[str]:
        wanted = {group_id} | {g for g in self.store.groups if group_id in self._group_refs(g)}
        return [
            link.id
            for link in self.links.values()
            if any(set(spec.get("group_id", [])) & wanted for spec in self._all_target_specs(link))
        ]

    @callback
    def async_delete_group(self, group_id: str) -> int:
        """Delete a group; references in links and other groups are removed."""
        if group_id not in self.store.groups:
            raise LinkNotFound(group_id)
        used = self._links_using_group(group_id)
        self._restart_users(used)
        del self.store.groups[group_id]
        for group in self.store.groups.values():
            group["members"] = [m for m in group["members"] if m != f"group:{group_id}"]
        for link in self.links.values():
            for spec in self._all_target_specs(link):
                if group_id in spec.get("group_id", []):
                    spec["group_id"] = [g for g in spec["group_id"] if g != group_id]
                    self._forget(link.id)
        self._changed()
        return len(used)

    @callback
    def groups_status(self) -> list[dict[str, Any]]:
        """Groups with resolved members and where they are used."""
        result = []
        for group in self.store.groups.values():
            members = self.group_members(group["id"])
            on = [e for e in members if (st := self.hass.states.get(e)) and st.state in (STATE_ON, "open")]
            result.append(
                {
                    **group,
                    "entities": members,
                    "on": len(on),
                    "used_by": [self.links[lid].name for lid in self._links_using_group(group["id"])],
                    "parents": [g["name"] for g in self.store.groups.values() if f"group:{group['id']}" in g["members"]],
                }
            )
        return sorted(result, key=lambda g: g["name"].lower())

    # ------------------------------------------------------ tidy up

    def _signature(self, link: Link, binding: dict[str, Any], src: Source) -> str:
        """What a binding does on which slot - equal signatures are duplicates."""
        targets = link.binding_targets(binding)
        data = {
            "source": src.key,
            "button": binding["button"] if binding["button"] is not None else src.button,
            "event": str(binding["event"]),
            "action": str(binding["action"]),
            "entities": sorted(targets.get("entity_id", [])),
            "areas": sorted(targets.get("area_id", [])),
        }
        for key in ("brightness_pct", "color_temp_kelvin", "kelvin_list", "color_list", "scene"):
            if binding.get(key) not in (None, []):
                data[key] = binding[key]
        if binding["action"] in RAMP_ACTIONS:
            data["ramp"] = binding.get("ramp")
        return json.dumps(data, sort_keys=True, default=str)

    @callback
    def duplicates(self) -> dict[str, int]:
        """Binding id -> number of identical bindings (only those > 1)."""
        seen: dict[str, list[str]] = {}
        for link in self.links.values():
            for binding in link.bindings:
                for src in link.sources:
                    if binding["source"] in (None, src.key) and src.adapter != Adapter.OCCUPANCY:
                        seen.setdefault(self._signature(link, binding, src), []).append(binding["id"])
        return {bid: len(ids) for ids in seen.values() if len(ids) > 1 for bid in ids}

    @callback
    def async_dedupe(self) -> dict[str, Any]:
        """Keep each identical binding once (in the oldest link).

        Links that end up without bindings are deleted, unless they are motion
        links (those work without buttons).
        """
        kept: set[str] = set()
        removed = 0
        changed: set[str] = set()
        for link in sorted(self.links.values(), key=lambda l: l.created_at):
            keep = []
            for binding in link.bindings:
                sigs = [
                    self._signature(link, binding, src)
                    for src in link.sources
                    if binding["source"] in (None, src.key) and src.adapter != Adapter.OCCUPANCY
                ]
                if sigs and all(sig in kept for sig in sigs):
                    removed += 1
                    changed.add(link.id)
                    continue
                kept.update(sigs)
                keep.append(binding)
            link.bindings = keep
        deleted = []
        for link_id in changed:
            link = self.links[link_id]
            link.updated_at = dt_util.utcnow().isoformat()
            if link.profile != Profile.CUSTOM and link.profile != Profile.MOTION:
                link.profile = Profile.CUSTOM
            self._forget(link_id)
            if not link.bindings and link.profile != Profile.MOTION:
                deleted.append(link.name)
                del self.links[link_id]
                ir.async_delete_issue(self.hass, DOMAIN, f"link_broken_{link_id}")
        if changed:
            self._changed()
        return {"removed": removed, "deleted": deleted}

    @callback
    def async_remove_source(self, key: str) -> dict[str, Any]:
        """Take a button (all its bindings) out of every link.

        Links that have no source left are deleted.
        """
        changed = []
        deleted = []
        for link in list(self.links.values()):
            if not any(src.key == key for src in link.sources):
                continue
            others = [src for src in link.sources if src.key != key]
            link.sources = others
            other_keys = {src.key for src in others}
            link.bindings = [
                b for b in link.bindings
                if b["source"] in other_keys or (b["source"] is None and others)
            ]
            self._forget(link.id)
            if not others or (link.profile != Profile.MOTION and not link.bindings):
                deleted.append(link.name)
                del self.links[link.id]
                ir.async_delete_issue(self.hass, DOMAIN, f"link_broken_{link.id}")
            else:
                link.updated_at = dt_util.utcnow().isoformat()
                changed.append(link.name)
        self.store.seen_buttons.pop(key, None)
        if changed or deleted:
            self._changed()
        return {"changed": changed, "deleted": deleted}

    @callback
    def async_set_enabled(self, link_id: str, enabled: bool) -> None:
        """Enable or disable a link (used by the 'aktiv' switch)."""
        link = self._get(link_id)
        if link.enabled == enabled:
            return
        link.enabled = enabled
        link.updated_at = dt_util.utcnow().isoformat()
        if not enabled:
            self._stop_dim(link_id)
        self._changed()

    def _validate(self, link: Link) -> None:
        """Rules that span sources and other links."""
        occupancy = [s for s in link.sources if s.adapter == Adapter.OCCUPANCY]
        if link.profile == Profile.MOTION:
            if not occupancy:
                raise vol.Invalid("Eine Bewegungs-Verknüpfung braucht mindestens einen Melder.")
            mine = set(self.resolve_targets(link))
            for other in self.links.values():
                if other.id == link.id or other.profile != Profile.MOTION:
                    continue
                if shared := mine & set(self.resolve_targets(other)):
                    raise vol.Invalid(
                        f"{', '.join(sorted(shared))} wird schon von der Bewegungs-Verknüpfung "
                        f"„{other.name}“ gesteuert."
                    )
        elif occupancy:
            raise vol.Invalid("Melder gehen nur mit dem Verhalten „Bewegung“.")

    def _get(self, link_id: str) -> Link:
        try:
            return self.links[link_id]
        except KeyError as err:
            raise LinkNotFound(link_id) from err

    @callback
    def _forget(self, link_id: str) -> None:
        """Drop runtime state of a link."""
        self._stop_dim(link_id)
        prefix = f"{link_id}|"
        for key in [k for k in self._expected if k.startswith(prefix)]:
            del self._expected[key]
        for key in [k for k in self._verify_tasks if k.startswith(prefix)]:
            self._verify_tasks.pop(key).cancel()
        for key in [k for k in self._cycle if k[0] == link_id]:
            del self._cycle[key]

    # ------------------------------------------------------------ subscribers

    @callback
    def async_subscribe_learn(self, cb: Callable[[dict[str, Any]], None]) -> CALLBACK_TYPE:
        """Open a learn session."""
        self._learn_subs.add(cb)
        self._set_learning()

        @callback
        def _unsub() -> None:
            self._learn_subs.discard(cb)
            self._set_learning()

        return _unsub

    @callback
    def _set_learning(self) -> None:
        for adapter in self._adapters:
            adapter.async_set_learning(self.learning)

    @callback
    def async_subscribe_activity(
        self, cb: Callable[[dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Receive every triggered link."""
        self._activity_subs.add(cb)
        return lambda: self._activity_subs.discard(cb)

    @callback
    def async_learn_candidate(
        self,
        *,
        adapter: Adapter,
        ident: str,
        button: str | None,
        raw_type: str,
        kind: EventKind | None,
    ) -> None:
        """Forward a raw event to open learn sessions."""
        if not self._learn_subs:
            return
        if adapter == Adapter.ZHA:
            device = self._zha_device(ident)
            name = (device.name_by_user or device.name) if device else ident
            area_id = device.area_id if device else None
            suggested = Profile.ROCKER if raw_type in ("on", "off") else Profile.TOGGLE
        else:
            state = self.hass.states.get(ident)
            name = state.name if state else ident
            area_id = self.area_id_of(ident)
            event_types = (state.attributes.get("event_types") if state else None) or ()
            if adapter == Adapter.OCCUPANCY:
                suggested = Profile.MOTION
            elif adapter == Adapter.STATE_INPUT:
                suggested = Profile.SWITCH
            elif "brightness_move_up" in event_types or {"on", "off"} <= set(event_types):
                suggested = Profile.ROCKER
            else:
                suggested = Profile.TOGGLE
        info = {
            "adapter": str(adapter),
            "entity_id": None if adapter == Adapter.ZHA else ident,
            "device_ieee": ident if adapter == Adapter.ZHA else None,
            "name": name,
            "area_id": area_id,
            "area": self._area_name(area_id),
            "button": button,
            "raw_type": raw_type,
            "kind": str(kind) if kind else None,
            "suggested_profile": str(suggested),
        }
        for cb in list(self._learn_subs):
            cb(info)

    # --------------------------------------------------------------- dispatch

    @callback
    def async_handle_event(self, ev: NormalizedEvent) -> None:
        """Entry point for all adapters."""
        event = slot_event(ev.kind, ev.direction)
        if event is None:
            return
        self._remember_button(ev)
        if self._observers.get(ev.source_key):
            self._notify_observers(ev, event)
        entries = self._index.get(ev.source_key)
        if not entries:
            return
        if event == "release":
            for link, src in entries:
                if src.button is None or src.button == ev.button:
                    self._end_holds(link, src, ev.button)
            return
        if event == "repeat":
            for link, src in entries:
                self._keepalive(link, src, ev.button)
            return
        if event == SlotEvent.PRESS and self._needs_multi(ev.source_key, ev.button):
            self._collect_press(ev)
            return
        self._dispatch_slot(ev, SlotEvent(event))

    @callback
    def _dispatch_slot(self, ev: NormalizedEvent, event: SlotEvent) -> None:
        for link, src in self._index.get(ev.source_key, ()):
            if src.button is not None and src.button != ev.button:
                continue
            if event in HOLD_EVENTS and self._keepalive(link, src, ev.button):
                continue  # devices that repeat "hold" while held
            binding = self._find_binding(link, src, ev.button, event)
            if binding is None:
                continue
            key = (link.id, src.key, ev.button or "", "hold" if event in HOLD_EVENTS else str(event))
            now = time.monotonic()
            if now - self._debounce.get(key, 0.0) < DEBOUNCE_S:
                _LOGGER.debug("%s: debounced %s", link.name, event)
                continue
            self._debounce[key] = now
            self._dispatch(link, src, binding, ev.button, event, ev.has_release, "button")

    @staticmethod
    def _find_binding(
        link: Link, src: Source, button: str | None, event: SlotEvent
    ) -> dict[str, Any] | None:
        """The most specific binding for this slot (own source/button beats 'all')."""
        best: tuple[int, dict[str, Any]] | None = None
        for binding in link.bindings:
            if binding["event"] != event:
                continue
            if binding["source"] not in (None, src.key):
                continue
            if binding["button"] is not None and binding["button"] != button:
                continue
            score = (binding["source"] is not None) + 2 * (binding["button"] is not None)
            if best is None or score > best[0]:
                best = (score, binding)
        return best[1] if best else None

    # ------------------------------------------------------- multi press

    def _needs_multi(self, source_key: str, button: str | None) -> bool:
        """Count presses ourselves when a double/triple is bound but not reported."""
        if self._multi_native.get(source_key, True):
            return False
        for link, src in self._index.get(source_key, ()):
            for binding in link.bindings:
                if binding["event"] not in (SlotEvent.DOUBLE, SlotEvent.TRIPLE):
                    continue
                if binding["source"] not in (None, src.key):
                    continue
                if binding["button"] in (None, button):
                    return True
        return False

    def _max_presses(self, source_key: str, button: str | None) -> int:
        for link, src in self._index.get(source_key, ()):
            for binding in link.bindings:
                if (
                    binding["event"] == SlotEvent.TRIPLE
                    and binding["source"] in (None, src.key)
                    and binding["button"] in (None, button)
                ):
                    return 3
        return 2

    @callback
    def _collect_press(self, ev: NormalizedEvent) -> None:
        key = (ev.source_key, ev.button or "")
        count, handle = self._presses.get(key, (0, None))
        if handle:
            handle.cancel()
        count += 1
        if count >= self._max_presses(ev.source_key, ev.button):
            self._presses.pop(key, None)
            self._flush_presses(ev, count)
            return
        handle = self.hass.loop.call_later(MULTI_PRESS_S, self._presses_timeout, key, ev)
        self._presses[key] = (count, handle)

    @callback
    def _presses_timeout(self, key: tuple[str, str], ev: NormalizedEvent) -> None:
        count, _ = self._presses.pop(key, (0, None))
        if count:
            self._flush_presses(ev, count)

    @callback
    def _flush_presses(self, ev: NormalizedEvent, count: int) -> None:
        event = {1: SlotEvent.PRESS, 2: SlotEvent.DOUBLE}.get(count, SlotEvent.TRIPLE)
        self._dispatch_slot(ev, event)

    @callback
    def async_update_device_info(self) -> None:
        """Which sources report multi presses themselves (from their event list)."""
        from .devices import match, native_multi  # noqa: PLC0415

        result: dict[str, bool] = {}
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        for key in self._index:
            adapter, _, ident = key.partition(":")
            if adapter == Adapter.EVENT_ENTITY:
                state = self.hass.states.get(ident)
                types = list((state.attributes.get("event_types") if state else None) or [])
                entry = ent_reg.async_get(ident)
                device = dev_reg.async_get(entry.device_id) if entry and entry.device_id else None
                result[key] = native_multi(match(self.library.entries, device), Adapter.EVENT_ENTITY, types)
            elif adapter == Adapter.ZHA:
                device = self._zha_device(ident)
                result[key] = native_multi(match(self.library.entries, device), Adapter.ZHA, [])
            else:
                result[key] = True
        self._multi_native = result

    # -------------------------------------------------------- observers

    @callback
    def async_observe(self, source_key: str, cb: Callable[[dict[str, Any]], None]) -> CALLBACK_TYPE:
        """Stream the slot events of one source (panel highlights the pressed key)."""
        self._observers.setdefault(source_key, set()).add(cb)
        self._push_watched()

        @callback
        def _unsub() -> None:
            subs = self._observers.get(source_key)
            if subs is not None:
                subs.discard(cb)
                if not subs:
                    del self._observers[source_key]
            self._push_watched()

        return _unsub

    @callback
    def _notify_observers(self, ev: NormalizedEvent, event: SlotEvent | str) -> None:
        info = {"source": ev.source_key, "button": ev.button, "event": str(event), "raw": ev.raw_type}
        for cb in list(self._observers.get(ev.source_key, ())):
            cb(info)

    @callback
    def _remember_button(self, ev: NormalizedEvent) -> None:
        if ev.button is None or ev.source_key.startswith(str(Adapter.STATE_INPUT)):
            return
        seen = self.store.seen_buttons.setdefault(ev.source_key, [])
        if ev.button not in seen and len(seen) < 16:
            seen.append(ev.button)
            self.store.async_schedule_save()

    # ---------------------------------------------------------- trigger

    @callback
    def async_trigger(self, link_id: str, kind: EventKind, origin: str = "test") -> None:
        """Run a link without a button press (dashboard, service).

        Works for disabled links too: the automation fallback never reacts to
        these, so nothing switches twice.
        """
        link = self._get(link_id)
        wanted = slot_event(kind, None)
        order = [wanted] if isinstance(wanted, SlotEvent) else []
        if wanted in (SlotEvent.PRESS, None):
            order += [SlotEvent.PRESS, SlotEvent.ON, SlotEvent.RISE]
        if wanted == SlotEvent.HOLD:
            order += [SlotEvent.HOLD_UP]
        for event in order:
            for binding in link.bindings:
                if binding["event"] == event:
                    self.async_test_binding(link_id, binding["id"], origin)
                    return

    @callback
    def async_test_binding(self, link_id: str, binding_id: str, origin: str = "test") -> None:
        """Run one binding; a hold lasts two seconds."""
        link = self._get(link_id)
        binding = next((b for b in link.bindings if b["id"] == binding_id), None)
        if binding is None:
            raise LinkNotFound(binding_id)
        src = self._source_of(link, binding)
        self._dispatch(link, src, binding, binding["button"], binding["event"], True, origin)
        if binding["event"] in HOLD_EVENTS:
            self.hass.loop.call_later(2, self._end_holds, link, src, binding["button"])

    @staticmethod
    def _source_of(link: Link, binding: dict[str, Any]) -> Source:
        for src in link.sources:
            if binding["source"] in (None, src.key):
                return src
        return link.sources[0]

    @callback
    def _dispatch(
        self,
        link: Link,
        src: Source,
        binding: dict[str, Any],
        button: str | None,
        event: SlotEvent,
        has_release: bool,
        origin: str,
    ) -> None:
        now = dt_util.utcnow().isoformat()
        record = {
            "link_id": link.id,
            "link_name": link.name,
            "entity_id": src.ident,
            "source": src.key,
            "source_name": self.store.aliases.get(src.key),
            "button": button,
            "kind": str(event),
            "action": str(binding["action"]),
            "binding_id": binding["id"],
            "origin": origin,
            "time": now,
        }
        context = Context()
        self.activity.appendleft(record)
        self.last_triggered[link.id] = now
        self.hass.bus.async_fire(EVENT_TRIGGERED, record, context=context)
        for cb in list(self._activity_subs):
            cb(record)
        self.entry.async_create_task(
            self.hass,
            self._async_run(link, src, binding, button, event, has_release, context),
            f"{DOMAIN} {link.name} {event}",
            eager_start=True,
        )

    # --------------------------------------------------------------- actions

    def _targets_of(self, link: Link, binding: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        targets = self.resolve_binding_targets(link, binding)
        return (
            [e for e in targets if e.startswith("light.")],
            [e for e in targets if e.startswith("switch.")],
            [e for e in targets if e.startswith("cover.")],
        )

    async def _async_run(
        self,
        link: Link,
        src: Source,
        binding: dict[str, Any],
        button: str | None,
        event: SlotEvent,
        has_release: bool,
        context: Context,
    ) -> None:
        lights, switches, covers = self._targets_of(link, binding)
        action = ActionType(binding["action"])
        key = self._state_key(link, [*lights, *switches])
        if event in HOLD_EVENTS:
            await self._hold_start(link, src, binding, button, event, has_release, lights, context)
            return
        if action == ActionType.NONE:
            return
        if covers and action in (ActionType.TOGGLE, ActionType.ON, ActionType.OFF):
            # gates and blinds among the targets: toggle / open / close them once, never retried
            service = {ActionType.TOGGLE: "toggle", ActionType.ON: "open_cover", ActionType.OFF: "close_cover"}[action]
            if error := await self._call("cover", service, covers, None, context):
                self.last_error[link.id] = {"time": dt_util.utcnow().isoformat(), "message": error}
            if not (lights or switches):
                return
        if action == ActionType.TOGGLE:
            is_on = self._group_is_on(link, key, [*lights, *switches])
            await self._turn(link, not is_on, lights, switches, context, key=key)
        elif action == ActionType.ON:
            extra = {k: binding[k] for k in ("brightness_pct", "color_temp_kelvin") if binding.get(k)}
            await self._turn(link, True, lights, switches, context, extra, key=key)
        elif action == ActionType.OFF:
            await self._turn(link, False, lights, switches, context, key=key)
        elif action == ActionType.BRIGHTNESS:
            await self.async_light_on(
                link, lights,
                {"brightness_pct": binding.get("brightness_pct") or 100, "transition": link.options["transition"]},
                context,
            )
        elif action == ActionType.CYCLE_COLOR_TEMP:
            values = binding.get("kelvin_list") or [2700, 4000, 6500]
            idx = self._next_cycle(link.id, binding["id"], len(values))
            await self.async_light_on(
                link, lights, {"color_temp_kelvin": values[idx], "transition": link.options["transition"]}, context
            )
        elif action == ActionType.CYCLE_COLOR:
            values = binding.get("color_list") or [{"rgb": [255, 147, 41]}]
            idx = self._next_cycle(link.id, binding["id"], len(values))
            await self.async_light_on(
                link, lights, {"rgb_color": values[idx]["rgb"], "transition": link.options["transition"]}, context
            )
        elif action == ActionType.SCENE and binding.get("scene"):
            await self._call("scene", "turn_on", [binding["scene"]], None, context)
        elif action == ActionType.COVER_TOGGLE:
            await self._gate(link, covers, switches, context)
        elif action in (ActionType.COVER_OPEN, ActionType.COVER_CLOSE, ActionType.COVER_STOP):
            service = {"cover_open": "open_cover", "cover_close": "close_cover", "cover_stop": "stop_cover"}[action]
            if error := await self._call("cover", service, covers, None, context):
                self.last_error[link.id] = {"time": dt_util.utcnow().isoformat(), "message": error}
        elif action in RAMP_ACTIONS:
            # a ramp on a click: one step
            await self._step_once(link, binding, lights, self._ramp_direction(link, binding, lights), context)

    async def _call(
        self,
        domain: str,
        service: str,
        entities: list[str],
        data: dict[str, Any] | None,
        context: Context,
        group: bool = True,
    ) -> str | None:
        """Call a service and wait for it; return the error text on failure."""
        if not entities:
            return None
        if group and domain == "light" and (found := self.z2m.group_for(entities)):
            entities = [found[0]]
        try:
            async with asyncio.timeout(_SERVICE_TIMEOUT_S):
                await self.hass.services.async_call(
                    domain,
                    service,
                    data or {},
                    blocking=True,
                    context=context,
                    target={"entity_id": entities},
                )
        except (HomeAssistantError, TimeoutError) as err:
            message = str(err) or type(err).__name__
            _LOGGER.warning("%s.%s %s failed: %s", domain, service, entities, message)
            return message
        return None

    async def async_light_on(
        self, link: Link, lights: list[str], data: dict[str, Any], context: Context
    ) -> None:
        """light.turn_on with error bookkeeping (used by actions and ramps)."""
        if error := await self._call("light", "turn_on", lights, data, context):
            self.last_error[link.id] = {"time": dt_util.utcnow().isoformat(), "message": error}

    @callback
    def fire_light_on(self, lights: list[str], data: dict[str, Any], context: Context) -> None:
        """Fire and forget (ramp steps must keep their cadence)."""
        if found := self.z2m.group_for(lights):
            lights = [found[0]]
        if lights:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "light", "turn_on", data, blocking=False, context=context,
                    target={"entity_id": lights},
                ),
                eager_start=True,
            )

    def _states_on(self, entities: Iterable[str]) -> list[bool]:
        result: list[bool] = []
        for entity_id in entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            result.append(state.state == STATE_ON)
        return result

    @staticmethod
    def _state_key(link: Link, entities: list[str]) -> str:
        return f"{link.id}|{','.join(sorted(entities))}"

    def _group_is_on(self, link: Link, key: str, entities: list[str]) -> bool:
        expected = self._expected.get(key)
        if expected and expected[1] > time.monotonic():
            return expected[0]
        states = self._states_on(entities)
        if link.options["toggle_mode"] == ToggleMode.ALL_ON:
            return bool(states) and all(states)
        return any(states)

    async def _turn(
        self,
        link: Link,
        on: bool,
        lights: list[str],
        switches: list[str],
        context: Context,
        extra: dict[str, Any] | None = None,
        attempt: int = 0,
        group: bool = True,
        key: str | None = None,
    ) -> None:
        if not lights and not switches:
            return
        if key is None:
            key = self._state_key(link, [*lights, *switches])
        opts = link.options
        if attempt == 0:
            # A newer command supersedes a pending check of the previous one.
            if task := self._verify_tasks.pop(key, None):
                task.cancel()
            self._expected[key] = (on, time.monotonic() + EXPECTED_STATE_TTL_S)

        if on:
            data: dict[str, Any] = {"transition": opts["transition"]}
            if opts["on_brightness_pct"] is not None:
                data["brightness_pct"] = opts["on_brightness_pct"]
            if opts["on_color_temp_kelvin"] is not None:
                data["color_temp_kelvin"] = opts["on_color_temp_kelvin"]
            data.update(extra or {})
            calls = [
                self._call("light", "turn_on", lights, data, context, group),
                self._call("switch", "turn_on", switches, None, context),
            ]
        else:
            calls = [
                self._call("light", "turn_off", lights, {"transition": opts["transition"]}, context, group),
                self._call("switch", "turn_off", switches, None, context),
            ]
        errors = [e for e in await asyncio.gather(*calls) if e]
        if errors:
            self.last_error[link.id] = {"time": dt_util.utcnow().isoformat(), "message": errors[0]}
            # The device refused: the next press should try the same direction again.
            if self._expected.get(key, (None,))[0] == on:
                self._expected.pop(key, None)
        elif attempt == 0:
            self.last_error.pop(link.id, None)

        verify = opts["verify"]
        if verify["enabled"]:
            # Only the newest command for these targets is checked.
            current = self._expected.get(key)
            if attempt == 0 and current is not None and current[0] != on:
                return
            task = self.entry.async_create_background_task(
                self.hass,
                self._verify(link, on, lights, switches, context, extra, attempt, errors, key, group),
                f"{DOMAIN} verify {link.name}",
            )
            self._verify_tasks[key] = task
        elif errors:
            self._notify(link, f"{link.name}: Schalten fehlgeschlagen: {errors[0]}")

    async def _wait_states(
        self, entities: list[str], ok: Callable[[State | None], bool], timeout: float
    ) -> list[str]:
        """Wait (event driven) until all entities satisfy ok; return the rest."""

        def pending() -> list[str]:
            return [e for e in entities if not ok(self.hass.states.get(e))]

        if not (rest := pending()):
            return []
        done = asyncio.Event()

        @callback
        def _changed(_event: Event) -> None:
            if not pending():
                done.set()

        unsub = async_track_state_change_event(self.hass, rest, _changed)
        try:
            async with asyncio.timeout(timeout):
                await done.wait()
        except TimeoutError:
            pass
        finally:
            unsub()
        return pending()

    async def _verify(
        self,
        link: Link,
        on: bool,
        lights: list[str],
        switches: list[str],
        context: Context,
        extra: dict[str, Any] | None,
        attempt: int,
        errors: list[str],
        key: str,
        group: bool,
    ) -> None:
        verify = link.options["verify"]
        expected = "on" if on else "off"
        mismatched = await self._wait_states(
            [*lights, *switches],
            lambda state: state is not None and state.state == expected,
            verify["timeout_s"],
        )
        if self._verify_tasks.get(key) is asyncio.current_task():
            self._verify_tasks.pop(key, None)
        if not mismatched:
            return
        if attempt < verify["retries"]:
            _LOGGER.debug("%s: retrying %s", link.name, mismatched)
            await self._turn(
                link,
                on,
                [e for e in mismatched if e.startswith("light.")],
                [e for e in mismatched if e.startswith("switch.")],
                context,
                extra,
                attempt + 1,
                group=group,
                key=key,
            )
            return
        # The command did not stick: forget the optimistic state.
        self._expected.pop(key, None)
        if verify["notify"]:
            names = ", ".join(self._name(e) for e in mismatched)
            reason = f" ({errors[0]})" if errors else ""
            word = "einschalten" if on else "ausschalten"
            self._notify(link, f"{link.name}: {names} ließ sich nicht {word}{reason}.")

    @callback
    def _notify(self, link: Link, message: str) -> None:
        persistent_notification.async_create(
            self.hass, message, title="Light Linker", notification_id=f"{DOMAIN}_{link.id}"
        )

    def _next_cycle(self, link_id: str, binding_id: str, length: int) -> int:
        key = (link_id, binding_id)
        idx = (self._cycle.get(key, -1) + 1) % length
        self._cycle[key] = idx
        return idx

    async def _gate(self, link: Link, covers: list[str], switches: list[str], context: Context) -> None:
        before = {e: getattr(self.hass.states.get(e), "state", None) for e in covers}
        errors = [
            e
            for e in await asyncio.gather(
                self._call("cover", "toggle", covers, None, context),
                self._call("switch", "toggle", switches, None, context),
            )
            if e
        ]
        if errors:
            self.last_error[link.id] = {"time": dt_util.utcnow().isoformat(), "message": errors[0]}
            self._notify(link, f"{link.name}: Tor ließ sich nicht schalten ({errors[0]}).")
            return
        self.last_error.pop(link.id, None)
        if covers and link.options["verify"]["enabled"]:
            self.entry.async_create_background_task(
                self.hass, self._verify_gate(link, before), f"{DOMAIN} gate {link.name}"
            )

    async def _verify_gate(self, link: Link, before: dict[str, str | None]) -> None:
        """Gates are never retried: a second pulse would stop or reverse them."""
        pending = await self._wait_states(
            list(before),
            lambda state: state is not None and state.state != before[state.entity_id],
            GATE_VERIFY_TIMEOUT_S,
        )
        if pending and link.options["verify"]["notify"]:
            names = ", ".join(self._name(e) for e in pending)
            self._notify(
                link, f"{link.name}: {names} hat sich nach {GATE_VERIFY_TIMEOUT_S} s nicht bewegt."
            )

    # ------------------------------------------------------------------ holds

    def _ramp_direction(self, link: Link, binding: dict[str, Any], lights: list[str]) -> str:
        action = binding["action"]
        if action == ActionType.RAMP_UP:
            return "up"
        if action == ActionType.RAMP_DOWN:
            return "down"
        params = binding["ramp"]
        current = brightness_pct(self.hass, lights)
        if current == 0 or current <= params["min_pct"]:
            direction = "up"
        elif current >= params["max_pct"]:
            direction = "down"
        else:
            direction = "down" if self._dim_dir.get((link.id, binding["id"])) == "up" else "up"
        self._dim_dir[(link.id, binding["id"])] = direction
        return direction

    def _hold_end_policy(self, src: Source, binding: dict[str, Any], has_release: bool) -> str:
        """release | repeat | step | full | none."""
        params = binding["ramp"]
        end = params["end"]
        if end != "auto":
            return end
        if has_release:
            return "release"
        if self._hold_style.get(src.key) == "repeat":
            return "repeat"
        return params["no_release"]

    async def _hold_start(
        self,
        link: Link,
        src: Source,
        binding: dict[str, Any],
        button: str | None,
        event: SlotEvent,
        has_release: bool,
        lights: list[str],
        context: Context,
    ) -> None:
        action = ActionType(binding["action"])
        session_key = (link.id, src.key, button or "")
        if action not in RAMP_ACTIONS:
            # any other action runs once; repeats of the hold are swallowed
            self._holds[session_key] = _Hold(binding=binding, ramp=None, policy="repeat")
            self._arm(session_key, REPEAT_GAP_S * 2)
            await self._async_run(link, src, {**binding, "event": SlotEvent.PRESS}, button, SlotEvent.PRESS, True, context)
            return
        if not lights:
            return
        policy = self._hold_end_policy(src, binding, has_release)
        direction = self._ramp_direction(link, binding, lights)
        self._end_session(session_key)
        if policy == "none":
            return
        if policy == "step":
            await self._step_once(link, binding, lights, direction, context)
            return
        key = self._state_key(link, lights)
        self._expected.pop(key, None)
        ramp = Ramp(self, link, binding["ramp"], lights, direction, context)
        hold = _Hold(binding=binding, ramp=ramp, policy=policy)
        self._holds[session_key] = hold
        if not await ramp.async_start():
            if self._holds.get(session_key) is hold:
                del self._holds[session_key]
            return
        if self._holds.get(session_key) is not hold:
            await ramp.async_stop()  # released while starting
            return
        if policy == "repeat":
            self._arm(session_key, REPEAT_GAP_S)
        elif policy == "release":
            self._arm(session_key, binding["ramp"]["max_s"])

    async def _step_once(
        self, link: Link, binding: dict[str, Any], lights: list[str], direction: str, context: Context
    ) -> None:
        params = binding["ramp"]
        current = brightness_pct(self.hass, lights)
        step = params["step_pct"]
        if current == 0:
            if params["when_off"] == "ignore":
                return
            target = max(step, params["min_pct"])
        elif direction == "up":
            target = min(params["max_pct"], current + step)
        else:
            target = max(params["min_pct"], current - step)
        await self.async_light_on(link, lights, {"brightness_pct": target, "transition": link.options["transition"]}, context)

    @callback
    def _arm(self, session_key: tuple[str, str, str], seconds: float) -> None:
        hold = self._holds.get(session_key)
        if hold is None:
            return
        if hold.timer:
            hold.timer.cancel()
        hold.timer = self.hass.loop.call_later(seconds, self._end_session, session_key)

    @callback
    def _keepalive(self, link: Link, src: Source, button: str | None) -> bool:
        """A repeated hold event; True if a hold of this button is running."""
        found = False
        for session_key, hold in list(self._holds.items()):
            if session_key[0] != link.id or session_key[1] != src.key:
                continue
            if button is not None and session_key[2] not in ("", button):
                continue
            found = True
            if hold.policy == "release":
                continue  # the device will send its release; max_s stays
            self._hold_style[src.key] = "repeat"
            hold.policy = "repeat"
            self._arm(session_key, REPEAT_GAP_S)
        return found

    @callback
    def _end_holds(self, link: Link, src: Source, button: str | None) -> None:
        for session_key in list(self._holds):
            if session_key[0] != link.id or session_key[1] != src.key:
                continue
            if button is not None and session_key[2] not in ("", button):
                continue
            self._end_session(session_key)

    @callback
    def _end_session(self, session_key: tuple[str, str, str]) -> None:
        hold = self._holds.pop(session_key, None)
        if hold is None:
            return
        if hold.timer:
            hold.timer.cancel()
        if hold.ramp is not None and hold.policy != "full":
            self.hass.async_create_task(hold.ramp.async_stop(), eager_start=True)

    @callback
    def _stop_dim(self, link_id: str) -> None:
        for session_key in [k for k in self._holds if k[0] == link_id]:
            self._end_session(session_key)

    # ------------------------------------------------------- conflicts, health

    @callback
    def conflicts(self) -> dict[str, list[str]]:
        """Links that react to the same event of the same button."""
        result: dict[str, list[str]] = {}
        links = list(self.links.values())
        for i, a in enumerate(links):
            for b in links[i + 1 :]:
                if not (a.enabled and b.enabled):
                    continue
                if not self._overlap(a, b):
                    continue
                result.setdefault(a.id, []).append(b.name)
                result.setdefault(b.id, []).append(a.name)
        return result

    @staticmethod
    def _slots(link: Link) -> list[tuple[str, str | None, str]]:
        """(source key, button or None, event) of every binding."""
        result = []
        for binding in link.bindings:
            for src in link.sources:
                if binding["source"] not in (None, src.key):
                    continue
                button = binding["button"] if binding["button"] is not None else src.button
                result.append((src.key, button, str(binding["event"])))
        return result

    def _overlap(self, a: Link, b: Link) -> bool:
        for key_a, button_a, event_a in self._slots(a):
            for key_b, button_b, event_b in self._slots(b):
                if key_a == key_b and event_a == event_b and (
                    button_a is None or button_b is None or button_a == button_b
                ):
                    return True
        return False

    @callback
    def missing(self, link: Link) -> list[str]:
        """Sources, targets or areas that no longer exist."""
        ent_reg = er.async_get(self.hass)
        result: list[str] = []
        for src in link.sources:
            if src.adapter == Adapter.ZHA:
                if self._zha_device(src.device_ieee or "") is None:
                    result.append(src.device_ieee or "?")
            elif ent_reg.async_get(src.entity_id or "") is None and self.hass.states.get(
                src.entity_id or ""
            ) is None:
                result.append(src.entity_id or "?")
        area_reg = ar.async_get(self.hass)
        for targets in self._all_target_specs(link):
            for entity_id in targets.get("entity_id", []):
                if entity_id in result:
                    continue
                if ent_reg.async_get(entity_id) is None and self.hass.states.get(entity_id) is None:
                    result.append(entity_id)
            result.extend(
                a for a in targets.get("area_id", [])
                if area_reg.async_get_area(a) is None and a not in result
            )
            result.extend(
                f"Gruppe {g}" for g in targets.get("group_id", [])
                if g not in self.store.groups and f"Gruppe {g}" not in result
            )
            for g in targets.get("group_id", []):
                for entity_id in self.group_members(g):
                    if entity_id not in result and ent_reg.async_get(entity_id) is None and self.hass.states.get(entity_id) is None:
                        result.append(entity_id)
        motion = link.options.get("motion") or {}
        for key in ("lux_entity", "block_entity"):
            if (entity_id := motion.get(key)) and link.profile == Profile.MOTION:
                if ent_reg.async_get(entity_id) is None and self.hass.states.get(entity_id) is None:
                    result.append(entity_id)
        return result

    @callback
    def async_update_issues(self) -> None:
        """Create or clear a repair issue per broken link."""
        for link in self.links.values():
            issue_id = f"link_broken_{link.id}"
            if missing := self.missing(link):
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="link_broken",
                    translation_placeholders={"name": link.name, "missing": ", ".join(missing)},
                    learn_more_url=f"/{PANEL_URL_PATH}",
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        moves = sum(len(v) for v in self.migrations().values())
        if moves:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "z2m_migration",
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="z2m_migration",
                translation_placeholders={"count": str(moves)},
                learn_more_url=f"/{PANEL_URL_PATH}",
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "z2m_migration")

    # ----------------------------------------------------- ZHA -> Z2M, extern

    @callback
    def migrations(self) -> dict[str, list[dict[str, Any]]]:
        """Per link: sources and targets that can move to Zigbee2MQTT."""
        result = {}
        for link in self.links.values():
            if found := z2m.suggestions(self.hass, link, self.store.ieee_hints):
                result[link.id] = found
        return result

    @callback
    def async_apply_migrations(self, link_ids: list[str] | None = None) -> int:
        """Replace ZHA sources/targets by their Z2M counterparts; returns the count."""
        count = 0
        for link_id, moves in self.migrations().items():
            if link_ids is not None and link_id not in link_ids:
                continue
            link = self.links[link_id]
            for move in moves:
                if move["kind"] == "source":
                    src = link.sources[move["index"]]
                    old_key = src.key
                    src.adapter = Adapter.EVENT_ENTITY
                    src.entity_id = move["new"]
                    src.device_ieee = None
                    self._rekey_bindings(link, old_key, src.key)
                else:
                    for spec in self._all_target_specs(link):
                        ids = spec.get("entity_id", [])
                        spec["entity_id"] = [move["new"] if e == move["old"] else e for e in ids]
                count += 1
            link.updated_at = dt_util.utcnow().isoformat()
            self._forget(link_id)
        if count:
            self._changed()
        return count

    @staticmethod
    def _rekey_bindings(link: Link, old_key: str, new_key: str) -> None:
        for binding in link.bindings:
            if binding["source"] == old_key:
                binding["source"] = new_key

    @callback
    def async_set_alias(self, key: str, name: str | None) -> None:
        """Readable name of a button / remote shown in the panel and logbook."""
        if name:
            self.store.aliases[key] = name
        else:
            self.store.aliases.pop(key, None)
        self.store.async_schedule_save()
        async_dispatcher_send(self.hass, SIGNAL_LINKS_CHANGED)

    @callback
    def async_set_external(self, key: str, note: str | None) -> None:
        """Mark a source as also used elsewhere (Node-RED, automations)."""
        if note:
            self.store.external[key] = note
        else:
            self.store.external.pop(key, None)
        self.store.async_schedule_save()
        async_dispatcher_send(self.hass, SIGNAL_LINKS_CHANGED)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _all_target_specs(link: Link) -> list[dict[str, list[str]]]:
        specs = [link.targets]
        specs.extend(b["targets"] for b in link.bindings if b.get("targets") is not None)
        return specs

    @callback
    def resolve_targets(self, link: Link) -> list[str]:
        """Entity ids of all targets of the link and its bindings, areas expanded."""
        result: list[str] = []
        for spec in self._all_target_specs(link):
            for entity_id in self._expand(spec):
                if entity_id not in result:
                    result.append(entity_id)
        return result

    @callback
    def resolve_binding_targets(self, link: Link, binding: dict[str, Any]) -> list[str]:
        """Entity ids one binding switches."""
        return self._expand(link.binding_targets(binding))

    @callback
    def group_members(self, group_id: str, _seen: frozenset[str] = frozenset()) -> list[str]:
        """Entity ids of a Light Linker group, nested groups expanded."""
        group = self.store.groups.get(group_id)
        if group is None or group_id in _seen:
            return []
        result: list[str] = []
        for member in group["members"]:
            if member.startswith("group:"):
                found = self.group_members(member[6:], _seen | {group_id})
            else:
                found = [member]
            result.extend(e for e in found if e not in result)
        return result

    @callback
    def _expand(self, targets: dict[str, list[str]]) -> list[str]:
        result: list[str] = []
        for entity_id in targets.get("entity_id", []):
            if entity_id not in result:
                result.append(entity_id)
        for group_id in targets.get("group_id", []):
            result.extend(e for e in self.group_members(group_id) if e not in result)
        areas = targets.get("area_id", [])
        if not areas:
            return result
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)

        def _ok(entry: er.RegistryEntry) -> bool:
            return (
                entry.domain in TARGET_DOMAINS
                and entry.disabled_by is None
                and entry.hidden_by is None
                and entry.entity_category is None
            )

        for area_id in areas:
            for entry in er.async_entries_for_area(ent_reg, area_id):
                if _ok(entry) and entry.entity_id not in result:
                    result.append(entry.entity_id)
            for device in dr.async_entries_for_area(dev_reg, area_id):
                for entry in er.async_entries_for_device(ent_reg, device.id):
                    if entry.area_id is None and _ok(entry) and entry.entity_id not in result:
                        result.append(entry.entity_id)
        return result

    def _name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    @callback
    def _zha_device(self, ieee: str) -> dr.DeviceEntry | None:
        return z2m.find_device(self.hass, ("zha", ieee.lower()))

    @callback
    def area_id_of(self, entity_id: str) -> str | None:
        """Area of an entity, falling back to its device."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            return None
        if entry.area_id:
            return entry.area_id
        if entry.device_id and (device := dr.async_get(self.hass).async_get(entry.device_id)):
            return device.area_id
        return None

    @callback
    def _area_name(self, area_id: str | None) -> str | None:
        if area_id is None:
            return None
        area = ar.async_get(self.hass).async_get_area(area_id)
        return area.name if area else None

    @callback
    def _handle_registry_update(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """Follow entity id renames; re-check health on add/remove."""
        data = event.data
        if data["action"] == "update" and "old_entity_id" in data:
            old, new = data["old_entity_id"], data["entity_id"]
            changed = False
            for link in self.links.values():
                for src in link.sources:
                    if src.entity_id == old:
                        old_key = src.key
                        src.entity_id = new
                        self._rekey_bindings(link, old_key, src.key)
                        changed = True
                for spec in self._all_target_specs(link):
                    ids = spec.get("entity_id", [])
                    if old in ids:
                        spec["entity_id"] = [new if e == old else e for e in ids]
                        changed = True
            for group in self.store.groups.values():
                if old in group["members"]:
                    group["members"] = [new if m == old else m for m in group["members"]]
                    changed = True
            if changed:
                _LOGGER.info("Updated links after rename %s -> %s", old, new)
                self._changed()
                return
        if data["action"] in ("create", "remove"):
            self.async_update_issues()

    @callback
    def _handle_device_update(self, event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        if event.data["action"] in ("create", "remove"):
            self.async_update_issues()
