"""Pure credit rules (§7.1). No I/O, no clock: every input is passed in, so each rule is unit-tested directly."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    resets_at: datetime


class Admission(StrEnum):
    ADMIT = "admit"
    EXHAUSTED = "exhausted"   # nothing left this window
    CONTENDED = "contended"   # something left, but already reserved by calls in flight


def window_bounds(now: datetime, window_hours: int) -> Window:
    """Fixed UTC windows aligned to midnight (00/06/12/18 for 6h). `window_hours` divides 24 (checked in config)."""
    if now.tzinfo is None:
        raise ValueError("window_bounds needs a timezone-aware datetime")
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(hours=(now.hour // window_hours) * window_hours)
    return Window(start=start, resets_at=start + timedelta(hours=window_hours))


def remaining(limit: int, used: int) -> int:
    return max(0, limit - used)


def decide_admission(limit: int, used: int, in_flight: int, max_call_tokens: int) -> Admission:
    """Admit only if this call fits after reserving `max_call_tokens` for each call already in flight.

    Overshoot is bounded by one call: a call is admitted only while something remains, and every admitted
    call's worst case was reserved before the next one could start.
    """
    left = remaining(limit, used)
    if left <= 0:
        return Admission.EXHAUSTED
    if left - in_flight * max_call_tokens <= 0:
        return Admission.CONTENDED
    return Admission.ADMIT


def retry_after_seconds(now: datetime, resets_at: datetime) -> int:
    return max(1, math.ceil((resets_at - now).total_seconds()))
