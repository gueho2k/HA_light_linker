"""Logbook entries for triggered links."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_TRIGGERED

_KIND_TEXT = {
    "press": "kurz gedrückt",
    "double": "doppelt gedrückt",
    "triple": "dreifach gedrückt",
    "hold_start": "gehalten",
    "hold_end": "losgelassen",
    "hold": "gehalten",
    "hold_up": "gehalten (hoch)",
    "hold_down": "gehalten (runter)",
    "on": "an",
    "off": "aus",
    "rise": "eingeschaltet",
    "fall": "ausgeschaltet",
    "toggle": "umgeschaltet",
    "motion_on": "Bewegung, Licht an",
    "motion_off": "Nachlauf vorbei, Licht aus",
    "manual_on": "von Hand eingeschaltet, Automatik wartet",
    "manual_off": "von Hand ausgeschaltet",
}

_ACTION_TEXT = {
    "toggle": "umschalten",
    "on": "einschalten",
    "off": "ausschalten",
    "brightness": "Helligkeit",
    "ramp_up": "Rampe hoch",
    "ramp_down": "Rampe runter",
    "ramp_alt": "Rampe",
    "cycle_color_temp": "Farbtemperatur weiter",
    "cycle_color": "Farbe weiter",
    "scene": "Szene",
    "cover_toggle": "Tor",
    "cover_open": "öffnen",
    "cover_close": "schließen",
    "cover_stop": "stopp",
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Describe light_linker_triggered."""

    @callback
    def _describe(event: Event) -> dict[str, Any]:
        data = event.data
        kind = _KIND_TEXT.get(data.get("kind", ""), data.get("kind"))
        if data.get("origin") == "motion":
            return {
                LOGBOOK_ENTRY_NAME: data.get("link_name", "Light Linker"),
                LOGBOOK_ENTRY_MESSAGE: kind,
            }
        state = hass.states.get(data.get("entity_id") or "")
        source = data.get("source_name") or (state.name if state else data.get("entity_id"))
        if data.get("button"):
            source = f"{source} ({data['button']})"
        origin = " [Test]" if data.get("origin") == "test" else ""
        action = _ACTION_TEXT.get(data.get("action") or "")
        arrow = f" → {action}" if action else ""
        return {
            LOGBOOK_ENTRY_NAME: data.get("link_name", "Light Linker"),
            LOGBOOK_ENTRY_MESSAGE: f"{source}: {kind}{arrow}{origin}",
        }

    async_describe_event(DOMAIN, EVENT_TRIGGERED, _describe)
