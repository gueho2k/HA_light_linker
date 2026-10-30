"""Source adapters: translate stack specific events into NormalizedEvent."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from ..const import Adapter

if TYPE_CHECKING:
    from ..engine import Engine


class SourceAdapter(Protocol):
    """Interface every adapter implements."""

    adapter: Adapter

    def async_set_watched(self, idents: Iterable[str]) -> None:
        """Follow exactly these sources."""

    def async_set_learning(self, learning: bool) -> None:
        """Open or close a learn session."""

    def async_stop(self) -> None:
        """Remove all listeners."""


def create_adapters(engine: Engine) -> list[SourceAdapter]:
    """Instantiate all adapters."""
    from .event_entity import EventEntityAdapter  # noqa: PLC0415
    from .occupancy import OccupancyAdapter  # noqa: PLC0415
    from .state_input import StateInputAdapter  # noqa: PLC0415
    from .zha import ZhaAdapter  # noqa: PLC0415

    return [
        EventEntityAdapter(engine),
        StateInputAdapter(engine),
        ZhaAdapter(engine),
        OccupancyAdapter(engine),
    ]
