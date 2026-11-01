"""Tests for v0.6: relay echoes (Sonoff ZBMINI), seconds for manual run-on, sensor calibration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from homeassistant.core import Context, HomeAssistant, State

from custom_components.light_linker import calibration as calib_mod
from custom_components.light_linker.calibration import SensorCalibration
from custom_components.light_linker.data import DATA_ENGINE

from .test_v03 import LAMP, LUX, PIR, create, fake_lights, kitchen, later, status


@pytest.fixture
async def room(hass: HomeAssistant, setup_ll):
    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    hass.states.async_set(LUX, "12", {"device_class": "illuminance"})
    hass.states.async_set(LAMP, "off")
    await hass.async_block_till_done()
    return fake_lights(hass)


async def _settle(hass: HomeAssistant) -> None:
    await hass.async_block_till_done()
    later(hass, 3)
    await hass.async_block_till_done()


async def test_relay_jumps_back_after_auto_on(hass, room, hass_ws_client) -> None:
    """ZBMINI reports 'off' right after our 'on' (even under our context): switch once more, stay automatic."""
    calls = room
    await create(hass_ws_client, hass, kitchen())
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    assert [c.service for c in calls] == ["turn_on"]
    own = calls[0].context
    hass.states.async_set(LAMP, "off", context=own)  # stale report of the relay
    await _settle(hass)
    assert [c.service for c in calls] == ["turn_on", "turn_on"]
    st = await status(hass_ws_client, hass)
    assert st["state"] == "auto"
    assert "zurück" in st["last_glitch"]


async def test_on_off_flicker_is_ignored(hass, room, hass_ws_client, monkeypatch) -> None:
    """A foreign off-on within the settle time while automatic changes nothing."""
    monkeypatch.setattr("custom_components.light_linker.motion.ECHO_S", -1)
    calls = room
    await create(hass_ws_client, hass, kitchen())
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    hass.states.async_set(LAMP, "off", context=Context())
    await hass.async_block_till_done()
    hass.states.async_set(LAMP, "on", context=Context())
    await _settle(hass)
    assert [c.service for c in calls] == ["turn_on"]
    assert (await status(hass_ws_client, hass))["state"] == "auto"


async def test_wall_switch_still_counts_as_hand(hass, room, hass_ws_client, monkeypatch) -> None:
    """A real switch-off by hand (state stays off) blocks the automatic as before."""
    monkeypatch.setattr("custom_components.light_linker.motion.ECHO_S", -1)
    await create(hass_ws_client, hass, kitchen())
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    hass.states.async_set(LAMP, "off", context=Context())
    await _settle(hass)
    assert (await status(hass_ws_client, hass))["state"] == "blocked"


async def test_manual_run_on_in_seconds(hass, room, hass_ws_client, monkeypatch) -> None:
    """'Von Hand eingeschaltet: aus nach 30 s' works in seconds."""
    monkeypatch.setattr("custom_components.light_linker.motion.ECHO_S", -1)
    calls = room
    _, msg = await create(hass_ws_client, hass, kitchen(manual_off_delay_s=30))
    assert msg["success"], msg
    hass.states.async_set(LAMP, "on", context=Context())
    await _settle(hass)
    assert (await status(hass_ws_client, hass))["state"] == "manual"
    later(hass, 34)
    await hass.async_block_till_done()
    assert [c.service for c in calls] == ["turn_off"]


def _feed(cal: SensorCalibration, monkeypatch, entity: str, periods: list[tuple[float, float]]) -> None:
    """periods: (on seconds, then off seconds) repeated."""
    clock = [datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(calib_mod.dt_util, "utcnow", lambda: clock[0])
    state = State(entity, "off")
    cal.observe(None, state)
    for on_s, off_s in periods:
        new = State(entity, "on")
        cal.observe(state, new)
        state = new
        clock[0] += timedelta(seconds=on_s)
        new = State(entity, "off")
        cal.observe(state, new)
        state = new
        clock[0] += timedelta(seconds=off_s)


def test_calibration_hue_vs_ikea(hass, monkeypatch) -> None:
    """Hue: short hold, run-on almost unchanged. IKEA: holds 3 min, timer shrinks to the floor."""
    cal = SensorCalibration(hass, {}, lambda: None)
    _feed(cal, monkeypatch, "binary_sensor.hue", [(10, 15), (12, 20), (10, 8), (11, 25), (10, 12), (14, 18)])
    _feed(cal, monkeypatch, "binary_sensor.ikea", [(180, 5), (200, 4), (185, 6), (240, 3), (181, 5)])
    hue = cal.info("binary_sensor.hue")
    ikea = cal.info("binary_sensor.ikea")
    assert 9 <= hue["hold_s"] <= 12 and 15 <= hue["gap_s"] <= 25
    assert 175 <= ikea["hold_s"] <= 190
    timer, info = cal.runout(["binary_sensor.hue"], 60)
    assert info["calibrated"] and 45 <= timer <= 52
    timer, info = cal.runout(["binary_sensor.ikea"], 60)
    assert calib_mod.MIN_RUNOUT_S <= timer <= 10
    # not enough samples: the setting is used as it is
    assert cal.runout(["binary_sensor.new"], 60) == (60, {"calibrated": False})
    # stored and loaded again
    again = SensorCalibration(hass, cal.as_data(), lambda: None)
    assert again.info("binary_sensor.ikea") == ikea


async def test_calibrated_runout_used_by_motion_link(hass, room, hass_ws_client, monkeypatch) -> None:
    """An IKEA-like sensor that held 3 min already: the light goes off soon after 'no motion'."""
    calls = room
    engine = hass.data[DATA_ENGINE]
    engine.calibration = SensorCalibration(
        hass, {PIR: {"on": [180, 185, 190, 200, 181], "gap": [5, 4, 6]}}, lambda: None
    )
    await create(hass_ws_client, hass, kitchen(off_delay_s=60))
    hass.states.async_set(PIR, "on", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    hass.states.async_set(PIR, "off", {"device_class": "occupancy"})
    await hass.async_block_till_done()
    st = await status(hass_ws_client, hass)
    assert st["calibration"]["calibrated"] and st["calibration"]["hold_s"] >= 180
    later(hass, 10)
    await hass.async_block_till_done()
    assert [c.service for c in calls] == ["turn_on", "turn_off"]
