"""Adapter for ZHA remotes (zha_event, identified by device IEEE)."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, callback
from homeassistant.util import dt as dt_util

from ..const import Adapter
from ..models import NormalizedEvent
from .device_maps import normalize_zha

if TYPE_CHECKING:
    from ..engine import Engine

_LOGGER = logging.getLogger(__name__)
EVENT_ZHA = "zha_event"


class ZhaAdapter:
    """Listen to zha_event; the bus only fires it for ZHA button presses."""

    adapter = Adapter.ZHA

    def __init__(self, engine: Engine) -> None:
        """Initialize."""
        self._engine = engine
        self._hass = engine.hass
        self._watched: frozenset[str] = frozenset()
        self._learning = False
        self._unsub: CALLBACK_TYPE | None = None

    @callback
    def async_set_watched(self, idents: Iterable[str]) -> None:
        """Device IEEEs to react to; listen only while there is something to do."""
        self._watched = frozenset(i.lower() for i in idents)
        self._update_listener()

    @callback
    def async_set_learning(self, learning: bool) -> None:
        """Pass every zha_event to the learn session."""
        self._learning = learning
        self._update_listener()

    @callback
    def _update_listener(self) -> None:
        needed = bool(self._watched) or self._learning
        if needed and self._unsub is None:
            self._unsub = self._hass.bus.async_listen(
                EVENT_ZHA, self._handle, event_filter=self._filter
            )
        elif not needed and self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _filter(self, data: dict[str, Any]) -> bool:
        return self._learning or str(data.get("device_ieee", "")).lower() in self._watched

    @callback
    def _handle(self, event: Event) -> None:
        data = event.data
        ieee = str(data.get("device_ieee", "")).lower()
        command = str(data.get("command", ""))
        button, kind, direction, has_rel = normalize_zha(
            command, data.get("args"), data.get("endpoint_id"), data.get("params")
        )
        self._engine.async_learn_candidate(
            adapter=self.adapter, ident=ieee, button=button, raw_type=command, kind=kind
        )
        if kind is None:
            return
        _LOGGER.debug("zha %s %s -> %s %s", ieee, command, button, kind)
        self._engine.async_handle_event(
            NormalizedEvent(
                source_key=f"{self.adapter}:{ieee}",
                entity_id=ieee,
                button=button,
                kind=kind,
                direction=direction,
                raw_type=command,
                has_release=has_rel,
                fired_at=dt_util.utcnow(),
            )
        )

    @callback
    def async_stop(self) -> None:
        """Remove the listener."""
        self._watched = frozenset()
        self._learning = False
        self._update_listener()
