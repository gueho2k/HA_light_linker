"""Optional dashboard button per link: pressing it acts like a short press."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_LINKS_CHANGED, EventKind
from .data import LightLinkerConfigEntry
from .engine import Engine
from .switch import service_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightLinkerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create buttons for links with dashboard_button and follow changes."""
    engine = entry.runtime_data
    entities: dict[str, LinkButton] = {}

    @callback
    def _sync() -> None:
        wanted = {lid for lid, link in engine.links.items() if link.dashboard_button}
        new = [LinkButton(engine, lid) for lid in wanted if lid not in entities]
        for entity in new:
            entities[entity.link_id] = entity
        if new:
            async_add_entities(new)
        ent_reg = er.async_get(hass)
        for link_id in [lid for lid in entities if lid not in wanted]:
            entity = entities.pop(link_id)
            if entity.entity_id and ent_reg.async_get(entity.entity_id):
                ent_reg.async_remove(entity.entity_id)
        for entity in entities.values():
            entity.async_refresh()

    _sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_LINKS_CHANGED, _sync))


class LinkButton(ButtonEntity):
    """Runs the link like a short press of its button."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, engine: Engine, link_id: str) -> None:
        """Initialize."""
        self._engine = engine
        self.link_id = link_id
        self._attr_unique_id = f"{link_id}_button"
        self._attr_device_info = service_device_info()

    @property
    def name(self) -> str | None:
        """Entity name = link name."""
        link = self._engine.links.get(self.link_id)
        return f"{link.name} Taste" if link else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the link id."""
        return {"link_id": self.link_id}

    async def async_press(self) -> None:
        """Act like a short press, also while the link is switched off."""
        self._engine.async_trigger(self.link_id, EventKind.PRESS, origin="dashboard")

    @callback
    def async_refresh(self) -> None:
        """Write the state if added (name may have changed)."""
        if self.hass is not None:
            self.async_write_ha_state()
