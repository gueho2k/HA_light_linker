"""Tests for v0.4: bindings per slot, templates, multi press, ramps, device library."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

RODRET = "event.rodret_kellerwohnung_action"
RODRET_TYPES = ["on", "off", "brightness_move_up", "brightness_move_down", "brightness_stop"]
HUE = "event.taster_h_erdgeschoss_wohnzimmer_030_action"
HUE_TYPES = ["press", "press_release", "hold", "hold_release"]
MOES = "event.moes_4fach_action"
MOES_TYPES = ["1_single", "1_double", "1_hold", "2_single", "2_double", "2_hold"]
_n = 0


def fire(hass: HomeAssistant, entity: str, event_type: str, types, button: str | None = None) -> None:
    global _n
    _n += 1
    attrs = {"event_types": types, "event_type": event_type}
    if button is not None:
        attrs["button"] = button
    hass.states.async_set(entity, (dt_util.utcnow() + timedelta(milliseconds=_n)).isoformat(), attrs)


async def ws(hass_ws_client, hass, payload):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(payload)
    msg = await client.receive_json()
    return client, msg


async def create(hass_ws_client, hass, link):
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/create", "link": link})
    assert msg["success"], msg
    return msg["result"]["link"]


def src(entity, button=None):
    return {"adapter": "event_entity", "entity_id": entity, "button": button}


@pytest.fixture
def no_debounce(monkeypatch):
    monkeypatch.setattr("custom_components.light_linker.engine.DEBOUNCE_S", 0)


async def test_v03_store_gets_bindings_and_backup(hass, hass_storage, hass_ws_client) -> None:
    """0.3 links are converted to bindings; the old data is kept as backup."""
    from homeassistant.setup import async_setup_component

    old = {
        "links": [{
            "id": "01KW", "name": "KW links", "enabled": True, "profile": "rocker",
            "sources": [{"adapter": "event_entity", "entity_id": RODRET, "button": None, "mode": "button", "role": None}],
            "targets": {"entity_id": ["light.kw"], "area_id": []},
            "options": {"double": {"type": "cycle_color_temp", "kelvin_list": [2700, 6500]}},
        }],
        "ieee_hints": {}, "external": {},
    }
    hass_storage["light_linker.links"] = {"version": 1, "minor_version": 3, "key": "light_linker.links", "data": old}
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "frontend", {})
    entry = MockConfigEntry(domain="light_linker", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/list"})
    link = msg["result"]["links"][0]
    slots = {(b["button"], b["event"]): b["action"] for b in link["bindings"]}
    assert slots[(None, "on")] == "on"
    assert slots[(None, "off")] == "off"
    assert slots[(None, "hold_up")] == "ramp_up"
    assert slots[(None, "double")] == "cycle_color_temp"
    assert hass_storage["light_linker.links.backup_0_3"]["data"] == old


async def test_bindings_with_own_targets(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """RODRET: I toggles the ceiling light, O toggles the floor lamp."""
    hass.states.async_set("light.kellerlicht", "off")
    hass.states.async_set("switch.stehlampe", "off")
    hass.states.async_set(RODRET, "unknown", {"event_types": RODRET_TYPES})
    light_on = async_mock_service(hass, "light", "turn_on")
    plug_on = async_mock_service(hass, "switch", "turn_on")
    await create(hass_ws_client, hass, {
        "name": "RODRET", "profile": "custom",
        "sources": [src(RODRET)],
        "targets": {"entity_id": []},
        "options": {"verify": {"enabled": False}},
        "bindings": [
            {"source": f"event_entity:{RODRET}", "event": "on", "action": "toggle",
             "targets": {"entity_id": ["light.kellerlicht"]}},
            {"source": f"event_entity:{RODRET}", "event": "off", "action": "toggle",
             "targets": {"entity_id": ["switch.stehlampe"]}},
        ],
    })
    fire(hass, RODRET, "on", RODRET_TYPES)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in light_on] == [["light.kellerlicht"]]
    assert not plug_on
    fire(hass, RODRET, "off", RODRET_TYPES)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in plug_on] == [["switch.stehlampe"]]


async def test_specific_button_beats_all_buttons(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """A binding for 'right' wins over the one for every button."""
    for e in ("light.a", "light.b"):
        hass.states.async_set(e, "off")
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    on = async_mock_service(hass, "light", "turn_on")
    await create(hass_ws_client, hass, {
        "name": "Hue", "profile": "custom", "sources": [src(HUE)], "targets": {"entity_id": ["light.a"]},
        "options": {"verify": {"enabled": False}},
        "bindings": [
            {"event": "press", "action": "toggle"},
            {"button": "right", "event": "press", "action": "on", "targets": {"entity_id": ["light.b"]}},
        ],
    })
    fire(hass, HUE, "press_release", HUE_TYPES, "right")
    await hass.async_block_till_done()
    fire(hass, HUE, "press_release", HUE_TYPES, "left")
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in on] == [["light.b"], ["light.a"]]


async def test_synthetic_double_click(hass, setup_ll, hass_ws_client, no_debounce, monkeypatch) -> None:
    """Hue modules report no double click: Light Linker counts presses itself."""
    monkeypatch.setattr("custom_components.light_linker.engine.MULTI_PRESS_S", 0.05)
    hass.states.async_set("light.a", "off")
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    await create(hass_ws_client, hass, {
        "name": "Hue", "profile": "custom", "sources": [src(HUE)], "targets": {"entity_id": ["light.a"]},
        "options": {"verify": {"enabled": False}},
        "bindings": [
            {"button": "left", "event": "press", "action": "on"},
            {"button": "left", "event": "double", "action": "off"},
        ],
    })
    fire(hass, HUE, "press_release", HUE_TYPES, "left")
    await hass.async_block_till_done()
    assert not on  # waiting whether a second press follows
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert len(on) == 1 and not off
    fire(hass, HUE, "press_release", HUE_TYPES, "left")
    fire(hass, HUE, "press_release", HUE_TYPES, "left")
    await hass.async_block_till_done()
    assert len(off) == 1 and len(on) == 1


def _z2m_light(hass, ieee: str, name: str, entity_id: str) -> None:
    mqtt_entry = MockConfigEntry(domain="mqtt", data={})
    mqtt_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", f"zigbee2mqtt_{ieee}")}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "light", "mqtt", f"{ieee}_light_zigbee2mqtt", suggested_object_id=entity_id.split(".")[1],
        device_id=device.id, config_entry=mqtt_entry,
    )


async def test_native_ramp_z2m(hass, setup_ll, hass_ws_client, no_debounce, monkeypatch) -> None:
    """Hold up on a Z2M lamp: one brightness_move, one stop on release."""
    from homeassistant.components import mqtt

    published: list[tuple[str, str]] = []

    async def _publish(_hass, topic, payload, *args, **kwargs):
        published.append((topic, payload))

    monkeypatch.setattr(mqtt, "async_publish", _publish)
    hass.config.components.add("mqtt")
    _z2m_light(hass, "0x0017880100aabbcc", "Kellerlicht", "light.kellerlicht")
    hass.states.async_set("light.kellerlicht", "on", {"brightness": 128})
    hass.states.async_set(RODRET, "unknown", {"event_types": RODRET_TYPES})
    await create(hass_ws_client, hass, {
        "name": "Rampe", "profile": "custom", "sources": [src(RODRET)],
        "targets": {"entity_id": ["light.kellerlicht"]}, "options": {"verify": {"enabled": False}},
        "bindings": [{"event": "hold_up", "action": "ramp_up", "ramp": {"mode": "native", "duration_s": 4}}],
    })
    fire(hass, RODRET, "brightness_move_up", RODRET_TYPES)
    await hass.async_block_till_done()
    assert published == [("zigbee2mqtt/Kellerlicht/set", '{"brightness_move": 64}')]
    fire(hass, RODRET, "brightness_stop", RODRET_TYPES)
    await hass.async_block_till_done()
    assert published[1] == ("zigbee2mqtt/Kellerlicht/set", '{"brightness_move": 0}')


async def test_native_ramp_zha(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """Hold down on a ZHA lamp: Level Control move (down) and stop."""
    zha_entry = MockConfigEntry(domain="zha", data={})
    zha_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "light", "zha", "00:17:88:01:0b:23:45:67-11", suggested_object_id="flurlicht", config_entry=zha_entry
    )
    hass.states.async_set("light.flurlicht", "on", {"brightness": 200})
    commands = async_mock_service(hass, "zha", "issue_zigbee_cluster_command")
    async_mock_service(hass, "homeassistant", "update_entity")
    hass.states.async_set(RODRET, "unknown", {"event_types": RODRET_TYPES})
    await create(hass_ws_client, hass, {
        "name": "Flur", "profile": "custom", "sources": [src(RODRET)],
        "targets": {"entity_id": ["light.flurlicht"]}, "options": {"verify": {"enabled": False}},
        "bindings": [{"event": "hold_down", "action": "ramp_down", "ramp": {"duration_s": 2}}],
    })
    fire(hass, RODRET, "brightness_move_down", RODRET_TYPES)
    await hass.async_block_till_done()
    move = commands[0].data
    assert (move["ieee"], move["endpoint_id"], move["cluster_id"], move["command"]) == (
        "00:17:88:01:0b:23:45:67", 11, 8, 1
    )
    assert move["params"] == {"move_mode": 1, "rate": 127}
    fire(hass, RODRET, "brightness_stop", RODRET_TYPES)
    await hass.async_block_till_done()
    assert commands[1].data["command"] == 3


async def test_ramp_steps_end_after_repeats(hass, setup_ll, hass_ws_client, no_debounce, monkeypatch) -> None:
    """A device that repeats 'hold' and sends no release: the ramp ends after the gap."""
    monkeypatch.setattr("custom_components.light_linker.engine.REPEAT_GAP_S", 0.15)
    types = ["single", "hold"]
    remote = "event.wiederholer_action"
    hass.states.async_set("light.a", "on", {"brightness": 100})
    hass.states.async_set(remote, "unknown", {"event_types": types})
    steps = async_mock_service(hass, "light", "turn_on")
    await create(hass_ws_client, hass, {
        "name": "Steps", "profile": "custom", "sources": [src(remote)],
        "targets": {"entity_id": ["light.a"]}, "options": {"verify": {"enabled": False}},
        "bindings": [{"event": "hold", "action": "ramp_up",
                      "ramp": {"mode": "steps", "end": "repeat", "interval_ms": 100, "duration_s": 5}}],
    })
    fire(hass, remote, "hold", types)
    await asyncio.sleep(0.1)
    fire(hass, remote, "hold", types)  # repeat keeps it alive, does not restart
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    running = len(steps)
    assert running >= 2
    assert all(c.data.get("brightness_step_pct") == 2 for c in steps)
    await asyncio.sleep(0.4)
    stopped = len(steps)
    await asyncio.sleep(0.3)
    assert len(steps) == stopped  # ramp ended


async def test_hold_without_release_steps_once(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """Moes sends only '1_hold': one step instead of an endless ramp."""
    hass.states.async_set("light.a", "on", {"brightness": 128})
    hass.states.async_set(MOES, "unknown", {"event_types": MOES_TYPES})
    on = async_mock_service(hass, "light", "turn_on")
    await create(hass_ws_client, hass, {
        "name": "Moes", "profile": "custom", "sources": [src(MOES)],
        "targets": {"entity_id": ["light.a"]}, "options": {"verify": {"enabled": False}},
        "bindings": [{"button": "1", "event": "hold", "action": "ramp_up", "ramp": {"step_pct": 20}}],
    })
    fire(hass, MOES, "1_hold", MOES_TYPES)
    await hass.async_block_till_done()
    assert [c.data["brightness_pct"] for c in on] == [70]


async def test_sources_carry_layout(hass, setup_ll, hass_ws_client) -> None:
    """Known remotes get their drawing from the library, others a generic one."""
    mqtt_entry = MockConfigEntry(domain="mqtt", data={})
    mqtt_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", "zigbee2mqtt_0x01")},
        name="RODRET Kellerwohnung", model="RODRET wireless dimmer", model_id="E2201",
    )
    er.async_get(hass).async_get_or_create(
        "event", "mqtt", "0x01_action_zigbee2mqtt", suggested_object_id="rodret_kellerwohnung_action",
        device_id=device.id, config_entry=mqtt_entry,
    )
    hass.states.async_set(RODRET, "unknown", {"event_types": RODRET_TYPES})
    hass.states.async_set(MOES, "unknown", {"event_types": MOES_TYPES})
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/sources/list"})
    by_id = {s["entity_id"]: s for s in msg["result"]["sources"]}
    rodret = by_id[RODRET]["layout"]
    assert rodret["library"] == "ikea_rodret"
    assert [b["label"] for b in rodret["buttons"]] == ["I", "O"]
    assert rodret["buttons"][0]["slots"] == [{"button": None, "event": "on"}, {"button": None, "event": "hold_up"}]
    moes = by_id[MOES]["layout"]
    assert moes["library"] is None
    assert [b["id"] for b in moes["buttons"]] == ["1", "2"]
    assert {s["event"] for s in moes["buttons"][0]["slots"]} == {"press", "double", "hold", "triple"}


async def test_binding_test_and_press_stream(hass, setup_ll, hass_ws_client) -> None:
    """bindings/test runs one binding; presses/subscribe streams the pressed key."""
    hass.states.async_set("light.a", "off")
    hass.states.async_set(MOES, "unknown", {"event_types": MOES_TYPES})
    on = async_mock_service(hass, "light", "turn_on")
    link = await create(hass_ws_client, hass, {
        "name": "Moes", "profile": "custom", "sources": [src(MOES)],
        "targets": {"entity_id": ["light.a"]}, "options": {"verify": {"enabled": False}},
        "bindings": [{"button": "2", "event": "press", "action": "on"}],
    })
    client, msg = await ws(hass_ws_client, hass, {
        "type": "light_linker/bindings/test", "link_id": link["id"], "binding_id": link["bindings"][0]["id"],
    })
    assert msg["success"]
    await hass.async_block_till_done()
    assert len(on) == 1

    await client.send_json_auto_id({"type": "light_linker/presses/subscribe", "source": "event_entity:" + "event.unbenutzt"})
    assert (await client.receive_json())["success"]
    hass.states.async_set("event.unbenutzt", "unknown", {"event_types": MOES_TYPES})
    fire(hass, "event.unbenutzt", "1_double", MOES_TYPES)
    await hass.async_block_till_done()
    event = (await client.receive_json())["event"]["press"]
    assert (event["button"], event["event"]) == ("1", "double")


async def test_duplicate_slot_rejected(hass, setup_ll, hass_ws_client) -> None:
    """One slot, one binding."""
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/create", "link": {
        "name": "Doppelt", "profile": "custom", "sources": [src(MOES)], "targets": {"entity_id": ["light.a"]},
        "bindings": [{"button": "1", "event": "press", "action": "on"}, {"button": "1", "event": "press", "action": "off"}],
    }})
    assert not msg["success"]
    assert "doppelt belegt" in msg["error"]["message"]


async def test_panel_style_update_frees_button(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """The panel adds a 'left' binding to a link whose source was limited to 'right'."""
    hass.states.async_set("light.a", "off")
    hass.states.async_set("light.b", "off")
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    on = async_mock_service(hass, "light", "turn_on")
    link = await create(hass_ws_client, hass, {
        "name": "Sofa", "profile": "toggle", "sources": [src(HUE, "right")],
        "targets": {"entity_id": ["light.a"]}, "options": {"verify": {"enabled": False}},
    })
    payload = {k: v for k, v in link.items() if k not in ("status", "id", "created_at", "updated_at")}
    payload["sources"][0]["button"] = None
    payload["profile"] = "custom"
    payload["bindings"].append({"source": f"event_entity:{HUE}", "button": "left", "event": "press", "action": "on",
                                "targets": {"entity_id": ["light.b"], "area_id": []}})
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/update", "link_id": link["id"], "link": payload,
                                             "updated_at": link["updated_at"]})
    assert msg["success"], msg
    fire(hass, HUE, "press_release", HUE_TYPES, "left")
    await hass.async_block_till_done()
    fire(hass, HUE, "press_release", HUE_TYPES, "right")
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in on] == [["light.b"], ["light.a"]]


async def test_new_device_lookup_signature(hass, setup_ll, hass_ws_client, monkeypatch) -> None:
    """HA 2026.8+: async_get_device_by_identifier needs the config entry."""
    calls = []

    def lookup(self, identifier, config_entry_id):
        calls.append((identifier, config_entry_id))
        return None

    monkeypatch.setattr(dr.DeviceRegistry, "async_get_device_by_identifier", lookup, raising=False)
    MockConfigEntry(domain="mqtt", data={}).add_to_hass(hass)
    MockConfigEntry(domain="zha", data={}).add_to_hass(hass)
    await create(hass_ws_client, hass, {
        "name": "Wippe", "profile": "rocker",
        "sources": [{"adapter": "zha", "device_ieee": "94:ec:32:ff:fe:b9:55:f8"}],
        "targets": {"entity_id": ["light.lampe_kw_keller_wohnzimmer_002"]}, "options": {},
    })
    assert calls and all(c[1] for c in calls)


async def test_dedupe_and_remove_source(hass, setup_ll, hass_ws_client) -> None:
    """Identical bindings are kept once; removing a button deletes its links."""
    hass.states.async_set(MOES, "unknown", {"event_types": MOES_TYPES})
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    same = {"profile": "rocker", "sources": [src(MOES)], "targets": {"entity_id": ["light.kw_002"]}, "options": {}}
    first = await create(hass_ws_client, hass, {"name": "KW 002", **same})
    await create(hass_ws_client, hass, {"name": "KW 002", **same})
    await create(hass_ws_client, hass, {"name": "KW 002", **same})
    mixed = await create(hass_ws_client, hass, {
        "name": "Gemischt", "profile": "custom", "sources": [src(MOES), src(HUE)], "targets": {"entity_id": ["light.x"]},
        "bindings": [{"source": f"event_entity:{MOES}", "button": "2", "event": "press", "action": "off"},
                     {"source": f"event_entity:{HUE}", "button": "left", "event": "press", "action": "on"}],
    })
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/list"})
    status = {l["name"]: l["status"] for l in msg["result"]["links"]}
    assert status["KW 002"]["duplicates"]  # marked for the panel

    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/dedupe"})
    assert msg["result"]["deleted"] == ["KW 002", "KW 002"]
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/list"})
    names = sorted(l["name"] for l in msg["result"]["links"])
    assert names == ["Gemischt", "KW 002"]
    assert next(l for l in msg["result"]["links"] if l["name"] == "KW 002")["id"] == first["id"]

    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/sources/remove", "source": f"event_entity:{MOES}"})
    assert msg["result"] == {"changed": ["Gemischt"], "deleted": ["KW 002"]}
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/links/list"})
    left = msg["result"]["links"]
    assert [l["name"] for l in left] == ["Gemischt"]
    assert [b["source"] for b in left[0]["bindings"]] == [f"event_entity:{HUE}"]
    assert left[0]["id"] == mixed["id"]


async def test_light_linker_groups(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """Kellerlicht 1 + 2 nested in 'gesamt'; buttons switch groups, member changes apply at once."""
    for n in ("002", "003", "004", "006", "007", "008"):
        hass.states.async_set(f"light.kw_{n}", "off")
    hass.states.async_set(MOES, "unknown", {"event_types": MOES_TYPES})
    on = async_mock_service(hass, "light", "turn_on")
    client = await hass_ws_client(hass)

    async def save(group):
        await client.send_json_auto_id({"type": "light_linker/groups/save", "group": group})
        msg = await client.receive_json()
        assert msg["success"], msg
        return msg["result"]["group"]

    k1 = await save({"name": "Kellerlicht 1", "members": ["light.kw_002", "light.kw_003", "light.kw_004"]})
    k2 = await save({"name": "Kellerlicht 2", "members": ["light.kw_006", "light.kw_007", "light.kw_008"]})
    alle = await save({"name": "Kellerlicht gesamt", "members": [f"group:{k1['id']}", f"group:{k2['id']}"]})

    await client.send_json_auto_id({"type": "light_linker/groups/save", "group": {**k1, "members": [f"group:{alle['id']}"]}})
    assert not (await client.receive_json())["success"]  # no cycles

    await create(hass_ws_client, hass, {
        "name": "Keller", "profile": "custom", "sources": [src(MOES)], "targets": {"entity_id": []},
        "options": {"verify": {"enabled": False}},
        "bindings": [
            {"button": "1", "event": "press", "action": "on", "targets": {"group_id": [k1["id"]]}},
            {"button": "2", "event": "press", "action": "on", "targets": {"group_id": [alle["id"]]}},
        ],
    })
    fire(hass, MOES, "1_single", MOES_TYPES)
    await hass.async_block_till_done()
    assert sorted(on[-1].data["entity_id"]) == ["light.kw_002", "light.kw_003", "light.kw_004"]
    fire(hass, MOES, "2_single", MOES_TYPES)
    await hass.async_block_till_done()
    assert len(on[-1].data["entity_id"]) == 6

    await save({**k1, "members": ["light.kw_002"]})
    fire(hass, MOES, "1_single", MOES_TYPES)
    await hass.async_block_till_done()
    assert on[-1].data["entity_id"] == ["light.kw_002"]

    await client.send_json_auto_id({"type": "light_linker/groups/list"})
    groups = {g["name"]: g for g in (await client.receive_json())["result"]["groups"]}
    assert groups["Kellerlicht 1"]["used_by"] == ["Keller"]
    assert groups["Kellerlicht 1"]["parents"] == ["Kellerlicht gesamt"]
    assert len(groups["Kellerlicht gesamt"]["entities"]) == 4

    await client.send_json_auto_id({"type": "light_linker/groups/delete", "group_id": k2["id"]})
    assert (await client.receive_json())["result"]["used"] == 1
    await client.send_json_auto_id({"type": "light_linker/groups/list"})
    groups = {g["name"]: g for g in (await client.receive_json())["result"]["groups"]}
    assert groups["Kellerlicht gesamt"]["members"] == [f"group:{k1['id']}"]


async def test_new_group_is_adopted_and_alias(hass, setup_ll, hass_ws_client) -> None:
    """Creating Sofa1+Sofa3 as group replaces them in existing links; buttons get readable names."""
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    link = await create(hass_ws_client, hass, {
        "name": "Fensterecke", "profile": "toggle", "sources": [src(HUE, "left")],
        "targets": {"entity_id": ["light.sofa1", "light.sofa3", "light.sofa4"]}, "options": {},
    })
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/groups/save", "group": {"name": "Sofaecke", "members": ["light.sofa1", "light.sofa3"]}})
    msg = await client.receive_json()
    assert msg["result"]["group"]["adopted"] == ["Fensterecke"]
    gid = msg["result"]["group"]["id"]
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    targets = (await client.receive_json())["result"]["links"][0]["targets"]
    assert targets == {"entity_id": ["light.sofa4"], "area_id": [], "group_id": [gid]}

    # a group alone is a valid target
    payload = {k: v for k, v in link.items() if k not in ("status", "id", "created_at", "updated_at")}
    payload["profile"] = "custom"
    payload["bindings"] = [{"button": "left", "event": "press", "action": "toggle", "targets": {"group_id": [gid]}}]
    payload["targets"] = {"group_id": [gid]}
    await client.send_json_auto_id({"type": "light_linker/links/update", "link_id": link["id"], "link": payload})
    assert (await client.receive_json())["success"]

    await client.send_json_auto_id({"type": "light_linker/sources/alias", "source": f"event_entity:{HUE}", "name": "Wandschalter Fensterecke"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "light_linker/sources/list"})
    srcs = {s["entity_id"]: s for s in (await client.receive_json())["result"]["sources"]}
    assert srcs[HUE]["alias"] == "Wandschalter Fensterecke"


async def test_adopted_link_named_after_lamps_takes_group_name(hass, setup_ll, hass_ws_client) -> None:
    """A link that was only named after its lamps gets the group name."""
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    hass.states.async_set("light.sofa1", "off", {"friendly_name": "Sofa1"})
    hass.states.async_set("light.sofa3", "off", {"friendly_name": "Sofa3"})
    await create(hass_ws_client, hass, {
        "name": "Sofa1, Sofa3", "profile": "toggle", "sources": [src(HUE, "left")],
        "targets": {"entity_id": ["light.sofa1", "light.sofa3"]}, "options": {},
    })
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/groups/save", "group": {"name": "Sofaecke", "members": ["light.sofa3", "light.sofa1"]}})
    assert (await client.receive_json())["result"]["group"]["adopted"] == ["Sofaecke"]
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    assert (await client.receive_json())["result"]["links"][0]["name"] == "Sofaecke"


async def test_targets_list_has_model_and_hides_own_switches(hass, setup_ll, hass_ws_client) -> None:
    """ZBMINI relays are findable by model; Light Linker's own switches are no targets."""
    zha_entry = MockConfigEntry(domain="zha", data={})
    zha_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id, identifiers={("zha", "00:12:4b:00:25:aa:bb:cc")},
        manufacturer="SONOFF", model="01MINIZB",
    )
    er.async_get(hass).async_get_or_create(
        "light", "zha", "00:12:4b:00:25:aa:bb:cc-1", suggested_object_id="h_eg_k_licht",
        device_id=device.id, config_entry=zha_entry,
    )
    hass.states.async_set("light.h_eg_k_licht", "off", {"friendly_name": "H.EG.K.Licht", "supported_color_modes": ["onoff"]})
    er.async_get(hass).async_get_or_create("switch", "light_linker", "xyz", suggested_object_id="light_linker_test")
    hass.states.async_set("switch.light_linker_test", "on")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/targets/list"})
    targets = {t["entity_id"]: t for t in (await client.receive_json())["result"]["targets"]}
    assert "01MINIZB" in targets["light.h_eg_k_licht"]["model"]
    assert "SONOFF" in targets["light.h_eg_k_licht"]["model"]
    assert "switch.light_linker_test" not in targets


async def test_moes_scene_remotes_show_all_keys(hass, setup_ll, hass_ws_client) -> None:
    """Z2M names Moes remotes 'Scene remote with 3 keys' / ZT-B-EU3: all keys are drawn
    before any was pressed; unknown remotes take the key count from the model text."""
    mqtt_entry = MockConfigEntry(domain="mqtt", data={})
    mqtt_entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    ents = er.async_get(hass)
    for ident, oid, model, model_id in (
        ("0x27", "taster_027_action", "Scene remote with 3 keys", "ZT-B-EU3"),
        ("0x19", "taster_019_action", "Scene remote with 2 keys", "ZT-B-EU2"),
        ("0x99", "taster_099_action", "Fancy 3-gang remote", "XYZ"),
    ):
        device = reg.async_get_or_create(
            config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", f"zigbee2mqtt_{ident}")},
            manufacturer="Moes", model=model, model_id=model_id,
        )
        ents.async_get_or_create("event", "mqtt", f"{ident}_action", suggested_object_id=oid, device_id=device.id, config_entry=mqtt_entry)
        hass.states.async_set(f"event.{oid}", "unknown", {"event_types": ["single", "double", "hold"], "button": "1"})
    _, msg = await ws(hass_ws_client, hass, {"type": "light_linker/sources/list"})
    by_id = {s["entity_id"]: s["layout"] for s in msg["result"]["sources"]}
    assert by_id["event.taster_027_action"]["library"] == "tuya_ts0043"
    assert [b["id"] for b in by_id["event.taster_027_action"]["buttons"]] == ["1", "2", "3"]
    assert [b["id"] for b in by_id["event.taster_019_action"]["buttons"]] == ["1", "2"]
    generic = by_id["event.taster_099_action"]
    assert generic["library"] is None
    assert [b["id"] for b in generic["buttons"]] == ["1", "2", "3"]


async def test_moes_key_two_by_attribute(hass, setup_ll, hass_ws_client) -> None:
    """event_type 'single' + attribute button '2' triggers the binding of key 2 only."""
    ent = "event.taster_027_action"
    hass.states.async_set(ent, "unknown", {"event_types": ["single", "double", "hold"]})
    hass.states.async_set("light.a", "off")
    hass.states.async_set("light.b", "off")
    toggle = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    await create(hass_ws_client, hass, {
        "name": "Flur", "profile": "custom", "sources": [src(ent)],
        "targets": {"entity_id": ["light.a"]}, "options": {},
        "bindings": [
            {"button": "1", "event": "press", "action": "toggle", "targets": {"entity_id": ["light.a"]}},
            {"button": "2", "event": "press", "action": "toggle", "targets": {"entity_id": ["light.b"]}},
        ],
    })
    hass.states.async_set(ent, dt_util.utcnow().isoformat(), {"event_types": ["single", "double", "hold"], "event_type": "single", "button": "2"})
    await hass.async_block_till_done()
    await asyncio.sleep(0.6)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in toggle] == [["light.b"]]


async def test_template_on_one_key_of_moes(hass, setup_ll, hass_ws_client) -> None:
    """Gate template on key 1 and key 2 of a 3-key remote: each key opens only its gate."""
    ent = "event.taster_027_action"
    types = ["single", "double", "hold"]
    hass.states.async_set(ent, "unknown", {"event_types": types})
    hass.states.async_set("cover.tor1", "closed")
    hass.states.async_set("cover.tor2", "closed")
    calls = async_mock_service(hass, "cover", "toggle")
    for button, cover in (("1", "cover.tor1"), ("2", "cover.tor2")):
        await create(hass_ws_client, hass, {
            "name": cover, "profile": "gate", "sources": [src(ent, button)],
            "targets": {"entity_id": [cover]}, "options": {},
        })
    for button in ("2", "3", "1"):
        hass.states.async_set(ent, dt_util.utcnow().isoformat(), {"event_types": types, "event_type": "single", "button": button})
        await hass.async_block_till_done()
        await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in calls] in ([["cover.tor2"], ["cover.tor1"]], ["cover.tor2", "cover.tor1"])


async def test_key_override_beats_all_keys_binding(hass, setup_ll, hass_ws_client) -> None:
    """An 'all keys' binding plus a key-2 override: key 2 does only its own thing, 'none' silences it."""
    ent = "event.taster_027_action"
    types = ["single", "double", "hold"]
    hass.states.async_set(ent, "unknown", {"event_types": types})
    for e in ("light.a", "light.b"):
        hass.states.async_set(e, "off")
    on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    link = await create(hass_ws_client, hass, {
        "name": "Flur", "profile": "custom", "sources": [src(ent)],
        "targets": {"entity_id": ["light.a"]}, "options": {},
        "bindings": [
            {"button": None, "event": "press", "action": "toggle"},
            {"button": "2", "event": "press", "action": "toggle", "targets": {"entity_id": ["light.b"]}},
            {"button": "3", "event": "press", "action": "none"},
        ],
    })
    assert link

    async def press(button):
        hass.states.async_set(ent, dt_util.utcnow().isoformat(), {"event_types": types, "event_type": "single", "button": button})
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        await hass.async_block_till_done()

    await press("2")
    await press("3")
    await press("1")
    assert [c.data["entity_id"] for c in on] == [["light.b"], ["light.a"]]


async def test_free_binding_can_drive_gate_and_cover(hass, setup_ll, hass_ws_client) -> None:
    """Without the gate template: cover_toggle pulses a gate relay (switch); toggle moves a cover."""
    ent = "event.taster_027_action"
    types = ["single", "double", "hold"]
    hass.states.async_set(ent, "unknown", {"event_types": types})
    hass.states.async_set("switch.torschalter1", "off")
    hass.states.async_set("cover.rollladen", "open")
    sw = async_mock_service(hass, "switch", "toggle")
    cv = async_mock_service(hass, "cover", "toggle")
    await create(hass_ws_client, hass, {
        "name": "Frei", "profile": "custom", "sources": [src(ent)],
        "targets": {"entity_id": ["switch.torschalter1"]}, "options": {},
        "bindings": [
            {"button": "1", "event": "press", "action": "cover_toggle"},
            {"button": "2", "event": "press", "action": "toggle", "targets": {"entity_id": ["cover.rollladen"]}},
        ],
    })
    for button in ("1", "2"):
        hass.states.async_set(ent, dt_util.utcnow().isoformat(), {"event_types": types, "event_type": "single", "button": button})
        await hass.async_block_till_done()
        await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in sw] in (["switch.torschalter1"], [["switch.torschalter1"]])
    assert [c.data["entity_id"] for c in cv] in (["cover.rollladen"], [["cover.rollladen"]])
