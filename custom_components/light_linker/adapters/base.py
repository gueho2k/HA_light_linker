"""Shared plumbing for adapters that follow entity states."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import Adapter

if TYPE_CHECKING:
    from ..engine import Engine


class StateTrackingAdapter:
    """Follows only the entities that links use.

    async_track_state_change_event dispatches by entity id from one shared
    listener, so state changes of unrelated entities cost nothing here. Only
    while a learn session is open a filtered bus listener sees everything.
    """

    adapter: Adapter

    def __init__(self, engine: Engine) -> None:
        """Initialize."""
        self._engine = engine
        self._hass = engine.hass
        self._watched: frozenset[str] = frozenset()
        self._track_unsub: CALLBACK_TYPE | None = None
        self._learn_unsub: CALLBACK_TYPE | None = None

    @callback
    def async_set_watched(self, entity_ids: Iterable[str]) -> None:
        """Follow exactly these entities."""
        ids = frozenset(entity_ids)
        if ids == self._watched and (self._track_unsub or not ids):
            return
        self._watched = ids
        if self._track_unsub:
            self._track_unsub()
            self._track_unsub = None
        if ids:
            self._track_unsub = async_track_state_change_event(
                self._hass, sorted(ids), self._handle
            )

    @callback
    def async_set_learning(self, learning: bool) -> None:
        """Open or close the catch-all listener of a learn session."""
        if learning and self._learn_unsub is None:
            self._learn_unsub = self._hass.bus.async_listen(
                EVENT_STATE_CHANGED, self._handle, event_filter=self._learn_filter
            )
        elif not learning and self._learn_unsub is not None:
            self._learn_unsub()
            self._learn_unsub = None

    @callback
    def _learn_filter(self, event_data: EventStateChangedData) -> bool:
        entity_id = event_data["entity_id"]
        # Watched entities already arrive through the tracker.
        return entity_id not in self._watched and self._learnable(entity_id, event_data)

    def _learnable(self, entity_id: str, event_data: EventStateChangedData) -> bool:
        raise NotImplementedError

    @callback
    def _handle(self, event: Event[EventStateChangedData]) -> None:
        raise NotImplementedError

    @callback
    def async_stop(self) -> None:
        """Remove all listeners."""
        self.async_set_learning(False)
        if self._track_unsub:
            self._track_unsub()
            self._track_unsub = None
        self._watched = frozenset()
