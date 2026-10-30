"""One 'aktiv' switch per link: disables a link and drives the automation fallback."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, PANEL_TITLE, SIGNAL_LINKS_CHANGED, VERSION
from .data import LightLinkerConfigEntry
from .engine import Engine

PARALLEL_UPDATES = 0


def service_device_info() -> DeviceInfo:
    """The one service device all Light Linker entities belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, "service")},
        name=PANEL_TITLE,
        entry_type=DeviceEntryType.SERVICE,
        sw_version=VERSION,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightLinkerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create switches for existing links and follow later changes."""
    engine = entry.runtime_data
    entities: dict[str, LinkActiveSwitch] = {}

    @callback
    def _sync() -> None:
        new = [LinkActiveSwitch(engine, link_id) for link_id in engine.links if link_id not in entities]
        for entity in new:
            entities[entity.link_id] = entity
        if new:
            async_add_entities(new)
        ent_reg = er.async_get(hass)
        for link_id in [lid for lid in entities if lid not in engine.links]:
            entity = entities.pop(link_id)
            if entity.entity_id and ent_reg.async_get(entity.entity_id):
                ent_reg.async_remove(entity.entity_id)
        for entity in entities.values():
            entity.async_refresh()

    _sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_LINKS_CHANGED, _sync))


class LinkActiveSwitch(SwitchEntity):
    """Whether Light Linker handles this link."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:link-variant"

    def __init__(self, engine: Engine, link_id: str) -> None:
        """Initialize."""
        self._engine = engine
        self.link_id = link_id
        self._attr_unique_id = link_id
        self._attr_device_info = service_device_info()

    @property
    def name(self) -> str | None:
        """Entity name = link name."""
        link = self._engine.links.get(self.link_id)
        return link.name if link else None

    @property
    def is_on(self) -> bool:
        """Link enabled."""
        link = self._engine.links.get(self.link_id)
        return bool(link and link.enabled)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the link id for automations and Node-RED."""
        return {"link_id": self.link_id}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the link."""
        self._engine.async_set_enabled(self.link_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the link (automations take over)."""
        self._engine.async_set_enabled(self.link_id, False)

    @callback
    def async_refresh(self) -> None:
        """Write the current state if the entity is added."""
        if self.hass is not None:
            self.async_write_ha_state()
