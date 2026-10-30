"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

# pytest-homeassistant-custom-component ships its own custom_components package;
# make ours discoverable next to it.
import custom_components

_OURS = str(Path(__file__).parent.parent / "custom_components")
if _OURS not in custom_components.__path__:
    custom_components.__path__.append(_OURS)

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "light_linker"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    yield


@pytest.fixture
async def setup_ll(hass: HomeAssistant):
    """Set up Light Linker with its dependencies and return the config entry."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "frontend", {})
    entry = MockConfigEntry(domain=DOMAIN, title="Light Linker", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
