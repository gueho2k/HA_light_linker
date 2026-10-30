"""Typed hass.data keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

if TYPE_CHECKING:
    from .engine import Engine

type LightLinkerConfigEntry = ConfigEntry[Engine]

DATA_ENGINE: HassKey[Engine] = HassKey(f"{DOMAIN}_engine")
DATA_STATIC_REGISTERED: HassKey[bool] = HassKey(f"{DOMAIN}_static")
