"""Translate raw event types of the different stacks into normalized kinds."""

from __future__ import annotations

import re

from ..const import EventKind, SlotEvent

# Event types that tell us the device reports the end of a hold
RELEASE_TYPES = frozenset(
    {
        "hold_release",
        "release",
        "brightness_stop",
        "press_long_release",
        "long_release",
        "long_press_release",
    }
)

# raw event type -> (kind, direction)
_KIND_MAP: dict[str, tuple[EventKind | None, str | None]] = {
    # Zigbee2MQTT generic / Moes / Aqara
    "single": (EventKind.PRESS, None),
    "double": (EventKind.DOUBLE, None),
    "triple": (EventKind.TRIPLE, None),
    "hold": (EventKind.HOLD_START, None),
    "release": (EventKind.HOLD_END, None),
    # Hue wall switch module via Z2M
    "press_release": (EventKind.PRESS, None),
    "hold_release": (EventKind.HOLD_END, None),
    "toggle": (EventKind.TOGGLE, None),
    # IKEA RODRET / STYRBAR style dimmers
    "on": (EventKind.ON, None),
    "off": (EventKind.OFF, None),
    "brightness_move_up": (EventKind.HOLD_START, "up"),
    "brightness_move_down": (EventKind.HOLD_START, "down"),
    "brightness_stop": (EventKind.HOLD_END, None),
    # Homematic IP (homematicip_local)
    "press_short": (EventKind.PRESS, None),
    "press_long_start": (EventKind.HOLD_START, None),
    "press_long": (EventKind.HOLD_REPEAT, None),
    "press_long_release": (EventKind.HOLD_END, None),
    # Hue integration / Matter generic switch
    "short_release": (EventKind.PRESS, None),
    "long_press": (EventKind.HOLD_START, None),
    "long_release": (EventKind.HOLD_END, None),
    "repeat": (EventKind.HOLD_REPEAT, None),
    "multi_press_2": (EventKind.DOUBLE, None),
    "multi_press_3": (EventKind.TRIPLE, None),
    "initial_press": (None, None),
}

# "single_left", "hold_both" ... (Aqara H1)
_SUFFIX_BUTTON = re.compile(r"^(single|double|triple|hold|release)_(left|right|both)$")

# "<button>_<what>": 1_single (Moes), left_press_release (Hue), arrow_left_click
# (STYRBAR), 1_short_release (SOMRIG), toggle_hold (TRADFRI). Longest first.
_PREFIX_SUFFIXES: tuple[tuple[str, EventKind | None], ...] = (
    ("press_release", EventKind.PRESS),
    ("hold_release", EventKind.HOLD_END),
    ("long_release", EventKind.HOLD_END),
    ("short_release", EventKind.PRESS),
    ("initial_press", None),
    ("double_press", EventKind.DOUBLE),
    ("triple_press", EventKind.TRIPLE),
    ("long_press", EventKind.HOLD_START),
    ("click", EventKind.PRESS),
    ("single", EventKind.PRESS),
    ("double", EventKind.DOUBLE),
    ("triple", EventKind.TRIPLE),
    ("hold", EventKind.HOLD_START),
    ("release", EventKind.HOLD_END),
    ("press", EventKind.PRESS),
)


def normalize(
    event_type: str,
    button_attr: str | None,
    event_types: list[str] | tuple[str, ...] | None,
    overrides: dict[str, str] | None = None,
) -> tuple[str | None, EventKind | None, str | None]:
    """Return (button, kind, direction) for a raw event type.

    kind is None when the event must be ignored.
    """
    button = str(button_attr) if button_attr not in (None, "") else None
    types = set(event_types or ())

    if overrides and event_type in overrides:
        value = overrides[event_type]
        return button, (EventKind(value) if value else None), None

    # Hue modules send "press" first and "press_release" afterwards: only the
    # release counts as a click, otherwise every hold would also click.
    if event_type == "press":
        return button, (None if "press_release" in types else EventKind.PRESS), None
    if event_type in _KIND_MAP:
        kind, direction = _KIND_MAP[event_type]
        return button, kind, direction
    if match := _SUFFIX_BUTTON.match(event_type):
        kind, _ = _KIND_MAP[match.group(1)]
        return match.group(2), kind, None
    for suffix, kind in _PREFIX_SUFFIXES:
        if event_type.endswith("_" + suffix) and len(event_type) > len(suffix) + 1:
            prefix = event_type[: -len(suffix) - 1]
            if suffix == "press" and f"{prefix}_press_release" in types:
                return prefix, None, None
            return prefix, kind, None
    return button, None, None


def slot_event(kind: EventKind, direction: str | None) -> SlotEvent | str | None:
    """Normalized kind -> slot event; "release" / "repeat" end or extend a hold."""
    if kind in (EventKind.PRESS, EventKind.TOGGLE):
        return SlotEvent.PRESS
    if kind == EventKind.HOLD_START:
        if direction == "up":
            return SlotEvent.HOLD_UP
        if direction == "down":
            return SlotEvent.HOLD_DOWN
        return SlotEvent.HOLD
    if kind == EventKind.HOLD_END:
        return "release"
    if kind == EventKind.HOLD_REPEAT:
        return "repeat"
    return {
        EventKind.DOUBLE: SlotEvent.DOUBLE,
        EventKind.TRIPLE: SlotEvent.TRIPLE,
        EventKind.ON: SlotEvent.ON,
        EventKind.OFF: SlotEvent.OFF,
        EventKind.RISING: SlotEvent.RISE,
        EventKind.FALLING: SlotEvent.FALL,
    }.get(kind)


def has_release(event_types: list[str] | tuple[str, ...] | None) -> bool:
    """Whether the device reports the end of a hold."""
    types = set(event_types or ())
    if types & RELEASE_TYPES:
        return True
    return any(t.endswith(("_release", "_hold_release", "_long_release")) for t in types)


def buttons_from_event_types(event_types: list[str] | tuple[str, ...] | None) -> list[str]:
    """Button names encoded in the event types (single_left, 1_hold, arrow_left_click)."""
    buttons: list[str] = []
    for raw in event_types or ():
        button, kind, _ = normalize(raw, None, event_types)
        if kind is not None and button is not None and button not in buttons:
            buttons.append(button)
    return buttons


# ZHA zha_event commands -> (kind, has_release)
_ZHA_COMMANDS: dict[str, EventKind | None] = {
    "single": EventKind.PRESS,
    "click": EventKind.PRESS,
    "short_press": EventKind.PRESS,
    "remote_button_short_press": EventKind.PRESS,
    "double": EventKind.DOUBLE,
    "remote_button_double_press": EventKind.DOUBLE,
    "triple": EventKind.TRIPLE,
    "remote_button_triple_press": EventKind.TRIPLE,
    "hold": EventKind.HOLD_START,
    "long_press": EventKind.HOLD_START,
    "remote_button_long_press": EventKind.HOLD_START,
    "release": EventKind.HOLD_END,
    "long_release": EventKind.HOLD_END,
    "remote_button_long_release": EventKind.HOLD_END,
    "on": EventKind.ON,
    "off": EventKind.OFF,
    "toggle": EventKind.TOGGLE,
    "stop": EventKind.HOLD_END,
    "stop_with_on_off": EventKind.HOLD_END,
    # step commands are single dim steps; ignored in v0.2
    "step": None,
    "step_with_on_off": None,
}


def normalize_zha(
    command: str, args: object, endpoint_id: object, params: object
) -> tuple[str | None, EventKind | None, str | None, bool]:
    """Return (button, kind, direction, has_release) for a zha_event."""
    button: str | None = None
    if isinstance(params, dict) and params.get("button") not in (None, ""):
        button = str(params["button"])
    elif endpoint_id is not None:
        button = str(endpoint_id)

    if command in ("move", "move_with_on_off"):
        mode = None
        if isinstance(args, list | tuple) and args:
            mode = args[0]
        elif isinstance(params, dict):
            mode = params.get("move_mode")
        direction = "down" if mode in (1, "1", "down", "Down") else "up"
        return button, EventKind.HOLD_START, direction, True

    kind = _ZHA_COMMANDS.get(command)
    has_rel = kind == EventKind.HOLD_END
    return button, kind, None, has_rel
