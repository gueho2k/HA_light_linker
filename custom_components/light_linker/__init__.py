"""Light Linker: link buttons and switches to lights, plugs and gates."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
    EventKind,
)
from .data import DATA_ENGINE, DATA_STATIC_REGISTERED, LightLinkerConfigEntry
from .engine import Engine, LinkNotFound
from .store import LinkStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_TRIGGER = "trigger"
SERVICE_TRIGGER_SCHEMA = vol.Schema(
    {
        vol.Required("link_id"): cv.string,
        vol.Optional("kind", default=EventKind.PRESS): vol.In(
            [k.value for k in EventKind if k not in (EventKind.RISING, EventKind.FALLING)]
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register WebSocket commands and services once."""
    websocket.async_register(hass)

    async def _trigger(call: ServiceCall) -> None:
        engine = hass.data.get(DATA_ENGINE)
        if engine is None:
            raise ServiceValidationError("Light Linker is not loaded")
        try:
            engine.async_trigger(call.data["link_id"], EventKind(call.data["kind"]), origin="service")
        except LinkNotFound as err:
            raise ServiceValidationError(f"Unknown link: {call.data['link_id']}") from err

    hass.services.async_register(DOMAIN, SERVICE_TRIGGER, _trigger, SERVICE_TRIGGER_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LightLinkerConfigEntry) -> bool:
    """Set up Light Linker from its config entry."""
    store = LinkStore(hass)
    await store.async_load()
    engine = Engine(hass, entry, store)
    await engine.library.async_load()
    entry.runtime_data = engine
    hass.data[DATA_ENGINE] = engine

    await _async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen only once HA is running, so restored states trigger nothing.
    @callback
    def _start(_hass: HomeAssistant) -> None:
        engine.async_start()

    entry.async_on_unload(async_at_started(hass, _start))
    entry.async_on_unload(engine.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LightLinkerConfigEntry) -> bool:
    """Unload."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save()
        hass.data.pop(DATA_ENGINE, None)
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    return unloaded


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel bundle and add the sidebar entry (admins only)."""
    if not hass.data.get(DATA_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False
                )
            ]
        )
        hass.data[DATA_STATIC_REGISTERED] = True

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_URL}/light-linker-panel.js?v={VERSION}",
        require_admin=True,
        config={"version": VERSION},
    )
