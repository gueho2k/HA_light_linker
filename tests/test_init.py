"""End-to-end tests: setup, WebSocket API, profiles, fallback switch."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import async_mock_service

EVENT_ENTITY = "event.taster_h_erdgeschoss_wohnzimmer_030_action"
HUE_TYPES = ["press", "press_release", "hold", "hold_release", "toggle"]


def _press(hass: HomeAssistant, event_type: str, button: str | None, types=HUE_TYPES, entity=EVENT_ENTITY):
    attrs = {"event_types": types, "event_type": event_type, "friendly_name": "Taster 030 Action"}
    if button is not None:
        attrs["button"] = button
    # A tiny offset keeps successive states distinct.
    _press.counter = getattr(_press, "counter", 0) + 1
    ts = (dt_util.utcnow() + timedelta(milliseconds=_press.counter)).isoformat()
    hass.states.async_set(entity, ts, attrs)


async def _ws_create(hass_ws_client, hass, link):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/links/create", "link": link})
    msg = await client.receive_json()
    assert msg["success"], msg
    return client, msg["result"]["link"]


FENSTERECKE = {
    "name": "Fensterecke",
    "profile": "toggle",
    "sources": [{"adapter": "event_entity", "entity_id": EVENT_ENTITY, "button": "left"}],
    "targets": {"entity_id": ["light.sofa1", "light.sofa3"]},
    "options": {"verify": {"enabled": False}},
}


async def test_setup_and_unload(hass: HomeAssistant, setup_ll) -> None:
    """Entry loads, panel registers, unload works."""
    assert setup_ll.state is ConfigEntryState.LOADED
    assert "light-linker" in hass.data["frontend_panels"]
    assert await hass.config_entries.async_unload(setup_ll.entry_id)
    await hass.async_block_till_done()
    assert setup_ll.state is ConfigEntryState.NOT_LOADED
    assert "light-linker" not in hass.data["frontend_panels"]


async def test_toggle_profile_any_on(hass: HomeAssistant, setup_ll, hass_ws_client) -> None:
    """Left button toggles both lights as a group; right button is ignored."""
    hass.states.async_set("light.sofa1", "on")
    hass.states.async_set("light.sofa3", "off")
    hass.states.async_set(EVENT_ENTITY, "unknown", {"event_types": HUE_TYPES})
    turn_off = async_mock_service(hass, "light", "turn_off")
    turn_on = async_mock_service(hass, "light", "turn_on")
    await _ws_create(hass_ws_client, hass, FENSTERECKE)

    _press(hass, "press", "left")  # Hue "press" alone must not click
    await hass.async_block_till_done()
    assert not turn_off and not turn_on

    _press(hass, "press_release", "right")
    await hass.async_block_till_done()
    assert not turn_off and not turn_on

    _press(hass, "press_release", "left")
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    assert sorted(turn_off[0].data["entity_id"]) == ["light.sofa1", "light.sofa3"]
    assert not turn_on


async def test_switch_entity_and_fallback(hass: HomeAssistant, setup_ll, hass_ws_client) -> None:
    """The 'aktiv' switch exists, disables the link and is unavailable after unload."""
    hass.states.async_set("light.sofa1", "off")
    hass.states.async_set("light.sofa3", "off")
    hass.states.async_set(EVENT_ENTITY, "unknown", {"event_types": HUE_TYPES})
    turn_on = async_mock_service(hass, "light", "turn_on")
    await _ws_create(hass_ws_client, hass, FENSTERECKE)
    await hass.async_block_till_done()

    assert hass.states.get("switch.light_linker_fensterecke").state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.light_linker_fensterecke"}, blocking=True
    )
    assert hass.states.get("switch.light_linker_fensterecke").state == "off"

    _press(hass, "press_release", "left")
    await hass.async_block_till_done()
    assert not turn_on  # disabled: automation fallback takes over

    await hass.config_entries.async_unload(setup_ll.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.light_linker_fensterecke").state == "unavailable"


async def test_rocker_and_cycle(hass: HomeAssistant, setup_ll, hass_ws_client, monkeypatch) -> None:
    """RODRET on/off and Aqara double click cycles colour temperature."""
    # Real presses are further apart than the 150 ms debounce window.
    monkeypatch.setattr("custom_components.light_linker.engine.DEBOUNCE_S", 0)
    rodret = "event.taster_kw_keller_wohnzimmer_009_action"
    aqara = "event.taster_kw_keller_wohnzimmer_005_action"
    rodret_types = ["on", "off", "brightness_move_up", "brightness_move_down", "brightness_stop"]
    aqara_types = ["single_left", "double_left", "hold_left"]
    for e in ("light.kw2", "light.kw3"):
        hass.states.async_set(e, "off")
    hass.states.async_set(rodret, "unknown", {"event_types": rodret_types})
    hass.states.async_set(aqara, "unknown", {"event_types": aqara_types})
    turn_on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")

    client, _ = await _ws_create(
        hass_ws_client,
        hass,
        {
            "name": "KW Wippe",
            "profile": "rocker",
            "sources": [{"adapter": "event_entity", "entity_id": rodret}],
            "targets": {"entity_id": ["light.kw2", "light.kw3"]},
            "options": {"on_brightness_pct": 100, "verify": {"enabled": False}},
        },
    )
    await client.send_json_auto_id(
        {
            "type": "light_linker/links/create",
            "link": {
                "name": "KW links",
                "profile": "toggle",
                "sources": [{"adapter": "event_entity", "entity_id": aqara, "button": "left"}],
                "targets": {"entity_id": ["light.kw2"]},
                "options": {
                    "double": {"type": "cycle_color_temp", "kelvin_list": [2700, 4000, 6500]},
                    "verify": {"enabled": False},
                },
            },
        }
    )
    assert (await client.receive_json())["success"]

    _press(hass, "on", None, rodret_types, rodret)
    await hass.async_block_till_done()
    assert turn_on[-1].data["brightness_pct"] == 100

    _press(hass, "double_left", None, aqara_types, aqara)
    await hass.async_block_till_done()
    assert turn_on[-1].data["color_temp_kelvin"] == 2700
    _press(hass, "double_left", None, aqara_types, aqara)
    await hass.async_block_till_done()
    assert turn_on[-1].data["color_temp_kelvin"] == 4000


async def test_gate_needs_confirmation(hass: HomeAssistant, setup_ll, hass_ws_client) -> None:
    """Gate test without confirmation is refused, with it the cover toggles once."""
    hass.states.async_set("cover.linkes_garagentor", "closed")
    toggle = async_mock_service(hass, "cover", "toggle")
    client, link = await _ws_create(
        hass_ws_client,
        hass,
        {
            "name": "Tor links",
            "profile": "gate",
            "sources": [
                {
                    "adapter": "event_entity",
                    "entity_id": "event.taster_h_erdgeschoss_flur_027_action",
                    "button": "1",
                }
            ],
            "targets": {"entity_id": ["cover.linkes_garagentor"]},
            "options": {"verify": {"enabled": False}},
        },
    )
    await client.send_json_auto_id({"type": "light_linker/links/test", "link_id": link["id"]})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "confirm_required"

    await client.send_json_auto_id(
        {"type": "light_linker/links/test", "link_id": link["id"], "confirm": True}
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert len(toggle) == 1


async def test_state_input_switch_mode(hass: HomeAssistant, setup_ll, hass_ws_client) -> None:
    """A latching input toggles on every edge."""
    hass.states.async_set("binary_sensor.eingang", "off")
    hass.states.async_set("switch.steckdose", "off")
    turn_on = async_mock_service(hass, "switch", "turn_on")
    await _ws_create(
        hass_ws_client,
        hass,
        {
            "name": "Steckdose",
            "profile": "switch",
            "sources": [
                {"adapter": "state_input", "entity_id": "binary_sensor.eingang", "mode": "switch"}
            ],
            "targets": {"entity_id": ["switch.steckdose"]},
            "options": {"verify": {"enabled": False}},
        },
    )
    hass.states.async_set("binary_sensor.eingang", "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_rename_follows_registry(hass: HomeAssistant, setup_ll, hass_ws_client) -> None:
    """Renaming a source entity updates the link."""
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("event", "mqtt", "abc", suggested_object_id="old_button")
    client, link = await _ws_create(
        hass_ws_client,
        hass,
        {
            "name": "Rename",
            "profile": "toggle",
            "sources": [{"adapter": "event_entity", "entity_id": entry.entity_id}],
            "targets": {"entity_id": ["light.x"]},
        },
    )
    ent_reg.async_update_entity(entry.entity_id, new_entity_id="event.new_button")
    await hass.async_block_till_done()
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    links = (await client.receive_json())["result"]["links"]
    assert links[0]["sources"][0]["entity_id"] == "event.new_button"


async def test_invalid_link_rejected(hass: HomeAssistant, setup_ll, hass_ws_client) -> None:
    """Missing sources are rejected."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "light_linker/links/create",
            "link": {"name": "x", "profile": "toggle", "sources": [], "targets": {}},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "invalid_format"


@pytest.mark.parametrize(
    ("raw", "button_attr", "types", "expected"),
    [
        ("single_right", None, [], ("right", "press", None)),
        ("hold_both", None, [], ("both", "hold_start", None)),
        ("press", "left", HUE_TYPES, ("left", None, None)),
        ("press_release", "left", HUE_TYPES, ("left", "press", None)),
        ("brightness_move_down", None, [], (None, "hold_start", "down")),
        ("2_single", None, [], ("2", "press", None)),
        ("press_long_release", None, [], (None, "hold_end", None)),
    ],
)
def test_normalize(raw, button_attr, types, expected) -> None:
    """Raw event types map to normalized kinds."""
    from custom_components.light_linker.adapters.device_maps import normalize

    button, kind, direction = normalize(raw, button_attr, types)
    assert (button, kind and str(kind), direction) == expected
