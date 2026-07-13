"""Tests for the timed choice-point seam (agents/choice_point.py)."""
from __future__ import annotations

import random

import pytest

from pokeai.agents.choice_point import (
    FOSSIL_OPTIONS,
    ChoicePoint,
    Option,
)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _cp(**kw):
    clock = kw.pop("clock", FakeClock())
    sleeps = []

    def sleep(dt):
        sleeps.append(dt)
        clock.t += dt   # advance the fake clock so the window can expire

    cp = ChoicePoint(FOSSIL_OPTIONS, clock=clock,
                     sleep=sleep, **kw)
    return cp, clock, sleeps


def test_needs_two_options():
    with pytest.raises(ValueError):
        ChoicePoint([Option("only", "Only")])


def test_poll_choice_wins_immediately():
    cp, _, sleeps = _cp()
    key, source = cp.resolve(lambda: "helix", window_s=30.0)
    assert (key, source) == ("helix", "poll")
    assert sleeps == []   # no waiting once a valid pick arrives


def test_invalid_poll_values_ignored_until_valid():
    picks = iter([None, "garbage", "dome"])
    cp, _, _ = _cp()
    key, source = cp.resolve(lambda: next(picks, None), window_s=30.0)
    assert (key, source) == ("dome", "poll")


def test_random_fallback_on_no_response():
    cp, _, _ = _cp(rng=random.Random(0))
    key, source = cp.resolve(lambda: None, window_s=5.0, poll_interval=1.0)
    assert source == "random"
    assert key in ("dome", "helix")


def test_random_fallback_is_seeded_deterministic():
    cp1, _, _ = _cp(rng=random.Random(42))
    cp2, _, _ = _cp(rng=random.Random(42))
    k1, _ = cp1.resolve(lambda: None, window_s=5.0)
    k2, _ = cp2.resolve(lambda: None, window_s=5.0)
    assert k1 == k2


def test_poll_fn_exception_falls_through_to_random():
    def boom():
        raise RuntimeError("poll source down")
    cp, _, _ = _cp(rng=random.Random(1))
    key, source = cp.resolve(boom, window_s=3.0)
    assert source == "random"
    assert key in ("dome", "helix")


def test_window_expiry_respects_clock():
    cp, clock, sleeps = _cp()
    cp.resolve(lambda: None, window_s=10.0, poll_interval=2.0)
    # 10s window / 2s interval => ~5 sleeps before expiry
    assert 4 <= len(sleeps) <= 6
