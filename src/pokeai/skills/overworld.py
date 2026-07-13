"""Reusable overworld interaction skills — the storyline 'arsenal'.

Every story part and strategy reuses these, so they're built control-aware on top
of the verified pieces: Navigator (movement/warps), the Intro screen helpers
(settle/vision via screenshots), and FireRedStateReader. The point is to tell apart:
  * the game is BUSY (printing text, a cutscene, walking the character for you) -> WAIT
  * the game is WAITING for input (a dialogue) -> advance with A
  * the player is FREE to move -> drive
so the AI never fights the game (NPCs that talk a lot, forced cutscene movement, etc).
"""
from __future__ import annotations

import random
import time

import numpy as np

from pokeai.agents.firered_intro import Intro

# Player ObjectEvent (gObjectEvents[0]). The first u32 is a flags bitfield; bit 8
# is `frozen`, which field scripts set while they force-walk the character through
# a movement-cutscene and clear when they hand control back. NOTE: a plain msgbox
# does NOT set this (it locks input via the script context, not the object), so
# `frozen` alone is not "can't move" — pair it with the dialogue-window check.
PLAYER_OBJ = 0x02036E38
_FROZEN_BIT = 1 << 8


class Overworld:
    # neighbour-offset of the target -> direction to FACE it from that neighbour
    _ADJ = [((0, 1), "UP"), ((0, -1), "DOWN"), ((-1, 0), "RIGHT"), ((1, 0), "LEFT")]
    # the three starter Poké Balls on Oak's table (verified live)
    STARTER_BALLS = [(8, 4), (9, 4), (10, 4)]

    def __init__(self, bridge, navigator, reader, dialogue_thresh: float = 185.0):
        self.b = bridge
        self.nav = navigator
        self.reader = reader
        self.screen = Intro(bridge)          # grab / wait_stable / is_keyboard / is_title
        self.dialogue_thresh = dialogue_thresh

    # --- reading the world ---
    def pos(self):
        return self.nav.vision.player_xy()

    def npcs(self):
        """Active NPC/object tiles on the current map (player excluded)."""
        return self.nav.vision.object_tiles()

    def nearest_npc(self):
        me = self.pos()
        npcs = list(self.npcs())
        if not npcs:
            return None
        return min(npcs, key=lambda t: abs(t[0] - me[0]) + abs(t[1] - me[1]))

    # --- screen / control state ---
    def dialogue_open(self, frame=None) -> bool:
        """Is a text window on screen? FireRed draws a bright cream box across the
        bottom; the plain overworld there is darker. Threshold tuned live."""
        f = frame if frame is not None else self.screen.grab()
        h, w, _ = f.shape
        box = f[int(h * 0.72):int(h * 0.96), int(w * 0.07):int(w * 0.93)]
        return float(box.mean()) > self.dialogue_thresh

    def wait_settle(self, timeout=6.0):
        return self.screen.wait_stable(timeout=timeout)

    def frozen(self) -> bool:
        """Is the player script-frozen (the game is force-walking the character
        through a movement-cutscene)? See PLAYER_OBJ note: this is NOT set during a
        plain dialogue, so it's only half of 'can't move'."""
        return bool(self.b.read_u32(PLAYER_OBJ) & _FROZEN_BIT)

    def has_control(self, frame=None) -> bool:
        """True when control is the player's right now: no dialogue window up and
        the game isn't force-walking the character. The single 'ready to move'
        check the whole arsenal leans on."""
        f = frame if frame is not None else self.screen.grab()
        return not self.dialogue_open(f) and not self.frozen()

    @staticmethod
    def _same(a, b, tol: float = 3.0) -> bool:
        """Two frames are effectively identical (only a blinking ▼ differs)."""
        if a is None or b is None or a.shape != b.shape:
            return False
        return float(np.abs(a.astype("int16") - b.astype("int16")).mean()) < tol

    def _terminal_box(self) -> bool:
        """A dialogue window is up but pressing A doesn't change anything — Oak's
        'Which one will you choose for yourself?' and other scripts leave their last
        box on screen AFTER handing control back. So: box that A can't dismiss +
        not frozen == the script has ended and control is ours, box or no box."""
        a = self.screen.grab()
        self.b.tap("A", 6)
        time.sleep(0.25)
        b = self.screen.wait_stable()
        return self._same(a, b)

    def wait_control(self, timeout=25.0, confirm=2) -> bool:
        """Ride out whatever the game is doing until control returns to the player.
        Reliable cutscene/dialogue terminator handling the three real cases:
          * force-walk cutscene -> `frozen` set -> wait;
          * blocking dialogue -> a text window A actually advances -> press A;
          * control returned -> no window, OR a window A can't dismiss (a script's
            last box that lingers, like Oak's starter prompt).
        Control is only declared after `confirm` consecutive 'ours' reads."""
        t0 = time.time()
        clear = 0
        while time.time() - t0 < timeout:
            f = self.screen.wait_stable()
            if self.frozen():
                clear = 0
                time.sleep(0.15)
                continue
            if not self.dialogue_open(f):
                clear += 1
            elif self._terminal_box():     # box A can't dismiss -> control is back
                clear += 1
            else:                          # real dialogue advanced -> keep riding
                clear = 0
                continue
            if clear >= confirm:
                return True
            time.sleep(0.15)
        return False

    # --- dialogue ---
    def advance_dialogue(self, cap=60) -> bool:
        """Press A through a conversation, settle-based, until the dialogue window
        closes. Reusable for any NPC / sign / item / event text."""
        for _ in range(cap):
            f = self.screen.wait_stable()
            if not self.dialogue_open(f):
                return True
            self.b.tap("A", 6)
            time.sleep(0.15)
        return False

    def walk_until_event(self, direction, max_steps=12) -> str:
        """Walk one tile at a time until the game interrupts — a dialogue opens or it
        starts moving the character itself (a triggered event / cutscene) — or we run
        out of steps. Returns 'event', 'blocked', or 'done'. Reusable for any "walk
        into a trigger" (the Oak intercept, gate guards, scripted encounters)."""
        for _ in range(max_steps):
            before = self.pos()
            self.b.press_direction_settle(direction)
            time.sleep(0.1)
            if self.dialogue_open():
                return "event"
            if self.pos() == before:
                self.screen.wait_stable(timeout=1.5)
                if self.dialogue_open() or self.pos() != before:
                    return "event"
                return "blocked"
        return "done"

    def ride_cutscene(self, timeout=40.0) -> bool:
        """Ride out a multi-phase cutscene (the game alternates dialogue and walking
        the character for you) until control returns. Thin alias over wait_control,
        which now handles the alternation directly. Reusable for every scripted
        story event."""
        return self.wait_control(timeout=timeout)

    def ride_to_control(self, timeout=150.0, step_dirs=("DOWN", "UP")) -> bool:
        """Ride any scripted scene until the player can actually MOVE — the one
        ground truth the lab proved unfakeable (2026-07-02): wait_control's
        frame-compare false-negatives in NPC-dense rooms (idle animations), and
        dialogue_open's brightness check false-positives on bright floors near
        the lab door. A registered step lies about neither. Movement is tested
        FIRST each round (a direction press during a real dialogue/cutscene is a
        harmless no-op); otherwise A advances whatever is on screen. Side
        effect: takes one step when control returns — navigate right after."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            for d in step_dirs:
                if self.b.press_direction_settle(d):
                    return True
            self.b.tap("A", 6)
            time.sleep(0.3)
        return False

    # --- interaction ---
    def interact(self, target, rounds=6) -> bool:
        """Walk to a tile next to `target`, face it, press A, and advance the
        resulting dialogue. Reusable for NPCs, signs, the PC, items, Poké Balls.

        Robust to a script still holding movement (e.g. Oak's lingering starter
        prompt): if no neighbour can be reached, navigation success itself is the
        ground-truth 'do I have control yet' test — advance any dialogue and retry
        until the path opens, rather than giving up on the first blocked step."""
        tx, ty = target
        for _ in range(rounds):
            me = self.pos()
            cands = [((tx + dx, ty + dy), d) for (dx, dy), d in self._ADJ]
            cands = [(nb, d) for nb, d in cands if nb == me or self.nav.vision.walkable(*nb)]
            cands.sort(key=lambda c: abs(c[0][0] - me[0]) + abs(c[0][1] - me[1]))
            for nb, facing in cands:
                if nb != me and not self.nav.go_to(nb):
                    continue
                self.b.press_button_held(facing, 12)   # turn to face the target
                time.sleep(0.15)
                self.b.tap("A", 6)
                time.sleep(0.25)
                if self.dialogue_open():
                    return self.advance_dialogue()
            # couldn't reach / A didn't take: a script may hold movement — advance it and retry
            if self.dialogue_open():
                self.b.tap("A", 6)
                time.sleep(0.2)
            self.screen.wait_stable()
        return False

    def pick_starter(self, ball=None, nickname="CLAW") -> int:
        """In Oak's lab: ride his intro to control (the lingering 'Which one will
        you choose for yourself?' box is handled by wait_control), walk to a starter
        ball (random if not given — viewers will vote via a Twitch bot later),
        confirm it, and answer FireRed's nickname prompt by naming it `nickname`
        (uppercase; reuses the verified intro keyboard). Stops before the rival
        cutscene. Returns the committed species id (0 on failure). Reusable for any
        'choose from a set of balls' scene."""
        # movement ground truth, NOT wait_control: Oak's multi-page lab speech +
        # four idle-animating NPCs starved the frame-compare for 180s (2026-07-02)
        self.ride_to_control(timeout=180)
        target = ball or random.choice(self.STARTER_BALLS)
        stand = (target[0], target[1] + 1)               # face the ball from below
        # Nav to the ball. If go_to fails it's because Oak's script re-froze the
        # player (the lingering 'choose!' box keeps dialogue_open True, so the OLD
        # fallback pressed A here — which RE-triggers "Go on, choose!" and re-
        # freezes: a deadlock, 2026-07-02). Instead: when blocked, re-clear the
        # freeze with the movement ground truth, never blind-A near no ball.
        for _ in range(8):
            if self.pos() == stand or self.nav.go_to(stand):
                break
            if self.frozen():
                self.ride_to_control(timeout=30)          # A-mash only while frozen
            else:
                self.screen.wait_stable()
        self.b.press_button_held("UP", 12)               # turn to face the ball
        time.sleep(0.2)
        for _ in range(12):
            if self.reader.read().party_count >= 1:       # YES committed it
                break
            self.b.tap("A", 6)                            # open -> "This is X" -> YES/NO -> YES
            time.sleep(0.45)
            self.screen.wait_stable()
        if self.reader.read().party_count < 1:
            return 0
        species = self.reader.read_species(0)
        # FireRed then prompts to nickname it: advance "received X!" + YES (default
        # cursor) opens the naming keyboard; type the nickname and confirm.
        if nickname and self.screen.advance_until(self.screen.is_keyboard, cap=15) is not None:
            self.screen.type_name(nickname.upper())
            self.screen.confirm()
            self.wait_settle()
        return species
