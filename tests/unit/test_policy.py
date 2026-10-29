"""Pure credit rules (§7.1): window boundaries and the admission decision."""

from datetime import UTC, datetime

import pytest

from app.modules.credits.policy import Admission, decide_admission, retry_after_seconds, window_bounds


def at(day: int, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 10, day, h, m, s, tzinfo=UTC)


@pytest.mark.parametrize(("now", "start", "resets_at"), [
    (at(29, 5, 59, 59), at(29, 0), at(29, 6)),
    (at(29, 6), at(29, 6), at(29, 12)),
    (at(29, 23, 59, 59), at(29, 18), at(30, 0)),   # resets at the next day's midnight
    (at(30, 0), at(30, 0), at(30, 6)),
])
def test_window_bounds(now: datetime, start: datetime, resets_at: datetime) -> None:
    w = window_bounds(now, 6)
    assert (w.start, w.resets_at) == (start, resets_at)


@pytest.mark.parametrize(("used", "in_flight", "expected"), [
    (0, 0, Admission.ADMIT),
    (195_000, 0, Admission.ADMIT),        # little left, nothing in flight: one call may overshoot
    (195_000, 1, Admission.CONTENDED),    # the rest is reserved by a call in flight
    (200_000, 0, Admission.EXHAUSTED),
    (202_000, 0, Admission.EXHAUSTED),
])
def test_decide_admission(used: int, in_flight: int, expected: Admission) -> None:
    assert decide_admission(200_000, used, in_flight, 15_000) is expected


def test_retry_after_rounds_up() -> None:
    assert retry_after_seconds(at(29, 11, 59, 59).replace(microsecond=500_000), at(29, 12)) == 1
