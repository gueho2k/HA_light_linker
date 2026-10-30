"""State sensor per motion link (aus, automatisch, Nachlauf, manuell, gesperrt)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_LINKS_CHANGED, SIGNAL_MOTION_STATE, MotionState, Profile
from .data import LightLinkerConfigEntry
from .engine import Engine
from .switch import service_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightLinkerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One sensor per motion link."""
    engine = entry.runtime_data
    entities: dict[str, MotionStateSensor] = {}

    @callback
    def _sync() -> None:
        wanted = {lid for lid, link in engine.links.items() if link.profile == Profile.MOTION}
        new = [MotionStateSensor(engine, lid) for lid in wanted if lid not in entities]
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

    @callback
    def _state(link_id: str) -> None:
        if entity := entities.get(link_id):
            entity.async_refresh()

    _sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_LINKS_CHANGED, _sync))
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_MOTION_STATE, _state))


class MotionStateSensor(SensorEntity):
    """What the motion automatic is doing right now."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [str(state) for state in MotionState]
    _attr_translation_key = "motion_state"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, engine: Engine, link_id: str) -> None:
        """Initialize."""
        self._engine = engine
        self.link_id = link_id
        self._attr_unique_id = f"{link_id}_motion_state"
        self._attr_device_info = service_device_info()

    @property
    def name(self) -> str | None:
        """Entity name = link name + Status."""
        link = self._engine.links.get(self.link_id)
        return f"{link.name} Status" if link else None

    @property
    def native_value(self) -> str | None:
        """Current state."""
        status = self._engine.motion_status(self.link_id)
        return status["state"] if status else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Timer end and occupancy."""
        status = self._engine.motion_status(self.link_id) or {}
        return {
            "link_id": self.link_id,
            "timer_end": status.get("timer_end"),
            "occupied": status.get("occupied"),
        }

    @callback
    def async_refresh(self) -> None:
        """Write the state if added."""
        if self.hass is not None:
            self.async_write_ha_state()
