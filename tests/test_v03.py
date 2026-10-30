"""Tests for v0.3: motion profile, Z2M groups, ZHA -> Z2M move, external sources."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

PIR = "binary_sensor.h_eg_k_bewegungsmelder"
LUX = "sensor.h_eg_k_bewegungsmelder_beleuchtungsstarke"
LAMP = "light.h_eg_k_licht"


def fake_lights(hass: HomeAssistant) -> list[ServiceCall]:
    """light/switch services that update the state with the caller's context."""
    calls: list[ServiceCall] = []

    async def _handle(call: ServiceCall) -> None:
        calls.append(call)
        on = call.service == "turn_on"
        for entity_id in call.data["entity_id"]:
            hass.states.async_set(entity_id, "on" if on else "off", context=call.context)

    for domain in ("light", "switch"):
        hass.services.async_register(domain, "turn_on", _handle)
        hass.services.async_register(domain, "turn_off", _handle)
    return calls


def by_hand(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state, context=Context())


async def create(hass_ws_client, hass, link):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/links/create", "link": link})
    msg = await client.receive_json()
    return client, msg


def kitchen(**motion):
    return {
        "name": "Küche",
        "profile": "motion",
        "sources": [{"adapter": "occupancy", "entity_id": PIR}],
        "targets": {"entity_id": [LAMP]},
        "options": {
            "verify": {"enabled": False},
            "motion": {"lux_entity": LUX, "lux_threshold": 36, "off_delay_s": 30, **motion},
        },
    }


@pytest.fixture
async def room(hass: HomeAssistant, setup_ll):
    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    hass.states.async_set(LUX, "12", {"device_class": "illuminance"})
    hass.states.async_set(LAMP, "off")
    await hass.async_block_till_done()
    return fake_lights(hass)


def later(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))


async def status(hass_ws_client, hass) -> dict:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    return (await client.receive_json())["result"]["links"][0]["status"]["motion"]


async def test_motion_on_runout_off(hass, room, hass_ws_client) -> None:
    """Dark + motion -> on; all clear -> run-on; motion again cancels; then off."""
    calls = room
    _, msg = await create(hass_ws_client, hass, kitchen())
    assert msg["success"], msg
    await hass.async_block_till_done()

    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert [c.service for c in calls] == ["turn_on"]
    assert hass.states.get(LAMP).state == "on"
    assert (await status(hass_ws_client, hass))["state"] == "auto"
    assert hass.states.get("sensor.light_linker_kuche_status").state == "auto"

    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert (await status(hass_ws_client, hass))["state"] == "runout"
    later(hass, 20)
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})  # back in time
    await hass.async_block_till_done()
    later(hass, 40)
    await hass.async_block_till_done()
    assert hass.states.get(LAMP).state == "on"

    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    later(hass, 31)
    await hass.async_block_till_done()
    assert [c.service for c in calls] == ["turn_on", "turn_off"]
    assert (await status(hass_ws_client, hass))["state"] == "off"


async def test_bright_room_stays_dark(hass, room, hass_ws_client) -> None:
    """Above the threshold motion does nothing."""
    hass.states.async_set(LUX, "120", {"device_class": "illuminance"})
    await create(hass_ws_client, hass, kitchen())
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert not room


async def test_hand_off_blocks_until_empty(hass, room, hass_ws_client) -> None:
    """Switched off by hand while occupied: motion does not switch on again until empty."""
    calls = room
    await create(hass_ws_client, hass, kitchen())
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert hass.states.get(LAMP).state == "on"

    by_hand(hass, LAMP, "off")  # wall switch on the Sonoff
    await hass.async_block_till_done()
    assert (await status(hass_ws_client, hass))["state"] == "blocked"

    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})  # within the run-on
    await hass.async_block_till_done()
    assert len(calls) == 1 and hass.states.get(LAMP).state == "off"

    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    later(hass, 31)
    await hass.async_block_till_done()
    assert (await status(hass_ws_client, hass))["state"] == "off"
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert hass.states.get(LAMP).state == "on"


async def test_hand_on_goes_off_after_manual_delay(hass, room, hass_ws_client) -> None:
    """Switched on by hand in an empty room: off after 10 min, not after 30 s."""
    calls = room
    await create(hass_ws_client, hass, kitchen())
    by_hand(hass, LAMP, "on")
    await hass.async_block_till_done()
    assert (await status(hass_ws_client, hass))["state"] == "manual"
    later(hass, 60)
    await hass.async_block_till_done()
    assert hass.states.get(LAMP).state == "on"
    later(hass, 601)
    await hass.async_block_till_done()
    assert hass.states.get(LAMP).state == "off"
    assert [c.service for c in calls] == ["turn_off"]


async def test_block_entity_pauses(hass, room, hass_ws_client) -> None:
    """While the block entity is on, motion does nothing."""
    hass.states.async_set("input_boolean.film", "on")
    await create(hass_ws_client, hass, kitchen(block_entity="input_boolean.film"))
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert not room


async def test_motion_validation(hass, room, hass_ws_client) -> None:
    """Motion links need a sensor; two motion links may not share a lamp."""
    bad = kitchen()
    bad["sources"] = [{"adapter": "event_entity", "entity_id": "event.x"}]
    _, msg = await create(hass_ws_client, hass, bad)
    assert not msg["success"] and "Melder" in msg["error"]["message"]

    _, msg = await create(hass_ws_client, hass, kitchen())
    assert msg["success"]
    second = kitchen()
    second["name"] = "Küche 2"
    _, msg = await create(hass_ws_client, hass, second)
    assert not msg["success"] and "Küche" in msg["error"]["message"]


async def test_z2m_group_used_for_toggle(hass, setup_ll, hass_ws_client) -> None:
    """Lights that are exactly a Z2M group are switched through the group."""
    ent_reg = er.async_get(hass)
    mqtt_entry = MockConfigEntry(domain="mqtt", data={})
    mqtt_entry.add_to_hass(hass)
    members = []
    for ieee in ("0x0000000000000001", "0x0000000000000002"):
        members.append(
            ent_reg.async_get_or_create("light", "mqtt", f"{ieee}_light_zigbee2mqtt", config_entry=mqtt_entry).entity_id
        )
    group = ent_reg.async_get_or_create("light", "mqtt", "7_light_zigbee2mqtt", config_entry=mqtt_entry, suggested_object_id="esstisch_gruppe").entity_id
    engine = setup_ll.runtime_data
    engine.z2m.async_set_groups(
        [{"id": 7, "friendly_name": "Esstisch", "members": [{"ieee_address": "0x0000000000000001", "endpoint": 1}, {"ieee_address": "0x0000000000000002", "endpoint": 1}]}]
    )
    for entity_id in members:
        hass.states.async_set(entity_id, "off")
    calls = fake_lights(hass)
    hue = "event.taster_031"
    hass.states.async_set(hue, "unknown", {"event_types": ["press_release"]})
    client, msg = await create(
        hass_ws_client, hass,
        {"name": "Esstisch", "profile": "toggle", "sources": [{"adapter": "event_entity", "entity_id": hue}],
         "targets": {"entity_id": members}, "options": {"verify": {"enabled": False}}},
    )
    assert msg["result"]["link"]["status"]["z2m_group"] == "Esstisch"
    hass.states.async_set(hue, dt_util.utcnow().isoformat(), {"event_types": ["press_release"], "event_type": "press_release"})
    await hass.async_block_till_done()
    assert calls[0].data["entity_id"] == [group]


async def test_zha_to_z2m_move(hass, setup_ll, hass_ws_client) -> None:
    """A ZHA lamp and a ZHA remote move to their Z2M twins after re-pairing."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    zha = MockConfigEntry(domain="zha", data={})
    zha.add_to_hass(hass)
    mqtt_entry = MockConfigEntry(domain="mqtt", data={})
    mqtt_entry.add_to_hass(hass)
    lamp_dev = dev_reg.async_get_or_create(config_entry_id=zha.entry_id, identifiers={("zha", "a4:c1:38:00:ab:39:3b:10")})
    old_lamp = ent_reg.async_get_or_create("light", "zha", "sofa1", device_id=lamp_dev.id, config_entry=zha, suggested_object_id="sofa1").entity_id
    hass.states.async_set(old_lamp, "off")
    remote_ieee = "94:ec:32:ff:fe:b9:55:f8"

    client, msg = await create(
        hass_ws_client, hass,
        {"name": "Tor", "profile": "toggle",
         "sources": [{"adapter": "zha", "device_ieee": remote_ieee, "button": "1"}],
         "targets": {"entity_id": [old_lamp]}},
    )
    assert msg["success"], msg
    link_id = msg["result"]["link"]["id"]

    # re-paired in Zigbee2MQTT; the ZHA entity is gone
    ent_reg.async_remove(old_lamp)
    z_lamp = dev_reg.async_get_or_create(config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", "zigbee2mqtt_0xa4c13800ab393b10")})
    new_lamp = ent_reg.async_get_or_create("light", "mqtt", "0xa4c13800ab393b10_light_zigbee2mqtt", device_id=z_lamp.id, config_entry=mqtt_entry, suggested_object_id="sofa1_z2m").entity_id
    z_remote = dev_reg.async_get_or_create(config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", "zigbee2mqtt_0x94ec32fffeb955f8")})
    new_event = ent_reg.async_get_or_create("event", "mqtt", "0x94ec32fffeb955f8_action_zigbee2mqtt", device_id=z_remote.id, config_entry=mqtt_entry, suggested_object_id="tor_action").entity_id
    await hass.async_block_till_done()

    await client.send_json_auto_id({"type": "light_linker/migrations/list"})
    moves = (await client.receive_json())["result"]["migrations"][link_id]
    assert {(m["kind"], m["new"]) for m in moves} == {("source", new_event), ("target", new_lamp)}

    await client.send_json_auto_id({"type": "light_linker/migrations/apply"})
    assert (await client.receive_json())["result"]["applied"] == 2
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    link = (await client.receive_json())["result"]["links"][0]
    assert link["targets"]["entity_id"] == [new_lamp]
    assert link["sources"][0] == {**link["sources"][0], "adapter": "event_entity", "entity_id": new_event, "button": "1"}


async def test_external_mark(hass, setup_ll, hass_ws_client) -> None:
    """External notes show up in the source list and the link status."""
    rodret = "event.taster_h_obergeschoss_timoszimmer_026_action"
    hass.states.async_set(rodret, "unknown", {"event_types": ["on", "off"]})
    client, msg = await create(
        hass_ws_client, hass,
        {"name": "Timo", "profile": "rocker", "sources": [{"adapter": "event_entity", "entity_id": rodret}],
         "targets": {"entity_id": ["light.x"]}},
    )
    await client.send_json_auto_id({"type": "light_linker/external/set", "key": f"event_entity:{rodret}", "note": "Node-RED Terrarium"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "light_linker/sources/list"})
    sources = (await client.receive_json())["result"]["sources"]
    assert next(s for s in sources if s.get("entity_id") == rodret)["external"] == "Node-RED Terrarium"
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    assert (await client.receive_json())["result"]["links"][0]["status"]["external"] == ["Node-RED Terrarium"]
