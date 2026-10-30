"""Diagnostics: links, index and recent activity."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .data import LightLinkerConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LightLinkerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    engine = entry.runtime_data
    return {
        "links": [link.as_dict() for link in engine.links.values()],
        "index": {key: [link.id for link, _ in entries] for key, entries in engine._index.items()},  # noqa: SLF001
        "conflicts": engine.conflicts(),
        "missing": {link.id: engine.missing(link) for link in engine.links.values()},
        "last_error": engine.last_error,
        "activity": list(engine.activity),
    }
