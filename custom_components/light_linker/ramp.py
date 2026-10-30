"""Dimming ramps while a button is held.

Three ways, chosen per binding (mode) and per lamp:

native      One Zigbee "move" command with a rate, one "stop" at the end.
            Zigbee2MQTT: brightness_move over MQTT; ZHA: Level Control move/stop
            through zha.issue_zigbee_cluster_command / issue_zigbee_group_command.
transition  light.turn_on to the limit with a transition; at the end the
            brightness reached so far is set (estimated from the elapsed time).
steps       brightness_step_pct every interval_ms, like most Node-RED ramps.

auto = native where the lamp allows it, steps for all others.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON
from homeassistant.core import Context, HomeAssistant, callback

from . import z2m
from .const import DOMAIN, Z2M_BASE_TOPIC

if TYPE_CHECKING:
    from .engine import Engine
    from .models import Link

_LOGGER = logging.getLogger(__name__)

ZHA_LEVEL_CLUSTER = 8
ZHA_CMD_MOVE = 1
ZHA_CMD_STOP = 3


def brightness_pct(hass: HomeAssistant, lights: list[str]) -> int:
    """Average brightness of the lamps that are on; 0 if all are off."""
    values = []
    for entity_id in lights:
        state = hass.states.get(entity_id)
        if state and state.state == STATE_ON:
            values.append(round((state.attributes.get("brightness") or 255) * 100 / 255))
    return round(sum(values) / len(values)) if values else 0


class Ramp:
    """One running ramp of one binding."""

    def __init__(
        self,
        engine: Engine,
        link: Link,
        params: dict[str, Any],
        lights: list[str],
        direction: str,
        context: Context,
    ) -> None:
        """Initialize."""
        self.engine = engine
        self.hass = engine.hass
        self.link = link
        self.params = params
        self.lights = lights
        self.direction = direction
        self.context = context
        self.started = 0.0
        self.start_pct = 0
        self.done = False
        self._native: list[dict[str, Any]] = []
        self._transition: list[str] = []
        self._steps: list[str] = []
        self._steps_task: asyncio.Task[None] | None = None
        self._limit_handle: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------- planning

    def _plan(self) -> None:
        mode = self.params["mode"]
        if mode == "transition":
            self._transition = list(self.lights)
            return
        if mode == "steps":
            self._steps = list(self.lights)
            return
        rest = list(self.lights)
        # one Zigbee2MQTT group for all lamps if there is one
        if (found := self.engine.z2m.group_for(rest)) and (
            target := z2m.native_target(self.hass, self.engine.z2m, found[0])
        ) and self._stack_ready("z2m"):
            self._native.append(target)
            rest = []
        for entity_id in rest:
            target = z2m.native_target(self.hass, self.engine.z2m, entity_id)
            if target and self._stack_ready(target["stack"]):
                self._native.append({**target, "entity_id": entity_id})
            else:
                self._steps.append(entity_id)

    def _stack_ready(self, stack: str) -> bool:
        if stack == "z2m":
            return "mqtt" in self.hass.config.components
        return self.hass.services.has_service("zha", "issue_zigbee_cluster_command")

    @property
    def rate(self) -> int:
        """Zigbee level units (0-254) per second."""
        return max(1, min(254, round(254 / self.params["duration_s"])))

    # ---------------------------------------------------------------- start

    async def async_start(self) -> bool:
        """Start; False if there is nothing to do."""
        params = self.params
        current = brightness_pct(self.hass, self.lights)
        if current == 0:
            if params["when_off"] == "ignore":
                return False
            # off: always come up from the lower limit
            self.direction = "up"
            await self.engine.async_light_on(
                self.link, self.lights, {"brightness_pct": params["min_pct"], "transition": 0}, self.context
            )
            current = params["min_pct"]
        if self.direction == "up" and current >= params["max_pct"]:
            return False
        if self.direction == "down" and current <= params["min_pct"]:
            return False
        self.start_pct = current
        self.started = time.monotonic()
        self._plan()
        _LOGGER.debug(
            "%s: ramp %s from %s%% native=%s transition=%s steps=%s",
            self.link.name, self.direction, current, len(self._native), self._transition, self._steps,
        )
        limit = params["max_pct"] if self.direction == "up" else params["min_pct"]
        seconds = abs(limit - current) / 100 * params["duration_s"]
        for target in self._native:
            await self._native_move(target)
        if self._transition:
            await self.engine.async_light_on(
                self.link, self._transition,
                {"brightness_pct": limit, "transition": round(seconds, 1)}, self.context,
            )
        if self._steps:
            self._steps_task = self.engine.entry.async_create_background_task(
                self.hass, self._steps_loop(), f"{DOMAIN} ramp {self.link.name}"
            )
        if self._native:
            # stop at the limit (the lamp itself would go on to 1 % or 100 %)
            self._limit_handle = self.hass.loop.call_later(seconds, self._at_limit)
        return True

    @callback
    def _at_limit(self) -> None:
        self._limit_handle = None
        self.hass.async_create_task(self.async_stop(), eager_start=True)

    # ----------------------------------------------------------------- stop

    async def async_stop(self) -> None:
        """End the ramp where it is."""
        if self.done:
            return
        self.done = True
        if self._limit_handle:
            self._limit_handle.cancel()
            self._limit_handle = None
        if self._steps_task:
            self._steps_task.cancel()
            self._steps_task = None
        for target in self._native:
            await self._native_stop(target)
        if self._transition:
            await self.engine.async_light_on(
                self.link, self._transition,
                {"brightness_pct": self.estimate(), "transition": 0}, self.context,
            )
        if self._native:
            self.hass.loop.call_later(0.4, self._refresh)

    def estimate(self) -> int:
        """Brightness reached so far (by time)."""
        params = self.params
        moved = (time.monotonic() - self.started) / params["duration_s"] * 100
        value = self.start_pct + moved if self.direction == "up" else self.start_pct - moved
        return int(max(params["min_pct"], min(params["max_pct"], round(value))))

    # ---------------------------------------------------------------- steps

    async def _steps_loop(self) -> None:
        params = self.params
        interval = params["interval_ms"] / 1000
        step = max(1, round(100 * interval / params["duration_s"]))
        while True:
            current = brightness_pct(self.hass, self._steps)
            if self.direction == "up":
                if current >= params["max_pct"]:
                    return
                if current + step >= params["max_pct"]:
                    data = {"brightness_pct": params["max_pct"], "transition": interval}
                else:
                    data = {"brightness_step_pct": step, "transition": interval}
            else:
                if current - step <= params["min_pct"]:
                    self.engine.fire_light_on(self._steps, {"brightness_pct": params["min_pct"]}, self.context)
                    return
                data = {"brightness_step_pct": -step, "transition": interval}
            self.engine.fire_light_on(self._steps, data, self.context)
            await asyncio.sleep(interval)

    # --------------------------------------------------------------- native

    async def _native_move(self, target: dict[str, Any]) -> None:
        up = self.direction == "up"
        if target["stack"] == "z2m":
            await self._z2m_publish(target["name"], {"brightness_move": self.rate if up else -self.rate})
        else:
            await self._zha_command(target, ZHA_CMD_MOVE, [0 if up else 1, self.rate])

    async def _native_stop(self, target: dict[str, Any]) -> None:
        if target["stack"] == "z2m":
            await self._z2m_publish(target["name"], {"brightness_move": 0})
        else:
            await self._zha_command(target, ZHA_CMD_STOP, [])

    async def _z2m_publish(self, name: str, payload: dict[str, Any], what: str = "set") -> None:
        from homeassistant.components import mqtt  # noqa: PLC0415

        try:
            await mqtt.async_publish(self.hass, f"{Z2M_BASE_TOPIC}/{name}/{what}", json.dumps(payload))
        except Exception as err:  # noqa: BLE001 - never let a ramp crash the engine
            _LOGGER.warning("%s: MQTT publish to %s failed: %s", self.link.name, name, err)

    async def _zha_command(self, target: dict[str, Any], command: int, args: list[int]) -> None:
        try:
            if "group" in target:
                await self.hass.services.async_call(
                    "zha", "issue_zigbee_group_command",
                    {
                        "group": target["group"], "cluster_id": ZHA_LEVEL_CLUSTER,
                        "cluster_type": "in", "command": command, "args": args,
                    },
                    blocking=True, context=self.context,
                )
            else:
                params = {"move_mode": args[0], "rate": args[1]} if command == ZHA_CMD_MOVE else {}
                await self.hass.services.async_call(
                    "zha", "issue_zigbee_cluster_command",
                    {
                        "ieee": target["ieee"], "endpoint_id": target["endpoint"],
                        "cluster_id": ZHA_LEVEL_CLUSTER, "cluster_type": "in",
                        "command": command, "command_type": "server", "params": params,
                    },
                    blocking=True, context=self.context,
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: ZHA level command failed: %s", self.link.name, err)

    @callback
    def _refresh(self) -> None:
        """Native moves do not report the end level by themselves: ask for it."""
        zha_entities = []
        for target in self._native:
            if target["stack"] == "z2m":
                for name in target.get("members") or [target["name"]]:
                    self.hass.async_create_task(
                        self._z2m_publish(name, {"brightness": "", "state": ""}, "get"), eager_start=True
                    )
            elif "entity_id" in target:
                zha_entities.append(target["entity_id"])
        if zha_entities:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "homeassistant", "update_entity", {"entity_id": zha_entities}, blocking=False
                ),
                eager_start=True,
            )
