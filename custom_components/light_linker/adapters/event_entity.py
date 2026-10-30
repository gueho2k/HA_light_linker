"""Adapter for event entities (Zigbee2MQTT, Matter, Homematic IP, Hue, Shelly ...)."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.util import dt as dt_util

from ..const import MAX_EVENT_AGE_S, Adapter
from ..models import NormalizedEvent
from .base import StateTrackingAdapter
from .device_maps import has_release, normalize

_LOGGER = logging.getLogger(__name__)


class EventEntityAdapter(StateTrackingAdapter):
    """Turn state changes of event.* entities into button events."""

    adapter = Adapter.EVENT_ENTITY

    def _learnable(self, entity_id: str, event_data: EventStateChangedData) -> bool:
        return entity_id.startswith("event.")

    @callback
    def _handle(self, event: Event[EventStateChangedData]) -> None:
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        # Restored states at startup and (un)availability changes are no presses.
        if old_state is None or new_state is None:
            return
        if old_state.state == STATE_UNAVAILABLE:
            return
        if new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        fired_at = dt_util.parse_datetime(new_state.state) or dt_util.utcnow()
        if dt_util.utcnow() - fired_at > timedelta(seconds=MAX_EVENT_AGE_S):
            _LOGGER.debug("Ignoring stale event from %s", new_state.entity_id)
            return

        attrs = new_state.attributes
        raw_type = attrs.get("event_type")
        if not raw_type:
            return
        event_types = attrs.get("event_types") or ()
        button, kind, direction = normalize(str(raw_type), attrs.get("button"), event_types)

        self._engine.async_learn_candidate(
            adapter=self.adapter,
            ident=new_state.entity_id,
            button=button,
            raw_type=str(raw_type),
            kind=kind,
        )
        if kind is None:
            return
        _LOGGER.debug("%s %s -> %s %s", new_state.entity_id, raw_type, button, kind)
        self._engine.async_handle_event(
            NormalizedEvent(
                source_key=f"{self.adapter}:{new_state.entity_id}",
                entity_id=new_state.entity_id,
                button=button,
                kind=kind,
                direction=direction,
                raw_type=str(raw_type),
                has_release=has_release(event_types),
                fired_at=fired_at,
            )
        )
