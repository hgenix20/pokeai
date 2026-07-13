"""FireRed story brain — the emulator-AGNOSTIC agent logic.

`StoryAgent` pursues ordered story objectives via collision-grid navigation;
`Explorer` is the wander-the-map fallback. Both drive through the injected
`emu` (any object with the EmulatorWrapper read+input surface: read_byte,
press_button_pulse, press_direction_settle, press_button_held, tick) plus the
verified perception stack (Navigator/FireRedVision) and the navigate_to skill.

Because they touch nothing emulator-specific, the SAME brain runs on the mGBA
wrapper or the BizHawk bridge unchanged — the "AI brain is portable" principle
(docs/FIRERED_REDESIGN.md): only the backend (mgba_wrapper <-> bizhawk_bridge)
swaps. This module was lifted out of the (discarded) Docker server
`scripts/firered_live.py` so it can be imported without mGBA/PIL present.
"""
from __future__ import annotations

import random

from pokeai.emulator.firered_state_reader import GPLAYER_PARTY_COUNT
from pokeai.perception.navigator import Navigator
from pokeai.perception.pathing import bfs_path
from pokeai.skills.navigate_to import NavigateTo

BEDROOM = (4, 1)


def vision_ascii(vision, nav, radius: int = 5) -> list[str]:
    """A player-centered ASCII collision map (# wall, . floor, P player, W warp,
    N npc) for logging/review. Tolerant of read failures (returns [])."""
    try:
        w, h, m = vision.layout()
        px, py = vision.player_xy()
    except Exception:
        return []
    warps = {(wp["x"], wp["y"]) for wp in nav.map_warps_full()}
    objs = vision.object_tiles()
    rows = []
    for dy in range(-radius, radius + 1):
        row = ""
        for dx in range(-radius, radius + 1):
            x, y = px + dx, py + dy
            if (dx, dy) == (0, 0):
                row += "P"
            elif (x, y) in warps:
                row += "W"
            elif (x, y) in objs:
                row += "N"
            elif not (0 <= x < w and 0 <= y < h):
                row += " "
            else:
                row += "#" if (vision.block_at(x, y, (w, h, m)) >> 10) & 0x3 else "."
        rows.append(row)
    return rows


class _Obj:
    def __init__(self, name, done, pursue):
        self.name, self.done, self.pursue = name, done, pursue


class StoryAgent:
    """Pursue ordered story objectives with collision-grid navigation."""

    def __init__(self, emu, nav: Navigator, skill: NavigateTo, log):
        self.emu, self.nav, self.skill, self.log = emu, nav, skill, log
        self.idx = 0
        self.thought = "starting out"
        cm = nav.current_map
        party = lambda: emu.read_byte(GPLAYER_PARTY_COUNT)
        self.objs = [
            _Obj("Leave the bedroom", lambda: cm() != BEDROOM,
                 lambda: nav.take_warp(nav.map_warps()[0]) if nav.map_warps() else None),
            _Obj("Go outside to Pallet Town", lambda: cm() == (3, 0),
                 lambda: nav.leave_building()),
            _Obj("Travel to Prof. Oak's Lab", lambda: cm() == (4, 3),
                 lambda: skill.overworld_exit("north")),
            _Obj("Receive a starter Pokemon", lambda: party() >= 1,
                 self._try_starter),
        ]
        self._stuck = 0
        self._last = None

    def _try_starter(self):
        # Walk to a starter ball and pick it (gated by FireRed's rival/Oak script;
        # honestly shown as 'in progress' until that lifts).
        for _ in range(6):
            self.emu.press_button_pulse("A", 16)

    def tasks(self) -> list[dict]:
        out = []
        for i, o in enumerate(self.objs):
            st = "done" if i < self.idx else ("active" if i == self.idx else "pending")
            out.append({"name": o.name, "status": st})
        out.append({"name": "Explore & train",
                    "status": "active" if self.idx >= len(self.objs) else "pending"})
        return out

    def step(self):
        while self.idx < len(self.objs) and self.objs[self.idx].done():
            self.log(f"objective DONE: {self.objs[self.idx].name}")
            self.idx += 1
        # stuck detection (dialogue/battle) -> advance with A
        try:
            pos = self.nav.vision.player_xy()
        except Exception:
            pos = None
        if pos is not None and pos == self._last:
            self._stuck += 1
        else:
            self._stuck = 0
        self._last = pos
        if self._stuck >= 4:
            self.emu.press_button_pulse("A", 16)
            self.thought = "clearing a message…"
            self._stuck = 0
            return
        if self.idx >= len(self.objs):
            self.thought = "story objectives complete — exploring"
            return  # caller falls back to explorer
        o = self.objs[self.idx]
        self.thought = f"goal: {o.name}"
        self.log(f"pursue: {o.name}  map={self.nav.current_map()}  pos={pos}")
        try:
            o.pursue()
        except Exception as e:
            self.emu.press_button_pulse("A", 16)
            self.thought = f"goal: {o.name} (recovering: {type(e).__name__})"


class Explorer:
    """Fallback AI: wander the current map via vision + BFS, take warps to new maps."""

    def __init__(self, emu, nav, log):
        self.emu, self.nav, self.vision, self.log = emu, nav, nav.vision, log
        self.path, self.target, self.thought = [], None, "exploring"
        self.rng = random.Random(1)
        self.visited = set()
        self._stuck, self._last = 0, None

    def tasks(self):
        return [{"name": "Free exploration", "status": "active"}]

    def step(self):
        v = self.vision
        try:
            w, h, m = v.layout()
            px, py = v.player_xy()
        except Exception:
            self.emu.press_button_pulse("A", 16)
            self.thought = "reading the screen…"
            return
        self.visited.add(self.nav.current_map())
        self._stuck = self._stuck + 1 if self._last == (px, py) else 0
        self._last = (px, py)
        if self._stuck >= 3:
            self.emu.press_button_pulse("A", 16)
            self.thought = "clearing a message…"
            self._stuck = 0
            return
        warps = {(wp["x"], wp["y"]) for wp in self.nav.map_warps_full()}
        objs = v.object_tiles()
        if not self.path:
            cands = [(x, y) for y in range(h) for x in range(w)
                     if v.walkable(x, y, (w, h, m)) and (x, y) not in warps
                     and (x, y) not in objs and (x, y) != (px, py)]
            self.rng.shuffle(cands)
            for t in cands[:25]:
                p = bfs_path((px, py), t,
                             lambda x, y: v.walkable(x, y, (w, h, m))
                             and (x, y) not in warps and (x, y) not in objs)
                if p:
                    self.path, self.target = p, t
                    self.log(f"explore path -> {t}: {p}")
                    break
        if self.path:
            self.emu.press_direction_settle(self.path.pop(0).upper())
            self.thought = f"exploring → {self.target}"
            return
        doors = self.nav.map_warps_full()
        fresh = [d for d in doors if (d["destGroup"], d["destMap"]) not in self.visited]
        pick = fresh or doors
        if pick:
            d = pick[0]
            self.thought = f"map explored — exit ({d['x']},{d['y']})"
            self.nav.take_warp((d["x"], d["y"]))
        else:
            self.emu.tick(8)
            self.thought = "nowhere new to go"
