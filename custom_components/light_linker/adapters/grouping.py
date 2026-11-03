"""Matter remotes report every key as its own event entity ("Taste (1)", "Taste (2)").

Light Linker shows them as one remote: the first entity is the source, the key
number is taken from the entity name (or the order) and becomes the button.
"""

from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_NUMBER = re.compile(r"(\d+)\)?\s*$")


def key_group(hass: HomeAssistant, entity_id: str) -> tuple[str, str, list[str]] | None:
    """(primary entity, key name of this entity, all entities) for a multi-key Matter remote.

    None for everything else (single entities, Zigbee2MQTT remotes with a button
    attribute, other integrations): those keep working as before.
    """
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get(entity_id)
    if entry is None or entry.platform != "matter" or not entry.device_id:
        return None
    siblings = sorted(
        e.entity_id
        for e in er.async_entries_for_device(ent_reg, entry.device_id)
        if e.domain == "event" and e.platform == "matter" and not e.disabled_by
    )
    if len(siblings) < 2:
        return None
    names: dict[str, str] = {}
    for sibling in siblings:
        item = ent_reg.async_get(sibling)
        text = (item.name or item.original_name or "") if item else ""
        match = _NUMBER.search(text)
        names[sibling] = match.group(1) if match else str(siblings.index(sibling) + 1)
    if len(set(names.values())) != len(siblings):
        names = {e: str(i + 1) for i, e in enumerate(siblings)}
    return siblings[0], names[entity_id], siblings
