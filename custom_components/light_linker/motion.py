"""Motion / presence links: switch on with motion, off after a run-on, hand wins."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HassJob, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_MOTION_STATE, Adapter, MotionState
from .models import Link

if TYPE_CHECKING:
    from .engine import Engine

_LOGGER = logging.getLogger(__name__)

_SWITCHED = (STATE_ON, STATE_OFF)


class MotionController:
    """State machine of one motion link.

    States: OFF (waiting for motion), AUTO (switched on by motion), RUNOUT
    (everybody left, timer running), MANUAL (someone switched by hand), BLOCKED
    (switched off by hand while occupied). Everything not caused by this
    controller - wall switch on the relay, other links, dashboard, voice - counts
    as "by hand"; that is recognised by the context of the state change.
    """

    def __init__(self, engine: Engine, link: Link) -> None:
        """Initialize."""
        self.engine = engine
        self.hass = engine.hass
        self.link = link
        self.state = MotionState.OFF
        self.timer_end: datetime | None = None
        self._timer: CALLBACK_TYPE | None = None
        self._own: deque[str] = deque(maxlen=32)
        self._unsub_targets: CALLBACK_TYPE | None = None
        self._targets: list[str] = []

    # ---------------------------------------------------------------- props

    @property
    def opts(self) -> dict[str, Any]:
        """Motion options of the link."""
        return self.link.options["motion"]

    @property
    def sensors(self) -> list[str]:
        """Occupancy sensors of the link."""
        return [s.entity_id for s in self.link.sources if s.adapter == Adapter.OCCUPANCY and s.entity_id]

    @property
    def occupied(self) -> bool:
        """At least one sensor reports occupied."""
        return any(
            (state := self.hass.states.get(e)) is not None and state.state == STATE_ON
            for e in self.sensors
        )

    def _any_target_on(self) -> bool:
        return any(
            (state := self.hass.states.get(e)) is not None and state.state == STATE_ON
            for e in self._targets
        )

    def _dark(self) -> bool:
        entity_id = self.opts["lux_entity"]
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True  # no reading: rather light than darkness
        try:
            return float(state.state) < self.opts["lux_threshold"]
        except ValueError:
            return True

    def _blocked_by_entity(self) -> bool:
        entity_id = self.opts["block_entity"]
        return bool(entity_id) and (state := self.hass.states.get(entity_id)) is not None and state.state == STATE_ON

    # ------------------------------------------------------------ lifecycle

    @callback
    def async_start(self) -> None:
        """Follow the targets; start from what is there, switch nothing."""
        self._targets = [
            e for e in self.engine.resolve_targets(self.link) if e.startswith(("light.", "switch."))
        ]
        if self._targets:
            self._unsub_targets = async_track_state_change_event(
                self.hass, self._targets, self._target_changed
            )
        self._set_state(MotionState.MANUAL if self._any_target_on() else MotionState.OFF)

    @callback
    def async_stop(self) -> None:
        """Stop following, cancel timers."""
        self._cancel_timer()
        if self._unsub_targets:
            self._unsub_targets()
            self._unsub_targets = None
        self._set_state(MotionState.INACTIVE)

    # --------------------------------------------------------------- events

    @callback
    def async_occupancy_changed(self) -> None:
        """A sensor of this link changed."""
        if self._blocked_by_entity():
            self._cancel_timer()
            return
        state = self.state
        if self.occupied:
            if state == MotionState.OFF:
                if not self.opts["only_off"] and self._dark():
                    self._switch(True, MotionState.AUTO, "motion_on")
            elif state == MotionState.RUNOUT:
                self._cancel_timer()
                self._set_state(MotionState.AUTO)
            elif state == MotionState.MANUAL:
                self._cancel_timer()
                self._notify()
            elif state == MotionState.BLOCKED and self.opts["manual_off_block"] == "until_empty":
                self._cancel_timer()
                self._notify()
            return
        # everybody left
        if state == MotionState.AUTO:
            self._start_timer(self.opts["off_delay_s"], self._auto_off)
            self._set_state(MotionState.RUNOUT)
        elif state == MotionState.MANUAL:
            if (delay := self._manual_delay()) is not None:
                self._start_timer(delay, self._manual_off)
        elif state == MotionState.BLOCKED and self.opts["manual_off_block"] == "until_empty":
            self._start_timer(self.opts["off_delay_s"], self._unblock)

    def _manual_delay(self) -> int | None:
        # "only off": light switched on by hand goes off like an automatic one
        if self.opts["only_off"]:
            return self.opts["off_delay_s"]
        return self.opts["manual_off_delay_s"]

    @callback
    def _target_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None or old.state == new.state:
            return
        if old.state not in _SWITCHED or new.state not in _SWITCHED:
            return  # (un)availability, restarts
        ctx = new.context
        if ctx.id in self._own or (ctx.parent_id and ctx.parent_id in self._own):
            return
        self._cancel_timer()
        if new.state == STATE_ON:
            # switched on by hand
            self._set_state(MotionState.MANUAL)
            if not self.occupied and (delay := self._manual_delay()) is not None:
                self._start_timer(delay, self._manual_off)
            self.engine.async_record_motion(self.link, "manual_on")
            return
        if self._any_target_on():
            return  # one of several lamps off: still manual
        # all off by hand
        self.engine.async_record_motion(self.link, "manual_off")
        if self.opts["manual_off_block"] == "timed":
            self._set_state(MotionState.BLOCKED)
            self._start_timer(self.opts["manual_off_block_s"], self._unblock)
        elif self.occupied:
            self._set_state(MotionState.BLOCKED)
        else:
            self._set_state(MotionState.OFF)

    # --------------------------------------------------------------- timers

    @callback
    def _auto_off(self) -> None:
        if self.occupied:
            self._set_state(MotionState.AUTO)
            return
        self._switch(False, MotionState.OFF, "motion_off")

    @callback
    def _manual_off(self) -> None:
        if self.occupied:
            return
        self._switch(False, MotionState.OFF, "motion_off")

    @callback
    def _unblock(self) -> None:
        self._set_state(MotionState.OFF)
        if self.occupied:
            self.async_occupancy_changed()

    def _start_timer(self, delay: float, action: Any) -> None:
        self._cancel_timer()
        self.timer_end = dt_util.utcnow() + timedelta(seconds=delay)

        @callback
        def _fire(_now: datetime) -> None:
            self._timer = None
            self.timer_end = None
            action()

        self._timer = async_call_later(self.hass, delay, HassJob(_fire, cancel_on_shutdown=True))
        self._notify()

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer()
            self._timer = None
        self.timer_end = None

    # ---------------------------------------------------------------- utils

    @callback
    def _switch(self, on: bool, new_state: MotionState, record: str) -> None:
        context = Context()
        self._own.append(context.id)
        self._set_state(new_state)
        self.engine.async_record_motion(self.link, record)
        lights = [e for e in self._targets if e.startswith("light.")]
        switches = [e for e in self._targets if e.startswith("switch.")]
        self.engine.entry.async_create_task(
            self.hass,
            self.engine.async_turn_for_motion(self.link, on, lights, switches, context),
            f"{DOMAIN} motion {self.link.name}",
        )

    def _set_state(self, state: MotionState) -> None:
        if state != self.state:
            _LOGGER.debug("%s: %s -> %s", self.link.name, self.state, state)
        self.state = state
        self._notify()

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_MOTION_STATE, self.link.id)

    def as_dict(self) -> dict[str, Any]:
        """Status for the panel and the state sensor."""
        return {
            "state": str(self.state),
            "timer_end": self.timer_end.isoformat() if self.timer_end else None,
            "occupied": self.occupied,
            "dark": self._dark(),
        }
