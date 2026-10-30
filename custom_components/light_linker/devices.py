"""Device library: what a remote looks like and which slots (button x event) it has.

Every file in devices/ describes one family of remotes: the drawing (frame and
button rectangles), which slots belong to which button and how the device ends
a hold. Devices without a file get a plain drawing built from what their event
entity reports.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .adapters.device_maps import has_release, normalize, slot_event
from .const import Adapter, SlotEvent

_LOGGER = logging.getLogger(__name__)
_DIR = Path(__file__).parent / "devices"

# Events offered for devices whose event list is unknown (ZHA without file)
_ZHA_GENERIC = (SlotEvent.PRESS, SlotEvent.DOUBLE, SlotEvent.HOLD)


def load_library() -> list[dict[str, Any]]:
    """Read all device files (blocking, run in the executor)."""
    result = []
    for path in sorted(_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            _LOGGER.warning("Skipping device file %s: %s", path.name, err)
            continue
        if isinstance(data, dict) and data.get("buttons"):
            result.append(data)
    return result


def match(library: list[dict[str, Any]], device: dr.DeviceEntry | None) -> dict[str, Any] | None:
    """The library entry for a device (longest matching model text wins)."""
    if device is None:
        return None
    texts = " ".join(
        str(v) for v in (device.model, getattr(device, "model_id", None)) if v
    ).lower()
    if not texts:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for entry in library:
        for needle in entry.get("match", []):
            if needle.lower() in texts and (best is None or len(needle) > best[0]):
                best = (len(needle), entry)
    return best[1] if best else None


def parse_slot(text: str) -> tuple[str | None, str]:
    """'left:press' -> ('left', 'press'); ':on' -> (None, 'on')."""
    button, _, event = text.partition(":")
    return (button or None), event


def _generic_slots(
    adapter: Adapter, event_types: list[str], buttons: list[str]
) -> list[tuple[str | None, str]]:
    """Slots derived from the event list and the buttons seen so far."""
    if adapter == Adapter.STATE_INPUT:
        return [(None, SlotEvent.RISE), (None, SlotEvent.FALL)]
    if adapter == Adapter.OCCUPANCY:
        return []
    found: list[tuple[str | None, str]] = []
    generic_events: list[str] = []
    for raw in event_types:
        button, kind, direction = normalize(raw, None, event_types)
        if kind is None:
            continue
        event = slot_event(kind, direction)
        if not isinstance(event, SlotEvent):
            continue  # release / repeat are no slots
        if button is None:
            if event not in generic_events:
                generic_events.append(event)
        elif (button, event) not in found:
            found.append((button, event))
    if adapter == Adapter.ZHA and not event_types:
        generic_events = list(_ZHA_GENERIC)
    # Z2M event entities report the button as attribute: combine with buttons seen
    on_off = {SlotEvent.ON, SlotEvent.OFF, SlotEvent.HOLD_UP, SlotEvent.HOLD_DOWN}
    per_button = [e for e in generic_events if e not in on_off]
    if buttons and per_button:
        for button in buttons:
            for event in per_button:
                if (button, event) not in found:
                    found.append((button, event))
        generic_events = [e for e in generic_events if e in on_off]
    found = [(None, e) for e in generic_events] + found
    # Light Linker recognises double / triple itself where the device does not
    for button in dict.fromkeys(b for b, _ in found):
        events = {e for b, e in found if b == button}
        if SlotEvent.PRESS in events:
            for extra in (SlotEvent.DOUBLE, SlotEvent.TRIPLE):
                if extra not in events:
                    found.append((button, extra))
    return found


_KEYS_RE = re.compile(r"(\d)\s*(?:-\s*)?(?:keys?|buttons?|gang|tasten|fach|-fach)\b", re.IGNORECASE)


def _keys_from_model(device: dr.DeviceEntry) -> int | None:
    """Number of keys named in the model text, e.g. 'Scene remote with 3 keys'."""
    text = " ".join(str(v) for v in (device.model, getattr(device, "model_id", None)) if v)
    if match := _KEYS_RE.search(text):
        count = int(match.group(1))
        if 2 <= count <= 8:
            return count
    return None


def native_multi(entry: dict[str, Any] | None, adapter: Adapter, event_types: list[str]) -> bool:
    """Whether the device reports double clicks itself."""
    if event_types:
        for raw in event_types:
            _, kind, direction = normalize(raw, None, event_types)
            if kind is not None and slot_event(kind, direction) == SlotEvent.DOUBLE:
                return True
        return False
    if entry is not None:
        return bool(entry.get("native_multi"))
    # ZHA without file: most ZHA remotes send their own double clicks
    return adapter == Adapter.ZHA


def hold_end(entry: dict[str, Any] | None, event_types: list[str]) -> str:
    """How the device ends a hold: release, repeat or none."""
    if event_types and has_release(event_types):
        return "release"
    if entry is not None and entry.get("hold_end"):
        return str(entry["hold_end"])
    return "release" if not event_types else "none"


def describe(
    library: list[dict[str, Any]],
    device: dr.DeviceEntry | None,
    adapter: Adapter,
    event_types: list[str],
    buttons: list[str],
) -> dict[str, Any]:
    """Drawing, slots and behaviour of one source for the panel."""
    entry = match(library, device) if adapter in (Adapter.EVENT_ENTITY, Adapter.ZHA) else None
    if entry is not None:
        layout_buttons = []
        for btn in entry["buttons"]:
            slots = []
            for text in btn.get("slots", []):
                button, event = parse_slot(text)
                slots.append({"button": button, "event": event})
            layout_buttons.append({**{k: v for k, v in btn.items() if k != "slots"}, "slots": slots})
        # buttons the device sent that the file does not know (other firmware)
        known = {(s["button"], s["event"]) for b in layout_buttons for s in b["slots"]}
        extra = [
            {"button": b, "event": str(e)}
            for b, e in _generic_slots(adapter, event_types, buttons)
            if (b, str(e)) not in known and b is not None
            and b not in {lb["id"] for lb in layout_buttons}
        ]
        if extra:
            layout_buttons.append(
                {"id": "_extra", "label": "weitere", "x": 0, "y": 0, "w": 0, "h": 0, "slots": extra}
            )
        return {
            "library": entry["id"],
            "model_name": entry["name"],
            "frame": entry["frame"],
            "buttons": layout_buttons,
            "hold_end": hold_end(entry, event_types),
            "native_multi": native_multi(entry, adapter, event_types),
        }

    # remotes that report the key as attribute ("button": "1") show only the keys
    # pressed so far; the model text often tells how many there are ("3 keys", "2-gang")
    if adapter == Adapter.EVENT_ENTITY and device is not None and (
        count := _keys_from_model(device)
    ) and (not buttons or all(str(b).isdigit() for b in buttons)):
        buttons = list(dict.fromkeys([*buttons, *(str(i) for i in range(1, count + 1))]))
        buttons.sort(key=lambda b: int(b))
    slots = _generic_slots(adapter, event_types, buttons)
    # dimmer-like remotes without a file (on/off + hold up/down, no button names):
    # draw them as two keys I and O like an IKEA dimmer
    unnamed = {str(e) for b, e in slots if b is None}
    if {"on", "off"} <= unnamed:
        sides = {
            "I": ["on", "hold_up", "press", "double", "triple", "hold"],
            "O": ["off", "hold_down"],
        }
        layout_buttons = []
        for index, (label, events) in enumerate(sides.items()):
            own = [{"button": None, "event": e} for e in events if e in unnamed]
            layout_buttons.append({"id": label, "label": label, "x": 0, "y": index * 52, "w": 64, "h": 52, "slots": own})
        named = [(b, e) for b, e in slots if b is not None]
        for button in dict.fromkeys(b for b, _ in named):
            layout_buttons.append({
                "id": button, "label": button, "x": 0, "y": 0, "w": 0, "h": 0,
                "slots": [{"button": b, "event": str(e)} for b, e in named if b == button],
            })
        return {
            "library": None,
            "model_name": device.model if device else None,
            "frame": {"w": 64, "h": 104, "r": 16},
            "buttons": layout_buttons,
            "hold_end": hold_end(None, event_types),
            "native_multi": native_multi(None, adapter, event_types),
        }
    order: list[str | None] = list(dict.fromkeys(b for b, _ in slots))
    layout_buttons = []
    count = max(1, len(order))
    for index, button in enumerate(order):
        label = button if button is not None else ("●" if count == 1 else "alle")
        layout_buttons.append(
            {
                "id": button if button is not None else "_any",
                "label": label,
                "x": 0,
                "y": round(index * 96 / count, 1),
                "w": 64,
                "h": round(96 / count, 1),
                "slots": [{"button": b, "event": str(e)} for b, e in slots if b == button],
            }
        )
    return {
        "library": None,
        "model_name": device.model if device else None,
        "frame": {"w": 64, "h": 96, "r": 12},
        "buttons": layout_buttons,
        "hold_end": hold_end(None, event_types) if adapter != Adapter.STATE_INPUT else "release",
        "native_multi": native_multi(None, adapter, event_types) if adapter != Adapter.STATE_INPUT else True,
    }


class DeviceLibrary:
    """Loaded once per setup; answers per source key."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load the device files in the executor."""
        self.entries = await self.hass.async_add_executor_job(load_library)
