"""Persistent storage for links."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_MINOR_VERSION, STORAGE_VERSION
from .models import Link

_LOGGER = logging.getLogger(__name__)


class _LinkStore(Store[dict[str, Any]]):
    """Store with a migration hook for future versions."""

    pre_bindings: dict[str, Any] | None = None

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        # 1.1 - 1.3 -> 1.4: links without "bindings" get them from their profile
        # template when they are loaded (models.Link.from_dict). Keep a copy of
        # the old data so going back to 0.3 stays possible.
        if old_major_version == 1 and old_minor_version < 4:
            self.pre_bindings = old_data
        return old_data


class LinkStore:
    """Load and save links."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._hass = hass
        self._store = _LinkStore(
            hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_MINOR_VERSION
        )
        self.links: dict[str, Link] = {}
        # entity id / zha ieee -> Zigbee IEEE as 0x..., kept for the ZHA -> Z2M move
        self.ieee_hints: dict[str, str] = {}
        # source key (adapter:ident) -> who else uses this button (e.g. "Node-RED Terrarium")
        self.external: dict[str, str] = {}
        # source key -> buttons the device has sent (Z2M event entities report the
        # button only with each press)
        self.seen_buttons: dict[str, list[str]] = {}
        # Light Linker groups: id -> {id, name, area_id, members}
        self.groups: dict[str, dict[str, Any]] = {}
        # source key -> readable name given in the panel
        self.aliases: dict[str, str] = {}

    async def async_load(self) -> None:
        """Load links from disk, skipping entries that no longer validate."""
        data = await self._store.async_load() or {}
        if self._store.pre_bindings is not None:
            backup = Store[dict[str, Any]](self._hass, STORAGE_VERSION, f"{STORAGE_KEY}.backup_0_3", minor_version=3)
            await backup.async_save(self._store.pre_bindings)
            _LOGGER.info("Saved a copy of the 0.3 links as %s.backup_0_3", STORAGE_KEY)
        for raw in data.get("links", []):
            try:
                link = Link.from_dict(raw)
            except vol.Invalid as err:
                _LOGGER.error("Skipping invalid link %s: %s", raw.get("id"), err)
                continue
            self.links[link.id] = link
        self.ieee_hints = dict(data.get("ieee_hints", {}))
        self.external = dict(data.get("external", {}))
        self.seen_buttons = {k: list(v) for k, v in data.get("seen_buttons", {}).items()}
        self.aliases = dict(data.get("aliases", {}))
        self.groups = {g["id"]: g for g in data.get("groups", []) if isinstance(g, dict) and g.get("id")}

    def async_schedule_save(self) -> None:
        """Save soon (debounced)."""
        self._store.async_delay_save(self._data_to_save, 1)

    async def async_save(self) -> None:
        """Save now."""
        await self._store.async_save(self._data_to_save())

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "links": [link.as_dict() for link in self.links.values()],
            "ieee_hints": self.ieee_hints,
            "external": self.external,
            "seen_buttons": self.seen_buttons,
            "groups": list(self.groups.values()),
            "aliases": self.aliases,
        }
