"""Adapter for motion, occupancy and presence sensors."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, callback

from ..const import OCCUPANCY_CLASSES, Adapter, EventKind
from .base import StateTrackingAdapter


class OccupancyAdapter(StateTrackingAdapter):
    """Passes occupancy changes to the motion controllers of the engine."""

    adapter = Adapter.OCCUPANCY

    def _learnable(self, entity_id: str, event_data: EventStateChangedData) -> bool:
        if not entity_id.startswith("binary_sensor."):
            return False
        state = event_data["new_state"]
        return state is not None and state.attributes.get("device_class") in OCCUPANCY_CLASSES

    @callback
    def _handle(self, event: Event[EventStateChangedData]) -> None:
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if new_state is None:
            return
        old = old_state.state if old_state else None
        if old == new_state.state:
            return  # attribute change only
        if (old, new_state.state) == (STATE_OFF, STATE_ON):
            self._engine.async_learn_candidate(
                adapter=self.adapter,
                ident=new_state.entity_id,
                button=None,
                raw_type=new_state.attributes.get("device_class", "motion"),
                kind=EventKind.ON,
            )
        # Every change (incl. unavailable) can change the combined occupancy.
        self._engine.async_occupancy_changed(new_state.entity_id)
