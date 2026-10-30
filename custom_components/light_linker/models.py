"""Data model for Light Linker."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (
    RAMP_ACTIONS,
    SLOT_GROUP,
    ActionType,
    Adapter,
    EventGroup,
    EventKind,
    Profile,
    SlotEvent,
    ToggleMode,
)

# ---------------------------------------------------------------------------
# Validation schemas (used by the WebSocket API and when loading the store)
# ---------------------------------------------------------------------------

_COLOR_LIST = [
    vol.Schema(
        {
            vol.Required("rgb"): vol.All(
                [vol.All(vol.Coerce(int), vol.Range(0, 255))], vol.Length(3, 3)
            ),
            vol.Optional("name", default=""): str,
        }
    )
]

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("type", default=ActionType.NONE): vol.Coerce(ActionType),
        vol.Optional("brightness_pct"): vol.All(vol.Coerce(int), vol.Range(1, 100)),
        vol.Optional("color_temp_kelvin"): vol.All(vol.Coerce(int), vol.Range(1000, 10000)),
        vol.Optional("kelvin_list"): [vol.All(vol.Coerce(int), vol.Range(1000, 10000))],
        vol.Optional("color_list"): [
            vol.Schema(
                {
                    vol.Required("rgb"): vol.All(
                        [vol.All(vol.Coerce(int), vol.Range(0, 255))], vol.Length(3, 3)
                    ),
                    vol.Optional("name", default=""): str,
                }
            )
        ],
        vol.Optional("scene"): cv.entity_id,
    }
)

def _source_identity(value: dict[str, Any]) -> dict[str, Any]:
    """ZHA sources are identified by device IEEE, all others by entity_id."""
    if value["adapter"] == Adapter.ZHA:
        if not value.get("device_ieee"):
            raise vol.Invalid("zha sources need device_ieee")
        value["entity_id"] = None
    elif not value.get("entity_id"):
        raise vol.Invalid("entity_id is required")
    return value


_SOURCE_BASE = vol.Schema(
    {
        vol.Required("adapter"): vol.Coerce(Adapter),
        vol.Optional("entity_id"): vol.Any(None, cv.entity_id),
        vol.Optional("device_ieee"): vol.Any(
            None, vol.All(str, vol.Lower, vol.Match(r"^([0-9a-f]{2}:){7}[0-9a-f]{2}$"))
        ),
        vol.Optional("button"): vol.Any(None, str),
        # state_input: button = rising edge is a press, switch = every edge toggles,
        # mirror = on/off follow the input
        vol.Optional("mode", default="button"): vol.In(["button", "switch", "mirror"]),
        # rocker: which role this source/button plays
        vol.Optional("role"): vol.Any(None, vol.In(["up", "down"])),
    }
)

MOTION_SCHEMA = vol.Schema(
    {
        # Illuminance sensor; None = always dark enough
        vol.Optional("lux_entity", default=None): vol.Any(None, cv.entity_id),
        vol.Optional("lux_threshold", default=36): vol.All(vol.Coerce(float), vol.Range(0, 100000)),
        # Run-on after all sensors report clear
        vol.Optional("off_delay_s", default=30): vol.All(vol.Coerce(int), vol.Range(0, 86400)),
        # Manually switched on: off this long after the room is empty; None = never
        vol.Optional("manual_off_delay_s", default=600): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(0, 86400))
        ),
        # Manually switched off while occupied: no automatic on until the room was
        # empty for off_delay_s ("until_empty") or for a fixed time ("timed")
        vol.Optional("manual_off_block", default="until_empty"): vol.In(["until_empty", "timed"]),
        vol.Optional("manual_off_block_s", default=600): vol.All(vol.Coerce(int), vol.Range(0, 86400)),
        # Automatic switching pauses while this entity is on
        vol.Optional("block_entity", default=None): vol.Any(None, cv.entity_id),
        # Only switch off automatically, never on
        vol.Optional("only_off", default=False): bool,
    }
)
SOURCE_SCHEMA = vol.All(_SOURCE_BASE, _source_identity)

ALL_EVENT_GROUPS = [str(group) for group in EventGroup]

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("on_brightness_pct", default=None): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(1, 100))
        ),
        vol.Optional("on_color_temp_kelvin", default=None): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(1000, 10000))
        ),
        vol.Optional("transition", default=0.4): vol.All(vol.Coerce(float), vol.Range(0, 10)),
        vol.Optional("toggle_mode", default=ToggleMode.ANY_ON): vol.Coerce(ToggleMode),
        vol.Optional("dim_step_pct", default=10): vol.All(vol.Coerce(int), vol.Range(1, 50)),
        vol.Optional("dim_interval_ms", default=400): vol.All(
            vol.Coerce(int), vol.Range(100, 2000)
        ),
        vol.Optional("min_brightness_pct", default=3): vol.All(
            vol.Coerce(int), vol.Range(1, 50)
        ),
        vol.Optional("dim_timeout_s", default=8): vol.All(vol.Coerce(float), vol.Range(1, 60)),
        vol.Optional("hold_without_release", default="step"): vol.In(["step", "none"]),
        vol.Optional("hold_step_pct", default=25): vol.All(vol.Coerce(int), vol.Range(1, 100)),
        # Which button events this link reacts to; others are left to other links.
        vol.Optional("events", default=lambda: list(ALL_EVENT_GROUPS)): vol.All(
            cv.ensure_list, [vol.In(ALL_EVENT_GROUPS)], vol.Length(min=1)
        ),
        vol.Optional("motion", default=dict): MOTION_SCHEMA,
        vol.Optional("double", default=dict): ACTION_SCHEMA,
        vol.Optional("triple", default=dict): ACTION_SCHEMA,
        vol.Optional("verify", default=dict): vol.Schema(
            {
                vol.Optional("enabled", default=True): bool,
                vol.Optional("timeout_s", default=1.5): vol.All(
                    vol.Coerce(float), vol.Range(0.5, 120)
                ),
                vol.Optional("retries", default=1): vol.All(vol.Coerce(int), vol.Range(0, 3)),
                vol.Optional("notify", default=True): bool,
            }
        ),
    }
)

TARGETS_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id", default=list): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional("area_id", default=list): vol.All(cv.ensure_list, [cv.string]),
        # Light Linker groups (store.groups)
        vol.Optional("group_id", default=list): vol.All(cv.ensure_list, [cv.string]),
    }
)

GROUP_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): vol.Any(None, str),
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=80)),
        vol.Optional("area_id", default=None): vol.Any(None, cv.string),
        # entity ids and "group:<id>" for nested groups
        vol.Required("members"): vol.All(
            cv.ensure_list,
            [vol.Any(vol.Match(r"^group:[A-Za-z0-9_-]+$"), cv.entity_id)],
        ),
    },
    extra=vol.REMOVE_EXTRA,
)

RAMP_SCHEMA = vol.Schema(
    {
        # auto = native Zigbee where the lamp allows it, otherwise steps
        vol.Optional("mode", default="auto"): vol.In(["auto", "native", "transition", "steps"]),
        # seconds from the lower to the upper limit
        vol.Optional("duration_s", default=4.0): vol.All(vol.Coerce(float), vol.Range(0.5, 30)),
        vol.Optional("min_pct", default=3): vol.All(vol.Coerce(int), vol.Range(1, 50)),
        vol.Optional("max_pct", default=100): vol.All(vol.Coerce(int), vol.Range(10, 100)),
        # light off: up starts at min_pct ("on_min") or nothing happens ("ignore")
        vol.Optional("when_off", default="on_min"): vol.In(["on_min", "ignore"]),
        # how the end of the hold is recognised; auto = from the device
        vol.Optional("end", default="auto"): vol.In(["auto", "release", "repeat", "full"]),
        # what a hold does when the device reports no end at all
        vol.Optional("no_release", default="step"): vol.In(["step", "full", "none"]),
        vol.Optional("step_pct", default=25): vol.All(vol.Coerce(int), vol.Range(1, 100)),
        # safety stop
        vol.Optional("max_s", default=8.0): vol.All(vol.Coerce(float), vol.Range(1, 60)),
        # steps mode cadence
        vol.Optional("interval_ms", default=400): vol.All(vol.Coerce(int), vol.Range(100, 2000)),
    }
)


def _binding_defaults(value: dict[str, Any]) -> dict[str, Any]:
    if not value.get("id"):
        value["id"] = ulid_now()
    return value


BINDING_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("id"): vol.Any(None, str),
            # "adapter:ident" of one source of the link; None = every source
            vol.Optional("source", default=None): vol.Any(None, str),
            # None = every button of the source
            vol.Optional("button", default=None): vol.Any(None, vol.Coerce(str)),
            vol.Required("event"): vol.Coerce(SlotEvent),
            vol.Required("action"): vol.Coerce(ActionType),
            # None = the targets of the link
            vol.Optional("targets", default=None): vol.Any(None, TARGETS_SCHEMA),
            vol.Optional("brightness_pct"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(1, 100))),
            vol.Optional("color_temp_kelvin"): vol.Any(
                None, vol.All(vol.Coerce(int), vol.Range(1000, 10000))
            ),
            vol.Optional("kelvin_list"): [vol.All(vol.Coerce(int), vol.Range(1000, 10000))],
            vol.Optional("color_list"): _COLOR_LIST,
            vol.Optional("scene"): vol.Any(None, cv.entity_id),
            vol.Optional("ramp", default=dict): RAMP_SCHEMA,
        },
        extra=vol.REMOVE_EXTRA,
    ),
    _binding_defaults,
)


def _unique_slots(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, str]] = set()
    for binding in bindings:
        slot = (binding["source"], binding["button"], str(binding["event"]))
        if slot in seen:
            raise vol.Invalid(
                f"Taste {binding['button'] or 'alle'} / {binding['event']} ist doppelt belegt"
            )
        seen.add(slot)
    return bindings

LINK_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=80)),
        vol.Optional("enabled", default=True): bool,
        vol.Required("profile"): vol.Coerce(Profile),
        vol.Required("sources"): vol.All([SOURCE_SCHEMA], vol.Length(min=1)),
        vol.Required("targets"): TARGETS_SCHEMA,
        vol.Optional("options", default=dict): OPTIONS_SCHEMA,
        # missing = old payload: generated from the profile template
        vol.Optional("bindings"): vol.All([BINDING_SCHEMA], _unique_slots),
        vol.Optional("dashboard_button", default=False): bool,
        vol.Optional("external_note"): vol.Any(None, str),
        vol.Optional("created_at"): str,
        vol.Optional("updated_at"): str,
    },
    extra=vol.REMOVE_EXTRA,
)


# ---------------------------------------------------------------------------
# Runtime types
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class NormalizedEvent:
    """A button event, independent of the stack it came from."""

    source_key: str
    entity_id: str
    button: str | None
    kind: EventKind
    direction: str | None
    raw_type: str
    has_release: bool
    fired_at: datetime


@dataclass(slots=True)
class Source:
    """One source of a link."""

    adapter: Adapter
    entity_id: str | None = None
    device_ieee: str | None = None
    button: str | None = None
    mode: str = "button"
    role: str | None = None

    @property
    def ident(self) -> str:
        """Entity id, or device IEEE for ZHA."""
        return self.device_ieee if self.adapter == Adapter.ZHA else self.entity_id  # type: ignore[return-value]

    @property
    def key(self) -> str:
        """Key used by the dispatcher index."""
        return f"{self.adapter}:{self.ident}"


@dataclass(slots=True)
class Link:
    """A link between sources and targets."""

    id: str
    name: str
    enabled: bool
    profile: Profile
    sources: list[Source]
    targets: dict[str, list[str]]
    options: dict[str, Any]
    bindings: list[dict[str, Any]] = field(default_factory=list)
    dashboard_button: bool = False
    external_note: str | None = None
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Link:
        """Validate and build a link from stored or submitted data."""
        clean = LINK_SCHEMA(data)
        sources = [Source(**src) for src in clean["sources"]]
        bindings = clean.get("bindings")
        if bindings is None:
            bindings = template_bindings(clean["profile"], sources, clean["options"])
        keys = {src.key for src in sources}
        for binding in bindings:
            if binding["source"] is not None and binding["source"] not in keys:
                raise vol.Invalid(f"Belegung verweist auf unbekannte Quelle {binding['source']}")
        return cls(
            id=clean.get("id") or ulid_now(),
            name=clean["name"],
            enabled=clean["enabled"],
            profile=clean["profile"],
            sources=sources,
            targets=clean["targets"],
            options=clean["options"],
            bindings=bindings,
            dashboard_button=clean["dashboard_button"],
            external_note=clean.get("external_note"),
            created_at=clean.get("created_at") or dt_util.utcnow().isoformat(),
            updated_at=clean.get("updated_at") or dt_util.utcnow().isoformat(),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize for the store and the WebSocket API."""
        data = asdict(self)
        data["profile"] = str(self.profile)
        data["sources"] = [
            {**asdict(src), "adapter": str(src.adapter)} for src in self.sources
        ]
        data["bindings"] = [
            {**b, "event": str(b["event"]), "action": str(b["action"])} for b in self.bindings
        ]
        return data

    def binding_targets(self, binding: dict[str, Any]) -> dict[str, list[str]]:
        """Targets of one binding (its own or the link's)."""
        return binding["targets"] if binding.get("targets") is not None else self.targets


# ---------------------------------------------------------------------------
# Templates: the v0.3 profiles expressed as bindings
# ---------------------------------------------------------------------------


def _ramp_from_options(options: dict[str, Any]) -> dict[str, Any]:
    """The v0.3 dim settings as ramp settings ("steps" keeps the old feel)."""
    step = options["dim_step_pct"]
    interval = options["dim_interval_ms"]
    return RAMP_SCHEMA(
        {
            "mode": "steps",
            "duration_s": round(min(30.0, max(0.5, interval * 100 / step / 1000)), 2),
            "interval_ms": interval,
            "min_pct": options["min_brightness_pct"],
            "max_s": options["dim_timeout_s"],
            "no_release": options["hold_without_release"],
            "step_pct": options["hold_step_pct"],
        }
    )


def _profile_actions(profile: Profile, role: str | None) -> dict[SlotEvent, ActionType]:
    """Slot event -> action of a profile for one button."""
    hold = {
        SlotEvent.HOLD: ActionType.RAMP_ALT,
        SlotEvent.HOLD_UP: ActionType.RAMP_UP,
        SlotEvent.HOLD_DOWN: ActionType.RAMP_DOWN,
    }
    if profile == Profile.GATE:
        return {SlotEvent.PRESS: ActionType.COVER_TOGGLE}
    if profile == Profile.SWITCH:
        return {SlotEvent.PRESS: ActionType.TOGGLE, SlotEvent.ON: ActionType.ON, SlotEvent.OFF: ActionType.OFF}
    if profile == Profile.ROCKER:
        if role == "up":
            return {
                SlotEvent.PRESS: ActionType.ON, SlotEvent.ON: ActionType.ON, SlotEvent.OFF: ActionType.OFF,
                **hold, SlotEvent.HOLD: ActionType.RAMP_UP,
            }
        if role == "down":
            return {
                SlotEvent.PRESS: ActionType.OFF, SlotEvent.ON: ActionType.ON, SlotEvent.OFF: ActionType.OFF,
                **hold, SlotEvent.HOLD: ActionType.RAMP_DOWN,
            }
        return {SlotEvent.PRESS: ActionType.TOGGLE, SlotEvent.ON: ActionType.ON, SlotEvent.OFF: ActionType.OFF, **hold}
    # toggle, motion (buttons inside a motion link), custom
    return {SlotEvent.PRESS: ActionType.TOGGLE, SlotEvent.ON: ActionType.TOGGLE, SlotEvent.OFF: ActionType.OFF, **hold}


def template_bindings(
    profile: Profile, sources: list[Source], options: dict[str, Any]
) -> list[dict[str, Any]]:
    """Bindings that reproduce a v0.3 profile exactly."""
    groups = set(options.get("events") or SLOT_GROUP.values())
    if profile == Profile.GATE:
        groups = {"click"}
    ramp = _ramp_from_options(options)
    result: list[dict[str, Any]] = []
    for src in sources:
        if src.adapter == Adapter.OCCUPANCY:
            continue
        actions = _profile_actions(profile, src.role)
        slots: dict[SlotEvent, ActionType] = {}
        if src.adapter == Adapter.STATE_INPUT:
            # v0.3 converted edges by the source mode first
            if src.mode == "switch":
                slots = {SlotEvent.RISE: actions[SlotEvent.PRESS], SlotEvent.FALL: actions[SlotEvent.PRESS]}
            elif src.mode == "mirror":
                if SlotEvent.ON in actions:
                    slots[SlotEvent.RISE] = actions[SlotEvent.ON]
                if SlotEvent.OFF in actions:
                    slots[SlotEvent.FALL] = actions[SlotEvent.OFF]
            else:
                slots = {SlotEvent.RISE: actions[SlotEvent.PRESS]}
        else:
            slots = dict(actions)
            if profile != Profile.GATE:
                for kind in ("double", "triple"):
                    action = (options.get(kind) or {}).get("type", ActionType.NONE)
                    if action != ActionType.NONE:
                        slots[SlotEvent(kind)] = action
        for event, action in slots.items():
            if SLOT_GROUP[str(event)] not in groups:
                continue
            binding: dict[str, Any] = {
                "source": src.key,
                "button": src.button,
                "event": event,
                "action": ActionType(action),
                "targets": None,
            }
            if event in (SlotEvent.DOUBLE, SlotEvent.TRIPLE):
                cfg = options.get(str(event)) or {}
                for key in ("brightness_pct", "color_temp_kelvin", "kelvin_list", "color_list", "scene"):
                    if key in cfg:
                        binding[key] = cfg[key]
            if ActionType(action) in RAMP_ACTIONS:
                binding["ramp"] = dict(ramp)
            result.append(BINDING_SCHEMA(binding))
    return _unique_slots(result)
