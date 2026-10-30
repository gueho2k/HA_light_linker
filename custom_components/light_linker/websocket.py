"""WebSocket API used by the panel. All commands are admin-only."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .adapters.device_maps import buttons_from_event_types, has_release
from .const import (
    DEFAULT_OFF_DELAY_S,
    ActionType,
    Adapter,
    DOMAIN,
    OCCUPANCY_CLASSES,
    HIDDEN_SOURCE_MODELS,
    LEARN_DURATION_S,
    TARGET_DOMAINS,
    EventKind,
    Profile,
)
from .data import DATA_ENGINE
from .devices import describe
from .engine import Engine, LinkNotFound


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all commands."""
    for handler in (
        ws_links_list,
        ws_links_create,
        ws_links_update,
        ws_links_delete,
        ws_links_test,
        ws_bindings_test,
        ws_presses_subscribe,
        ws_sources_list,
        ws_targets_list,
        ws_learn_subscribe,
        ws_activity_subscribe,
        ws_migrations_list,
        ws_migrations_apply,
        ws_external_set,
        ws_links_dedupe,
        ws_groups_list,
        ws_sources_alias,
        ws_groups_save,
        ws_groups_delete,
        ws_sources_remove,
    ):
        websocket_api.async_register_command(hass, handler)


def _engine(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int) -> Engine | None:
    engine = hass.data.get(DATA_ENGINE)
    if engine is None:
        connection.send_error(msg_id, "not_loaded", "Light Linker is not loaded")
    return engine


def _link_payload(
    hass: HomeAssistant,
    engine: Engine,
    link_id: str,
    conflicts: dict[str, list[str]] | None = None,
    dups: dict[str, int] | None = None,
) -> dict[str, Any]:
    link = engine.links[link_id]
    missing = engine.missing(link)
    ent_reg = er.async_get(hass)
    if conflicts is None:
        conflicts = engine.conflicts()
    if dups is None:
        dups = engine.duplicates()
    return {
        **link.as_dict(),
        "status": {
            "broken": bool(missing),
            "missing": missing,
            "last_triggered": engine.last_triggered.get(link_id),
            "last_error": engine.last_error.get(link_id),
            "conflicts": conflicts.get(link_id, []),
            "resolved_targets": engine.resolve_targets(link),
            "switch_entity": ent_reg.async_get_entity_id("switch", DOMAIN, link_id),
            "button_entity": ent_reg.async_get_entity_id("button", DOMAIN, f"{link_id}_button"),
            "sensor_entity": ent_reg.async_get_entity_id("sensor", DOMAIN, f"{link_id}_motion_state"),
            "motion": engine.motion_status(link_id),
            "z2m_group": _group_name(engine, link),
            "duplicates": {bid: n for b in link.bindings if (n := dups.get(bid := b["id"]))},
            "external": [
                note for src in link.sources if (note := engine.store.external.get(src.key))
            ],
        },
    }


def _group_name(engine: Engine, link: Any) -> str | None:
    if link.profile == Profile.MOTION:
        return None
    lights = [e for e in engine.resolve_targets(link) if e.startswith("light.")]
    found = engine.z2m.group_for(lights)
    return found[1] if found else None


# --------------------------------------------------------------------- links


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/links/list"})
@websocket_api.require_admin
@callback
def ws_links_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List all links."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    conflicts = engine.conflicts()
    dups = engine.duplicates()
    connection.send_result(
        msg["id"],
        {"links": [_link_payload(hass, engine, lid, conflicts, dups) for lid in engine.links]},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/sources/alias",
        vol.Required("source"): str,
        vol.Optional("name"): vol.Any(None, vol.All(str, vol.Length(max=80))),
    }
)
@websocket_api.require_admin
@callback
def ws_sources_alias(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Give a button a readable name (empty = back to the device name)."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    engine.async_set_alias(msg["source"], (msg.get("name") or "").strip() or None)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/groups/list"})
@websocket_api.require_admin
@callback
def ws_groups_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Light Linker groups."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    connection.send_result(msg["id"], {"groups": engine.groups_status()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/groups/save", vol.Required("group"): dict}
)
@websocket_api.require_admin
@callback
def ws_groups_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Create or update a group."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    try:
        group = engine.async_save_group(msg["group"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"group": group})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/groups/delete", vol.Required("group_id"): str}
)
@websocket_api.require_admin
@callback
def ws_groups_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete a group."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    try:
        used = engine.async_delete_group(msg["group_id"])
    except LinkNotFound:
        connection.send_error(msg["id"], "not_found", "Unknown group")
        return
    connection.send_result(msg["id"], {"used": used})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/links/dedupe"})
@websocket_api.require_admin
@callback
def ws_links_dedupe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Remove identical bindings; delete links that become empty."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    connection.send_result(msg["id"], engine.async_dedupe())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/sources/remove", vol.Required("source"): str}
)
@websocket_api.require_admin
@callback
def ws_sources_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Take a button out of all links."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    connection.send_result(msg["id"], engine.async_remove_source(msg["source"]))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/links/create", vol.Required("link"): dict}
)
@websocket_api.require_admin
@callback
def ws_links_create(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Create a link."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    try:
        link = engine.async_create_link(msg["link"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"link": _link_payload(hass, engine, link.id)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/links/update",
        vol.Required("link_id"): str,
        vol.Required("link"): dict,
        vol.Optional("updated_at"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_links_update(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Replace a link; updated_at protects against overwriting newer changes."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    current = engine.links.get(msg["link_id"])
    if current is None:
        connection.send_error(msg["id"], "not_found", "Unknown link")
        return
    if "updated_at" in msg and msg["updated_at"] != current.updated_at:
        connection.send_error(msg["id"], "conflict", "Link was changed elsewhere")
        return
    try:
        link = engine.async_update_link(msg["link_id"], msg["link"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"link": _link_payload(hass, engine, link.id)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/links/delete", vol.Required("link_id"): str}
)
@websocket_api.require_admin
@callback
def ws_links_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete a link."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    try:
        engine.async_delete_link(msg["link_id"])
    except LinkNotFound:
        connection.send_error(msg["id"], "not_found", "Unknown link")
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/links/test",
        vol.Required("link_id"): str,
        vol.Optional("kind", default=EventKind.PRESS): vol.Coerce(EventKind),
        vol.Optional("confirm", default=False): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_links_test(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Simulate an event. Gates need an explicit confirmation."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    link = engine.links.get(msg["link_id"])
    if link is None:
        connection.send_error(msg["id"], "not_found", "Unknown link")
        return
    if link.profile == Profile.GATE and not msg["confirm"]:
        connection.send_error(msg["id"], "confirm_required", "Gate test needs confirmation")
        return
    engine.async_trigger(link.id, msg["kind"], origin="test")
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/bindings/test",
        vol.Required("link_id"): str,
        vol.Required("binding_id"): str,
        vol.Optional("confirm", default=False): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_bindings_test(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Run one binding like its button would. Gates need a confirmation."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    link = engine.links.get(msg["link_id"])
    binding = next((b for b in link.bindings if b["id"] == msg["binding_id"]), None) if link else None
    if binding is None:
        connection.send_error(msg["id"], "not_found", "Unknown binding")
        return
    if binding["action"] == ActionType.COVER_TOGGLE and not msg["confirm"]:
        connection.send_error(msg["id"], "confirm_required", "Gate test needs confirmation")
        return
    engine.async_test_binding(link.id, binding["id"], origin="test")
    connection.send_result(msg["id"])


# ------------------------------------------------------------------- catalog


def _area_of(entry: er.RegistryEntry | None, dev_reg: dr.DeviceRegistry) -> str | None:
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dev_reg.async_get(entry.device_id)):
        return device.area_id
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/sources/list"})
@websocket_api.require_admin
@callback
def ws_sources_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Event entities that can act as sources (virtual CCU buttons hidden)."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    sources = []
    for state in hass.states.async_all("event"):
        entry = ent_reg.async_get(state.entity_id)
        device = dev_reg.async_get(entry.device_id) if entry and entry.device_id else None
        if device and device.model in HIDDEN_SOURCE_MODELS:
            continue
        event_types = list(state.attributes.get("event_types") or [])
        buttons = buttons_from_event_types(event_types)
        if (btn := state.attributes.get("button")) not in (None, "") and str(btn) not in buttons:
            buttons.append(str(btn))
        sources.append(
            {
                "adapter": "event_entity",
                "entity_id": state.entity_id,
                "name": state.name,
                "device": (device.name_by_user or device.name) if device else None,
                "_device": device,
                "area_id": _area_of(entry, dev_reg),
                "event_types": event_types,
                "buttons": buttons,
                "has_release": has_release(event_types),
            }
        )
    sources.extend(_zha_sources(hass, ent_reg, dev_reg))
    sources.extend(_occupancy_sources(hass, ent_reg, dev_reg))
    sources.extend(_input_sources(hass, ent_reg, dev_reg))
    engine = hass.data.get(DATA_ENGINE)
    external = engine.store.external if engine else {}
    seen = engine.store.seen_buttons if engine else {}
    library = engine.library.entries if engine else []
    for src in sources:
        ident = src["device_ieee"] if src["adapter"] == "zha" else src["entity_id"]
        key = f"{src['adapter']}:{ident}"
        src["key"] = key
        src["external"] = external.get(key)
        src["alias"] = engine.store.aliases.get(key) if engine else None
        device = src.pop("_device", None)
        buttons = list(dict.fromkeys([*src["buttons"], *seen.get(key, [])]))
        src["buttons"] = buttons
        src["model"] = device.model if device else None
        src["manufacturer"] = device.manufacturer if device else None
        src["layout"] = describe(library, device, Adapter(src["adapter"]), src["event_types"], buttons)
    illuminance = [
        {"entity_id": st.entity_id, "name": st.name, "area_id": _area_of(ent_reg.async_get(st.entity_id), dev_reg)}
        for st in hass.states.async_all("sensor")
        if st.attributes.get("device_class") == "illuminance"
    ]
    connection.send_result(msg["id"], {"sources": sources, "illuminance": illuminance})


def _occupancy_sources(
    hass: HomeAssistant, ent_reg: er.EntityRegistry, dev_reg: dr.DeviceRegistry
) -> list[dict[str, Any]]:
    """Motion, occupancy and presence sensors with the light sensor of the same device."""
    result = []
    for state in hass.states.async_all("binary_sensor"):
        device_class = state.attributes.get("device_class")
        if device_class not in OCCUPANCY_CLASSES:
            continue
        entry = ent_reg.async_get(state.entity_id)
        lux = None
        if entry and entry.device_id:
            for sibling in er.async_entries_for_device(ent_reg, entry.device_id):
                sib_state = hass.states.get(sibling.entity_id)
                if sibling.domain == "sensor" and sib_state and sib_state.attributes.get("device_class") == "illuminance":
                    lux = sibling.entity_id
                    break
        result.append(
            {
                "adapter": "occupancy",
                "entity_id": state.entity_id,
                "name": state.name,
                "device": None,
                "area_id": _area_of(entry, dev_reg),
                "device_class": device_class,
                "default_off_delay_s": DEFAULT_OFF_DELAY_S.get(device_class, 30),
                "lux_entity": lux,
                "event_types": [],
                "buttons": [],
                "has_release": False,
            }
        )
    return result


_NON_REMOTE_DOMAINS = frozenset({"light", "switch", "cover", "climate", "fan", "lock", "binary_sensor"})


def _zha_sources(
    hass: HomeAssistant, ent_reg: er.EntityRegistry, dev_reg: dr.DeviceRegistry
) -> list[dict[str, Any]]:
    """ZHA devices that look like remotes (no actuator or sensor entities).

    Only devices of ZHA config entries are looked at; identifiers of other
    integrations may have any length.
    """
    result = []
    devices = [
        device
        for zha_entry in hass.config_entries.async_entries("zha")
        for device in dr.async_entries_for_config_entry(dev_reg, zha_entry.entry_id)
    ]
    for device in devices:
        ieee = next(
            (ident[1] for ident in device.identifiers if len(ident) >= 2 and ident[0] == "zha"),
            None,
        )
        if ieee is None or device.via_device_id is None:
            continue  # not a ZHA device, or the coordinator itself
        domains = {e.domain for e in er.async_entries_for_device(ent_reg, device.id, True)}
        if domains & _NON_REMOTE_DOMAINS:
            continue
        result.append(
            {
                "adapter": "zha",
                "entity_id": None,
                "device_ieee": ieee.lower(),
                "name": device.name_by_user or device.name,
                "device": device.name_by_user or device.name,
                "_device": device,
                "area_id": device.area_id,
                "event_types": [],
                "buttons": [],
                "has_release": False,
            }
        )
    return result


def _input_sources(
    hass: HomeAssistant, ent_reg: er.EntityRegistry, dev_reg: dr.DeviceRegistry
) -> list[dict[str, Any]]:
    """Inputs already used in links (binary sensors, input_boolean, relays).

    All binary sensors would flood the list; others come in through learning.
    """
    engine = hass.data.get(DATA_ENGINE)
    if engine is None:
        return []
    used = {
        src.entity_id
        for link in engine.links.values()
        for src in link.sources
        if src.adapter == Adapter.STATE_INPUT and src.entity_id
    }
    result = []
    for entity_id in sorted(used):
        state = hass.states.get(entity_id)
        entry = ent_reg.async_get(entity_id)
        result.append(
            {
                "adapter": "state_input",
                "entity_id": entity_id,
                "name": state.name if state else entity_id,
                "device": None,
                "area_id": _area_of(entry, dev_reg),
                "event_types": [],
                "buttons": [],
                "has_release": True,
            }
        )
    return result


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/targets/list"})
@websocket_api.require_admin
@callback
def ws_targets_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Lights, switches and covers plus all areas."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    targets = []
    for domain in TARGET_DOMAINS:
        for state in hass.states.async_all(domain):
            entry = ent_reg.async_get(state.entity_id)
            if entry and (entry.entity_category is not None or entry.hidden_by is not None):
                continue
            if entry and entry.platform == DOMAIN:
                continue  # our own "aktiv" switches are no lamps
            device = dev_reg.async_get(entry.device_id) if entry and entry.device_id else None
            targets.append(
                {
                    "entity_id": state.entity_id,
                    "name": state.name,
                    "domain": domain,
                    "area_id": _area_of(entry, dev_reg),
                    # model and maker make "ZBMINI" or "Sonoff" searchable
                    "model": " ".join(
                        str(v) for v in (
                            device.manufacturer if device else None,
                            device.model if device else None,
                            getattr(device, "model_id", None) if device else None,
                        ) if v
                    ) or None,
                }
            )
    areas = [
        {"area_id": area.id, "name": area.name}
        for area in ar.async_get(hass).async_list_areas()
    ]
    connection.send_result(msg["id"], {"targets": targets, "areas": areas})


# ------------------------------------------------------------- subscriptions


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/learn/subscribe"})
@websocket_api.require_admin
@callback
def ws_learn_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Stream raw button events for LEARN_DURATION_S seconds."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    msg_id = msg["id"]

    @callback
    def _forward(info: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg_id, {"candidate": info}))

    unsub = engine.async_subscribe_learn(_forward)

    @callback
    def _timeout() -> None:
        unsub()
        connection.send_message(websocket_api.event_message(msg_id, {"done": True}))

    handle = hass.loop.call_later(LEARN_DURATION_S, _timeout)

    @callback
    def _unsubscribe() -> None:
        handle.cancel()
        unsub()

    connection.subscriptions[msg_id] = _unsubscribe
    connection.send_result(msg_id, {"duration": LEARN_DURATION_S})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/presses/subscribe", vol.Required("source"): str}
)
@websocket_api.require_admin
@callback
def ws_presses_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Stream the button events of one source while its page is open."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    msg_id = msg["id"]

    @callback
    def _forward(info: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg_id, {"press": info}))

    connection.subscriptions[msg_id] = engine.async_observe(msg["source"], _forward)
    connection.send_result(msg_id)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/activity/subscribe"})
@websocket_api.require_admin
@callback
def ws_activity_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Stream triggered links; the reply carries the recent history."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    msg_id = msg["id"]

    @callback
    def _forward(record: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg_id, {"activity": record}))

    connection.subscriptions[msg_id] = engine.async_subscribe_activity(_forward)
    connection.send_result(msg_id, {"recent": list(engine.activity)})


# ------------------------------------------------------------- ZHA -> Z2M, extern


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/migrations/list"})
@websocket_api.require_admin
@callback
def ws_migrations_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """What can move from ZHA to Zigbee2MQTT."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    connection.send_result(msg["id"], {"migrations": engine.migrations()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/migrations/apply",
        vol.Optional("link_ids"): [str],
    }
)
@websocket_api.require_admin
@callback
def ws_migrations_apply(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Move sources and targets to their Zigbee2MQTT counterparts."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    count = engine.async_apply_migrations(msg.get("link_ids"))
    connection.send_result(msg["id"], {"applied": count})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/external/set",
        vol.Required("key"): str,
        vol.Optional("note"): vol.Any(None, vol.All(str, vol.Length(max=80))),
    }
)
@websocket_api.require_admin
@callback
def ws_external_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Mark a source as also used elsewhere (or clear the mark)."""
    if (engine := _engine(hass, connection, msg["id"])) is None:
        return
    engine.async_set_external(msg["key"], (msg.get("note") or "").strip() or None)
    connection.send_result(msg["id"])
