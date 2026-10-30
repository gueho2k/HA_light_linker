"""Adapter for binary inputs (Shelly inputs, input_boolean, relays)."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.util import dt as dt_util

from ..const import OCCUPANCY_CLASSES, Adapter, EventKind
from ..models import NormalizedEvent
from .base import StateTrackingAdapter


class StateInputAdapter(StateTrackingAdapter):
    """Turn on/off edges of an input into raw rising/falling events."""

    adapter = Adapter.STATE_INPUT

    def _learnable(self, entity_id: str, event_data: EventStateChangedData) -> bool:
        # Relays (switch.*) would flood a learn session; inputs only. Motion and
        # presence sensors belong to the occupancy adapter.
        if not entity_id.startswith(("binary_sensor.", "input_boolean.")):
            return False
        state = event_data["new_state"]
        return state is None or state.attributes.get("device_class") not in OCCUPANCY_CLASSES

    @callback
    def _handle(self, event: Event[EventStateChangedData]) -> None:
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if old_state is None or new_state is None:
            return
        if (old_state.state, new_state.state) == (STATE_OFF, STATE_ON):
            kind = EventKind.RISING
        elif (old_state.state, new_state.state) == (STATE_ON, STATE_OFF):
            kind = EventKind.FALLING
        else:
            return
        raw = f"{old_state.state}->{new_state.state}"
        self._engine.async_learn_candidate(
            adapter=self.adapter, ident=new_state.entity_id, button=None, raw_type=raw, kind=kind
        )
        self._engine.async_handle_event(
            NormalizedEvent(
                source_key=f"{self.adapter}:{new_state.entity_id}",
                entity_id=new_state.entity_id,
                button=None,
                kind=kind,
                direction=None,
                raw_type=raw,
                has_release=True,
                fired_at=dt_util.utcnow(),
            )
        )
