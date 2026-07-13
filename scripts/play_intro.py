"""Closed-loop automation of the FireRed new-game intro: title -> NEW GAME ->
help -> Oak intro -> name player CLAUDE -> name rival GROK -> bedroom.

TRIGGER-BASED, not timer-based (the game has load/print/transition delays, so
blind mashing desyncs). Core idea: after every input, WAIT until the screen
settles (stops changing) before the next input, and decide what to press from
what's actually on screen / in RAM:
  * wait_stable() polls screenshots until the frame stops changing (text done /
    transition done), skipping black transition frames.
  * advance() presses A only on a settled screen; if A doesn't change anything
    (e.g. we're on the title, which needs START), it presses START instead — so
    boot + help + dialogue + menus are all handled by one paced loop.
  * the name keyboard is detected by its orange OK/legend buttons (verified ~331
    orange px in the right region vs a >60 threshold); typing uses the verified
    deterministic cursor moves; confirm = START (settle) then A (settle).
  * the overworld is detected by reading the live map (bedroom = (4,1)).
Saves checkpoints to states/bizhawk/intro_*.png.
"""
from __future__ import annotations

import sys
import time

import numpy as np
from PIL import Image

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import (
    GSAVEBLOCK1_PTR, SB1_MAP_GROUP_OFF, SB1_MAP_NUM_OFF,
)

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"
SCAN = OUT + r"\_scan.png"

# Absolute (col,row) of each letter on the verified contiguous 4x7 keyboard.
GRID = {c: (i % 7, i // 7) for i, c in enumerate(
    ["A", "B", "C", "D", "E", "F", ".",
     "G", "H", "I", "J", "K", "L", ",",
     "M", "N", "O", "P", "Q", "R", "S",
     "T", "U", "V", "W", "X", "Y", "Z"])}


class Intro:
    def __init__(self, b: BizHawkBridge):
        self.b = b

    # --- vision / triggers ---
    def grab(self) -> np.ndarray:
        self.b.screenshot(SCAN)
        return np.asarray(Image.open(SCAN).convert("RGB"), dtype=np.int16)

    @staticmethod
    def is_black(a) -> bool:
        return a.mean() < 14

    @staticmethod
    def _orange(a, x0, x1, y0=0.30, y1=0.95) -> int:
        h, w, _ = a.shape
        reg = a[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        r, g, bl = reg[..., 0], reg[..., 1], reg[..., 2]
        return int(((r > 175) & (g > 70) & (g < 190) & (bl < 120) & ((r - bl) > 85)).sum())

    @staticmethod
    def is_keyboard(a) -> bool:
        # keyboard: orange OK/legend buttons on the FAR right, and NO big orange
        # block in the center (that's the title's Charizard). Calibrated live.
        return Intro._orange(a, 0.88, 1.0) > 60 and Intro._orange(a, 0.30, 0.70) < 30

    def wait_stable(self, timeout=7.0, thresh=3.5, need=2) -> np.ndarray:
        """Poll until the frame stops changing for `need` polls (text/transition
        done), skipping black frames. Returns the settled frame (or last on timeout)."""
        t0 = time.time()
        prev = self.grab()
        stable = 0
        while time.time() - t0 < timeout:
            time.sleep(0.2)
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

    def shot(self, tag):
        p = f"{OUT}\\intro_{tag}.png"
        self.b.screenshot(p)
        print(f"  checkpoint: {p}", flush=True)

    # --- driving ---
    def advance_until(self, pred, cap=90):
        """Settle, then if pred not met press A (or START if A changes nothing),
        and settle again. Never presses on an unsettled screen."""
        f = self.wait_stable()
        for _ in range(cap):
            if pred(f):
                return f
            before = f
            self.b.tap("A", 6)
            time.sleep(0.1)
            f = self.wait_stable()
            if np.abs(f - before).mean() < 3.5:   # A did nothing -> needs START (title etc.)
                self.b.tap("START", 6)
                time.sleep(0.1)
                f = self.wait_stable()
        return f if pred(f) else None

    def type_name(self, name):
        """Coordinate-based: track the cursor (keyboard opens on 'A'=(0,0)) and
        walk to each letter's absolute grid cell, so it's correct for ANY name."""
        cx, cy = 0, 0
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

    def confirm(self):
        """START moves cursor to OK, A confirms; settle between, retry while still
        on the keyboard. Settling (not a fixed delay) is what makes START register."""
        for _ in range(4):
            self.b.tap("START", 8)
            self.wait_stable(timeout=2.5)
            self.b.tap("A", 8)
            f = self.wait_stable(timeout=2.5)
            if not self.is_keyboard(f):
                return True
        return False


def main() -> int:
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge.lua…", flush=True)
    b.wait_for_bizhawk()
    print("ping:", b.ping(), flush=True)
    g = Intro(b)

    print("driving to the player name keyboard…", flush=True)
    if g.advance_until(g.is_keyboard) is None:
        g.shot("fail_player_kbd"); print("FAIL: no player keyboard"); b.close(); return 1
    g.shot("kbd_player")
    print("typing CLAUDE…", flush=True)
    g.type_name("CLAUDE")
    g.shot("typed_claude")
    g.confirm()

    print("driving to the rival name keyboard…", flush=True)
    if g.advance_until(g.is_keyboard) is None:
        g.shot("fail_rival_kbd"); print("FAIL: no rival keyboard"); b.close(); return 1
    g.shot("kbd_rival")
    print("typing GROK…", flush=True)
    g.type_name("GROK")
    g.shot("typed_grok")
    g.confirm()

    print("driving to the overworld…", flush=True)
    g.advance_until(lambda _f: g.cur_map() == (4, 1))
    g.shot("overworld")
    m = g.cur_map()
    print(f"current_map={m} reached_bedroom={m == (4, 1)}", flush=True)
    b.close()
    return 0 if m == (4, 1) else 1


if __name__ == "__main__":
    sys.exit(main())
