"""Choice-point seam: a timed decision the operator or viewers can make for
the AI, defaulting to random on no response (FIXLIST fossil-poll-not-
implemented; Kameron's 2026-07-06 [[Feature]] on the Dome/Helix fossil).

The walkthrough tags several story moments as "let viewers choose in a timed
poll; if no responses, default to random" - the fossil is the first, the
intro names (Ash/Gary) are the same shape. This module is the ONE mechanism
those share, mirroring the B1 naming flow the doc describes: an operator
field and (when live) a viewer poll both feed the same resolution, with a
random fallback so an unattended or offline run never blocks.

Design:
  - `ChoicePoint(options)` holds a labelled option set (e.g. DOME/HELIX).
  - `resolve(poll_fn, window_s)` polls `poll_fn()` (returns a chosen option
    key or None) until it returns a choice or `window_s` elapses, then falls
    back to a uniformly random option. Returns (key, source) where source is
    "poll" or "random" - the caller logs which, honestly.
  - `poll_fn` is injected: the live wiring passes a reader over the operator
    field / a chat-poll tally; tests pass a scripted function. No network,
    no clock, no randomness at import - all injected for testability.

The random fallback uses the injected `rng` (default random.Random()); tests
pass a seeded Random for determinism. The Workflow-only ban on Math.random
does not apply here - this is real Python.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    detail: str = ""


class ChoicePoint:
    def __init__(self, options: list[Option], *,
                 rng: random.Random | None = None,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        if len(options) < 2:
            raise ValueError("a choice needs at least two options")
        self.options = options
        self._by_key = {o.key: o for o in options}
        self._rng = rng or random.Random()
        self._clock = clock
        self._sleep = sleep

    def is_option(self, key: str | None) -> bool:
        return key in self._by_key

    def resolve(self, poll_fn: Callable[[], str | None],
                window_s: float = 30.0,
                poll_interval: float = 1.0) -> tuple[str, str]:
        """Poll for a choice up to `window_s`; return (chosen_key, source).
        source = "poll" when poll_fn produced a valid option in time,
        else "random" (uniform over the options)."""
        deadline = self._clock() + window_s
        while self._clock() < deadline:
            try:
                pick = poll_fn()
            except Exception:
                pick = None
            if self.is_option(pick):
                return pick, "poll"
            self._sleep(poll_interval)
        return self._rng.choice(self.options).key, "random"


# The fossil choice, ready for the Part 4 Miguel moment.
DOME = Option("dome", "Dome Fossil", "revives into Kabuto (Rock/Water)")
HELIX = Option("helix", "Helix Fossil", "revives into Omanyte (Rock/Water)")
FOSSIL_OPTIONS = [DOME, HELIX]
