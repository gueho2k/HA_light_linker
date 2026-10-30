"""Tests for v0.2: fast presses, failures, event filter, dashboard button, ZHA, repairs."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

HUE = "event.taster_h_erdgeschoss_wohnzimmer_030_action"
HUE_TYPES = ["press", "press_release", "hold", "hold_release", "toggle"]
_n = 0


def press(hass: HomeAssistant, event_type: str = "press_release", button: str | None = "left",
          entity: str = HUE, types=HUE_TYPES) -> None:
    global _n
    _n += 1
    attrs = {"event_types": types, "event_type": event_type}
    if button is not None:
        attrs["button"] = button
    hass.states.async_set(entity, (dt_util.utcnow() + timedelta(milliseconds=_n)).isoformat(), attrs)


async def create(hass_ws_client, hass, link):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/links/create", "link": link})
    msg = await client.receive_json()
    assert msg["success"], msg
    return client, msg["result"]["link"]


def link(name="Sofa", targets=("light.sofa2",), **extra):
    base = {
        "name": name,
        "profile": "toggle",
        "sources": [{"adapter": "event_entity", "entity_id": HUE, "button": "left"}],
        "targets": {"entity_id": list(targets)},
        "options": {"verify": {"enabled": False}},
    }
    base.update(extra)
    return base


@pytest.fixture
def no_debounce(monkeypatch):
    monkeypatch.setattr("custom_components.light_linker.engine.DEBOUNCE_S", 0)


async def test_fast_presses_toggle_back(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """Second press before the lamp reports must switch back, not repeat."""
    hass.states.async_set("light.sofa2", "off")
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    calls: list[str] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call.service)  # lamp is slow: state is NOT updated

    hass.services.async_register("light", "turn_on", _record)
    hass.services.async_register("light", "turn_off", _record)
    await create(hass_ws_client, hass, link())

    for _ in range(3):
        press(hass)
        await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off", "turn_on"]


async def test_failure_notifies_with_reason(hass, setup_ll, hass_ws_client) -> None:
    """A device that does not respond is retried once and reported with the reason."""
    hass.states.async_set("light.sofa2", "on")
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    attempts = []

    async def _fail(call: ServiceCall) -> None:
        attempts.append(call)
        raise HomeAssistantError("Failed to send request: device did not respond")

    hass.services.async_register("light", "turn_off", _fail)
    _, created = await create(
        hass_ws_client, hass,
        link(options={"verify": {"enabled": True, "timeout_s": 0.5, "retries": 1}}),
    )
    press(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(attempts) == 2
    notes = hass.states.async_all("persistent_notification") or []
    from homeassistant.components import persistent_notification as pn
    messages = [n["message"] for n in pn._async_get_or_create_notifications(hass).values()]
    assert any("did not respond" in m and "ausschalten" in m for m in messages)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    status = (await client.receive_json())["result"]["links"][0]["status"]
    assert "did not respond" in status["last_error"]["message"]


async def test_event_filter_and_conflicts(hass, setup_ll, hass_ws_client) -> None:
    """A 'double only' link ignores clicks; overlapping links are reported."""
    hass.states.async_set("light.a", "off")
    hass.states.async_set("light.b", "off")
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES + ["double"]})
    on = async_mock_service(hass, "light", "turn_on")
    client, _ = await create(
        hass_ws_client, hass,
        link("Nur doppelt", ["light.b"],
             options={"events": ["double"], "double": {"type": "on"}, "verify": {"enabled": False}}),
    )
    press(hass)
    await hass.async_block_till_done()
    assert not on
    press(hass, "double")
    await hass.async_block_till_done()
    assert on[-1].data["entity_id"] == ["light.b"]

    await client.send_json_auto_id({"type": "light_linker/links/create", "link": link("Klick", ["light.a"])})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id(
        {"type": "light_linker/links/create",
         "link": link("Auch doppelt", ["light.a"], options={"double": {"type": "off"}, "verify": {"enabled": False}})}
    )
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    links = (await client.receive_json())["result"]["links"]
    by_name = {l["name"]: l["status"]["conflicts"] for l in links}
    # 0.4: only links that actually occupy the same slot conflict
    assert "Nur doppelt" not in by_name["Klick"]
    assert "Nur doppelt" in by_name["Auch doppelt"]


async def test_dashboard_button(hass, setup_ll, hass_ws_client) -> None:
    """dashboard_button creates a button that runs the link, also when disabled."""
    hass.states.async_set("light.sofa2", "off")
    on = async_mock_service(hass, "light", "turn_on")
    client, created = await create(hass_ws_client, hass, link(dashboard_button=True, enabled=False))
    await hass.async_block_till_done()
    assert hass.states.get("button.light_linker_sofa_taste") is not None
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.light_linker_sofa_taste"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(on) == 1

    data = {**link(dashboard_button=False)}
    await client.send_json_auto_id(
        {"type": "light_linker/links/update", "link_id": created["id"], "link": data}
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get("button.light_linker_sofa_taste") is None


async def test_zha_source(hass, setup_ll, hass_ws_client, no_debounce) -> None:
    """zha_event of a watched IEEE triggers the gate profile, other IEEEs do not."""
    ieee = "94:ec:32:ff:fe:b9:55:f8"
    hass.states.async_set("cover.linkes_garagentor", "closed")
    toggle = async_mock_service(hass, "cover", "toggle")
    await create(
        hass_ws_client, hass,
        {
            "name": "Tor links",
            "profile": "gate",
            "sources": [{"adapter": "zha", "device_ieee": ieee.upper(), "button": "1"}],
            "targets": {"entity_id": ["cover.linkes_garagentor"]},
            "options": {"verify": {"enabled": False}},
        },
    )
    hass.bus.async_fire("zha_event", {"device_ieee": ieee, "command": "single", "endpoint_id": 2, "args": []})
    hass.bus.async_fire("zha_event", {"device_ieee": "00:00:00:00:00:00:00:01", "command": "single", "endpoint_id": 1})
    hass.bus.async_fire("zha_event", {"device_ieee": ieee, "command": "hold", "endpoint_id": 1})
    await hass.async_block_till_done()
    assert not toggle
    hass.bus.async_fire("zha_event", {"device_ieee": ieee, "command": "single", "endpoint_id": 1, "args": []})
    await hass.async_block_till_done()
    assert len(toggle) == 1


async def test_repair_issue_for_missing_entity(hass, setup_ll, hass_ws_client) -> None:
    """A link to an entity that does not exist raises a repair issue."""
    hass.states.async_set(HUE, "unknown", {"event_types": HUE_TYPES})
    _, created = await create(hass_ws_client, hass, link(targets=("light.gibt_es_nicht",)))
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue("light_linker", f"link_broken_{created['id']}")
    assert issue is not None
    assert issue.translation_placeholders["missing"] == "light.gibt_es_nicht"


async def test_learn_mode_only_listens_while_open(hass, setup_ll, hass_ws_client) -> None:
    """Unwatched event entities reach the learn session, and only while it is open."""
    client = await hass_ws_client(hass)
    other = "event.irgendein_taster"
    hass.states.async_set(other, "unknown", {"event_types": ["single"]})
    await client.send_json_auto_id({"type": "light_linker/learn/subscribe"})
    sub = await client.receive_json()
    assert sub["success"]
    press(hass, "single", None, other, ["single"])
    await hass.async_block_till_done()
    msg = await client.receive_json()
    assert msg["event"]["candidate"]["entity_id"] == other
    assert msg["event"]["candidate"]["kind"] == "press"


async def test_v01_store_loads(hass, hass_storage, hass_ws_client) -> None:
    """Links saved by v0.1 load unchanged and get the new defaults."""
    from homeassistant.setup import async_setup_component

    hass_storage["light_linker.links"] = {
        "version": 1,
        "minor_version": 1,
        "key": "light_linker.links",
        "data": {"links": [{
            "id": "01M5WHBBCYYBF6R5XKZZQ160F9", "name": "Fensterecke", "enabled": True,
            "profile": "toggle",
            "sources": [{"adapter": "event_entity", "entity_id": HUE, "button": "left", "mode": "button", "role": None}],
            "targets": {"entity_id": ["light.sofa1", "light.sofa3"], "area_id": []},
            "options": {"transition": 0.4}, "external_note": None,
            "created_at": "2026-10-26T16:40:26+00:00", "updated_at": "2026-10-26T16:40:26+00:00",
        }]},
    }
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "frontend", {})
    entry = MockConfigEntry(domain="light_linker", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/links/list"})
    links = (await client.receive_json())["result"]["links"]
    assert links[0]["id"] == "01M5WHBBCYYBF6R5XKZZQ160F9"
    assert links[0]["options"]["events"] == ["click", "double", "triple", "hold"]
    assert links[0]["dashboard_button"] is False
    assert links[0]["status"]["switch_entity"] == "switch.light_linker_fensterecke"


async def test_sources_list_with_odd_identifiers(hass, setup_ll, hass_ws_client) -> None:
    """Devices with 3-part identifiers must not break the source list; ZHA remotes show up."""
    dev_reg = dr.async_get(hass)
    other = MockConfigEntry(domain="legacy_thing", data={})
    other.add_to_hass(hass)
    dev_reg.async_get_or_create(config_entry_id=other.entry_id, identifiers={("legacy_thing", "a", "b")})

    zha = MockConfigEntry(domain="zha", data={})
    zha.add_to_hass(hass)
    coordinator = dev_reg.async_get_or_create(
        config_entry_id=zha.entry_id, identifiers={("zha", "00:21:2e:ff:ff:07:d9:df")}, name="Conbee II"
    )
    dev_reg.async_get_or_create(
        config_entry_id=zha.entry_id,
        identifiers={("zha", "94:ec:32:ff:fe:b9:55:f8")},
        name="ELW.EG.3-Fach Schalter",
        via_device=("zha", "00:21:2e:ff:ff:07:d9:df"),
    )
    assert coordinator

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "light_linker/sources/list"})
    msg = await client.receive_json()
    assert msg["success"], msg
    zha_sources = [s for s in msg["result"]["sources"] if s["adapter"] == "zha"]
    assert [s["device_ieee"] for s in zha_sources] == ["94:ec:32:ff:fe:b9:55:f8"]
