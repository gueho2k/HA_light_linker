"""Self-calibration of motion sensors.

Motion sensors differ a lot: a Hue sensor reports "motion" for a few seconds and
reports again as soon as somebody moves, an IKEA or Lidl sensor keeps "motion"
for one to three minutes and is blind in between. Light Linker watches every
sensor it uses and learns two figures:

hold_s   How long the sensor keeps "motion" at least (its built-in run-on).
         Taken as the lower quartile of the measured on-periods.
gap_s    How long it shows "no motion" while somebody is still there (the
         short pauses between two detections). Taken as the 80th percentile
         of pauses shorter than GAP_LIMIT_S.

The run-on of a motion link ("off without motion after X") counts from the last
motion. The sensor itself already waited hold_s, so the timer after "no motion"
is X - hold_s, but never shorter than gap_s (otherwise the light would go off in
the normal pauses of a sensor that is blind for a while).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.util import dt as dt_util

SAMPLES = 40
MIN_ON_SAMPLES = 5
MIN_GAP_SAMPLES = 3
GAP_LIMIT_S = 600  # a longer pause means the room was empty
MIN_RUNOUT_S = 5
STATS_SAVE_S = 300


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


class SensorCalibration:
    """Learned behaviour of all motion sensors (persisted in the link store)."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any], save: Any) -> None:
        """Initialize from stored data {entity_id: {"on": [...], "gap": [...]}}."""
        self.hass = hass
        self._save = save
        self._on: dict[str, deque[float]] = {}
        self._gap: dict[str, deque[float]] = {}
        for entity_id, raw in (data or {}).items():
            self._on[entity_id] = deque((float(x) for x in raw.get("on", [])), maxlen=SAMPLES)
            self._gap[entity_id] = deque((float(x) for x in raw.get("gap", [])), maxlen=SAMPLES)
        # entity -> (state, since) of the running period
        self._since: dict[str, tuple[str, float]] = {}

    @callback
    def observe(self, old: State | None, new: State) -> None:
        """A sensor changed state."""
        entity_id = new.entity_id
        now = dt_util.utcnow().timestamp()
        previous = self._since.get(entity_id)
        if new.state not in (STATE_ON, STATE_OFF):
            self._since.pop(entity_id, None)  # unavailable: start over
            return
        self._since[entity_id] = (new.state, now)
        if previous is None or old is None or old.state == new.state:
            return
        state, since = previous
        if state != old.state:
            return
        duration = now - since
        if old.state == STATE_ON and new.state == STATE_OFF:
            self._on.setdefault(entity_id, deque(maxlen=SAMPLES)).append(round(duration, 1))
            self._save()
        elif old.state == STATE_OFF and new.state == STATE_ON and duration <= GAP_LIMIT_S:
            self._gap.setdefault(entity_id, deque(maxlen=SAMPLES)).append(round(duration, 1))
            self._save()

    def info(self, entity_id: str) -> dict[str, Any]:
        """What has been learned about one sensor."""
        on = list(self._on.get(entity_id, ()))
        gap = list(self._gap.get(entity_id, ()))
        return {
            "samples": len(on),
            "hold_s": round(_quantile(on, 0.25)) if len(on) >= MIN_ON_SAMPLES else None,
            "gap_s": round(_quantile(gap, 0.8)) if len(gap) >= MIN_GAP_SAMPLES else None,
            "needed": MIN_ON_SAMPLES,
        }

    def runout(self, sensors: list[str], wanted_s: int) -> tuple[int, dict[str, Any]]:
        """Timer after "no motion" for a wanted run-on counted from the last motion.

        With several sensors the room is empty only when all are clear, so the
        sensor with the longest hold counts, the longest gap sets the floor.
        """
        infos = [self.info(e) for e in sensors]
        holds = [i["hold_s"] for i in infos if i["hold_s"] is not None]
        gaps = [i["gap_s"] for i in infos if i["gap_s"] is not None]
        if not holds:
            return wanted_s, {"calibrated": False}
        hold = max(holds)
        floor = max([MIN_RUNOUT_S, *gaps])
        timer = max(wanted_s - hold, floor) if wanted_s > 0 else 0
        return int(timer), {
            "calibrated": True,
            "hold_s": hold,
            "gap_s": max(gaps) if gaps else None,
            "timer_s": int(timer),
            "earliest_s": int(hold + (floor if wanted_s > 0 else 0)),
        }

    def as_data(self) -> dict[str, Any]:
        """For the store."""
        keys = set(self._on) | set(self._gap)
        return {
            k: {"on": list(self._on.get(k, ())), "gap": list(self._gap.get(k, ()))}
            for k in sorted(keys)
        }
