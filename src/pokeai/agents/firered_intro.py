"""Trigger-based driver for the FireRed new-game intro (title -> name CLAUDE ->
name GROK -> bedroom), reusable by both the standalone script and the stream
dashboard.

Pacing is by GAME STATE, never fixed timers: after each input we wait until the
screen stops changing (wait_stable), and decide the next press from what's on
screen / in RAM. The scratch screenshot is a single rolling temp file (no file
accumulation).
"""
from __future__ import annotations

import os
import tempfile
import time

import numpy as np
from PIL import Image

from pokeai.emulator.firered_state_reader import (
    GSAVEBLOCK1_PTR, SB1_MAP_GROUP_OFF, SB1_MAP_NUM_OFF,
)

# Absolute (col,row) of each cell on the verified contiguous 4x7 keyboard.
GRID = {c: (i % 7, i // 7) for i, c in enumerate(
    ["A", "B", "C", "D", "E", "F", ".",
     "G", "H", "I", "J", "K", "L", ",",
     "M", "N", "O", "P", "Q", "R", "S",
     "T", "U", "V", "W", "X", "Y", "Z"])}

_SCRATCH = os.path.join(tempfile.gettempdir(), "pokeai_scan.png")


class StopRun(Exception):
    """Raised through the controlled bridge to abort a run cleanly."""


class Intro:
    def __init__(self, bridge, scratch: str = _SCRATCH):
        self.b = bridge
        self.scratch = scratch
        self.tick = None  # optional per-loop callback (e.g. refresh live stats)

    # --- vision / triggers ---
    def grab(self) -> np.ndarray:
        # client.screenshot can occasionally leave a partial/locked file; retry a
        # few times before giving up instead of crashing the whole run.
        last = None
        for _ in range(4):
            self.b.screenshot(self.scratch, wait=0.5)
            try:
                return np.asarray(Image.open(self.scratch).convert("RGB"), dtype=np.int16)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.12)
        raise last

    @staticmethod
    def is_black(a) -> bool:
        return a.mean() < 14

    @staticmethod
    def _orange(a, x0, x1, y0=0.30, y1=0.95) -> int:
        h, w, _ = a.shape
        r = a[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        rr, gg, bb = r[..., 0], r[..., 1], r[..., 2]
        return int(((rr > 175) & (gg > 70) & (gg < 190) & (bb < 120) & ((rr - bb) > 85)).sum())

    @staticmethod
    def is_keyboard(a) -> bool:
        # orange OK/legend buttons on the FAR right, and NO big center orange
        # block (that's the title's Charizard). Calibrated live.
        return Intro._orange(a, 0.88, 1.0) > 60 and Intro._orange(a, 0.30, 0.70) < 30

    @staticmethod
    def is_title(a) -> bool:
        # the Charizard title has a big ORANGE block in the CENTRE (help/copyright/
        # Oak screens don't), so START is pressed ONLY here — not as a blind fallback,
        # which is what made it oscillate A<->START.
        return Intro._orange(a, 0.30, 0.70) > 120

    def wait_stable(self, timeout=7.0, thresh=3.5, need=2) -> np.ndarray:
        t0 = time.time()
        prev = self.grab()
        stable = 0
        while time.time() - t0 < timeout:
            time.sleep(0.3)
            cur = self.grab()
            if self.is_black(cur):
                stable = 0
                prev = cur
                continue
            if np.abs(cur - prev).mean() < thresh:
                stable += 1
                if stable >= need:
                    return cur
            else:
                stable = 0
            prev = cur
        return prev

    def cur_map(self):
        sb1 = self.b.read_u32(GSAVEBLOCK1_PTR)
        return self.b.read_byte(sb1 + SB1_MAP_GROUP_OFF), self.b.read_byte(sb1 + SB1_MAP_NUM_OFF)

    # --- driving ---
    def advance_until(self, pred, cap=120):
        f = self.wait_stable()
        for _ in range(cap):
            if self.tick:
                self.tick()
            if pred(f):
                return f
            # START only on the real title; advance everything else with A — always
            # AFTER the screen has settled (wait_stable), so we react to the game
            # instead of mashing. No A<->START oscillation.
            if self.is_title(f):
                self.b.tap("START", 6)
            else:
                self.b.tap("A", 6)
            time.sleep(0.1)
            f = self.wait_stable()
        return f if pred(f) else None

    def type_name(self, name):
        cx, cy = 0, 0  # keyboard opens on 'A'
        for ch in name:
            tx, ty = GRID[ch]
            for _ in range(tx - cx):
                self.b.tap("RIGHT", 6); time.sleep(0.22)
            for _ in range(cx - tx):
                self.b.tap("LEFT", 6); time.sleep(0.22)
            for _ in range(ty - cy):
                self.b.tap("DOWN", 6); time.sleep(0.22)
            for _ in range(cy - ty):
                self.b.tap("UP", 6); time.sleep(0.22)
            self.b.tap("A", 6); time.sleep(0.35)
            cx, cy = tx, ty


class _NoHooks:
    def phase(self, task_id, action): ...
    def done_task(self, task_id): ...
    def typed(self, name): ...


def run_intro(intro: Intro, hooks=None) -> bool:
    """Drive the whole intro. `hooks` (optional) is notified at phase boundaries
    so a UI can show progress. Returns True if we land in the bedroom (4,1)."""
    h = hooks or _NoHooks()

    h.phase("name_self", "Booting up a brand-new adventure")
    if intro.advance_until(intro.is_keyboard) is None:
        raise RuntimeError("never reached the player name keyboard")
    h.phase("name_self", "Spelling out my name on the keyboard: CLAUDE")
    intro.type_name("CLAUDE")
    intro.confirm()
    h.typed("CLAUDE")
    h.done_task("name_self")

    h.phase("name_rival", "Meeting my lifelong rival")
    if intro.advance_until(intro.is_keyboard) is None:
        raise RuntimeError("never reached the rival name keyboard")
    h.phase("name_rival", "Giving my rival his name: GROK")
    intro.type_name("GROK")
    intro.confirm()
    h.typed("GROK")
    h.done_task("name_rival")

    h.phase("enter_world", "Stepping out into the world")
    intro.advance_until(lambda _f: intro.cur_map() == (4, 1))
    ok = intro.cur_map() == (4, 1)
    if ok:
        h.done_task("enter_world")
    return ok


# confirm() lives on Intro but is defined here to keep the keyboard logic together.
def _confirm(self):
    """START walks the cursor to OK, A confirms; settle between so the laggy
    START registers; retry while still on the keyboard."""
    for _ in range(4):
        self.b.tap("START", 10)
        self.wait_stable(timeout=2.5)
        self.b.tap("A", 8)
        f = self.wait_stable(timeout=2.5)
        if not self.is_keyboard(f):
            return True
    return False


Intro.confirm = _confirm
