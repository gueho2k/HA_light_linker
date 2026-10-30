"""Constants for Light Linker."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "light_linker"
VERSION: Final = "0.5.5"

STORAGE_KEY: Final = "light_linker.links"
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 4

PANEL_URL_PATH: Final = "light-linker"
PANEL_COMPONENT: Final = "light-linker-panel"
PANEL_TITLE: Final = "Light Linker"
PANEL_ICON: Final = "mdi:link-variant"
STATIC_URL: Final = "/light_linker_static"

EVENT_TRIGGERED: Final = "light_linker_triggered"
SIGNAL_LINKS_CHANGED: Final = "light_linker_links_changed"

# Domains a link may target
TARGET_DOMAINS: Final = ("light", "switch", "cover")
# Domains a state_input source may use
STATE_INPUT_DOMAINS: Final = ("binary_sensor", "input_boolean", "switch")

# Timing defaults
DEBOUNCE_S: Final = 0.15
MAX_EVENT_AGE_S: Final = 5.0
LEARN_DURATION_S: Final = 30
GATE_VERIFY_TIMEOUT_S: Final = 60
# How long a commanded state counts as truth before the device reports back
EXPECTED_STATE_TTL_S: Final = 3.0
ACTIVITY_BUFFER: Final = 50
# Presses closer together than this count as double / triple click when the
# device does not report multi presses itself
MULTI_PRESS_S: Final = 0.4
# A hold that the device repeats ends when no repeat came for this long
REPEAT_GAP_S: Final = 1.2

# Binary sensor device classes that count as motion / presence sources
OCCUPANCY_CLASSES: Final = ("motion", "occupancy", "presence")
# Default run-on after "all clear" by device class (seconds)
DEFAULT_OFF_DELAY_S: Final = {"motion": 30, "occupancy": 30, "presence": 15}
# Zigbee2MQTT naming (unique_id = <ieee|group id>_<object>_<base topic>)
Z2M_BASE_TOPIC: Final = "zigbee2mqtt"
SIGNAL_MOTION_STATE: Final = "light_linker_motion_state"

# Virtual CCU buttons that must not show up as sources by default
HIDDEN_SOURCE_MODELS: Final = ("HmIP-RCV-50", "HM-RCV-50")


class EventKind(StrEnum):
    """Normalized event kinds."""

    PRESS = "press"
    DOUBLE = "double"
    TRIPLE = "triple"
    HOLD_START = "hold_start"
    HOLD_REPEAT = "hold_repeat"
    HOLD_END = "hold_end"
    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"
    # Raw edges of a state_input; converted per source mode by the engine
    RISING = "rising"
    FALLING = "falling"


class Profile(StrEnum):
    """Behaviour profiles."""

    TOGGLE = "toggle"
    ROCKER = "rocker"
    SWITCH = "switch"
    GATE = "gate"
    MOTION = "motion"
    # bindings edited one by one in the panel (no template)
    CUSTOM = "custom"


class Adapter(StrEnum):
    """Source adapters."""

    EVENT_ENTITY = "event_entity"
    STATE_INPUT = "state_input"
    ZHA = "zha"
    OCCUPANCY = "occupancy"


class EventGroup(StrEnum):
    """What a link reacts to (user facing grouping of EventKind)."""

    CLICK = "click"
    DOUBLE = "double"
    TRIPLE = "triple"
    HOLD = "hold"


EVENT_GROUP_OF: Final = {
    "press": EventGroup.CLICK,
    "toggle": EventGroup.CLICK,
    "on": EventGroup.CLICK,
    "off": EventGroup.CLICK,
    "double": EventGroup.DOUBLE,
    "triple": EventGroup.TRIPLE,
    "hold_start": EventGroup.HOLD,
    "hold_repeat": EventGroup.HOLD,
    "hold_end": EventGroup.HOLD,
}


class ActionType(StrEnum):
    """What a binding does."""

    NONE = "none"
    TOGGLE = "toggle"
    ON = "on"
    OFF = "off"
    BRIGHTNESS = "brightness"
    RAMP_UP = "ramp_up"
    RAMP_DOWN = "ramp_down"
    RAMP_ALT = "ramp_alt"
    CYCLE_COLOR_TEMP = "cycle_color_temp"
    CYCLE_COLOR = "cycle_color"
    SCENE = "scene"
    COVER_TOGGLE = "cover_toggle"
    COVER_OPEN = "cover_open"
    COVER_CLOSE = "cover_close"
    COVER_STOP = "cover_stop"


RAMP_ACTIONS: Final = frozenset({ActionType.RAMP_UP, ActionType.RAMP_DOWN, ActionType.RAMP_ALT})


class SlotEvent(StrEnum):
    """Events a binding can be placed on (one slot = button x event)."""

    PRESS = "press"
    DOUBLE = "double"
    TRIPLE = "triple"
    HOLD = "hold"
    HOLD_UP = "hold_up"
    HOLD_DOWN = "hold_down"
    ON = "on"
    OFF = "off"
    RISE = "rise"
    FALL = "fall"


HOLD_EVENTS: Final = frozenset({SlotEvent.HOLD, SlotEvent.HOLD_UP, SlotEvent.HOLD_DOWN})
# Which user-facing event group (v0.3 "Reagiert auf") a slot event belongs to
SLOT_GROUP: Final = {
    "press": "click",
    "on": "click",
    "off": "click",
    "rise": "click",
    "fall": "click",
    "double": "double",
    "triple": "triple",
    "hold": "hold",
    "hold_up": "hold",
    "hold_down": "hold",
}


class ToggleMode(StrEnum):
    """How a group toggle decides."""

    ANY_ON = "any_on"
    ALL_ON = "all_on"


class MotionState(StrEnum):
    """States of a motion link."""

    OFF = "off"
    AUTO = "auto"
    RUNOUT = "runout"
    MANUAL = "manual"
    BLOCKED = "blocked"
    INACTIVE = "inactive"
