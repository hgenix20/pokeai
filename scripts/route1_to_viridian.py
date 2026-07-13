"""G2 traversal: Route 1 south edge (slot 3) -> Viridian City, PLANNER-DRIVEN.

v2 (2026-07-03): the v1 greedy walker paced visibly on stream and got nowhere.
This version uses the real stack: FireRedVision.nav_grid (ledge/grass-aware,
bulk-read) + Navigator BFS. Loop: plan to the northmost REACHABLE tile, walk;
a wild battle interrupts the walk -> FLEE (fight if fleeing fails) -> replan.
NPCs near the path get one interact + SaveBlock1 bag diff (free-Potion hunt).
At the top row, push UP across the connection. Saves slot 4 in Viridian.

Run with stream.py STOPPED (I bind 51055; ai_bridge.lua reconnects ~8s).
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.overworld import Overworld

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
SB1_PTR, SB2_PTR = 0x03005008, 0x0300500C
ROUTE1 = (3, 19)
DUMP_LEN = 0x700


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sb1_dump(b) -> bytes:
    out = bytearray()
    for off in range(0, DUMP_LEN, 0x100):
        p = b.read_u32(SB1_PTR)
        out += bytes(b.read_range(p + off, p + off + 0x100))
    return bytes(out)


def moved(b, d="LEFT") -> bool:
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_battle(b, battle) -> bool:
    if not battle.active():
        return False
    return not (moved(b, "LEFT") or moved(b, "RIGHT"))


def flee_or_fight(b, battle) -> str:
    for _ in range(4):
        for _ in range(2):
            b.tap("B", 6)
            time.sleep(0.35)
        b.tap("RIGHT", 6)
        time.sleep(0.3)
        b.tap("DOWN", 6)
        time.sleep(0.3)
        b.tap("A", 6)
        time.sleep(0.6)
        for _ in range(4):
            b.tap("B", 6)
            time.sleep(0.35)
        if not in_battle(b, battle):
            return "fled"
    verdict = battle.fight()
    for _ in range(15):
        b.tap("A", 6)
        time.sleep(0.35)
    return verdict


def reachable_northmost(nav, grid) -> tuple[int, int] | None:
    """BFS flood from the player over the walk set; return the reachable tile
    with the smallest y (ties: closest x to the player)."""
    start = nav.vision.player_xy()
    walk = grid["walk"] - nav.vision.object_tiles()
    seen = {start}
    q = deque([start])
    best = start
    while q:
        x, y = q.popleft()
        if y < best[1] or (y == best[1] and abs(x - start[0]) < abs(best[0] - start[0])):
            best = (x, y)
        for nx, ny in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
            if (nx, ny) in walk and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    return None if best == start else best


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    battle = Battle(b)

    say("loading slot 3…")
    if not b.load_state(SLOTS + r"\slot_3.state"):
        say("FAIL: slot load")
        return 1
    time.sleep(1.0)
    key16 = b.read_u32(b.read_u32(SB2_PTR) + 0xF20) & 0xFFFF
    say(f"start map {nav.current_map()} local {nav.vision.player_xy()}")
    bag0 = sb1_dump(b)
    interacted: set[tuple[int, int]] = set()
    flees = fights = 0

    deadline = time.time() + 480
    while time.time() < deadline:
        if nav.current_map() != ROUTE1:
            break
        if reader.read().all_party_fainted:
            say("BLACKOUT — aborting")
            return 1
        if battle.active() and in_battle(b, battle):
            r = flee_or_fight(b, battle)
            flees, fights = flees + (r == "fled"), fights + (r != "fled")
            say(f"battle -> {r} (CLAW {battle.my_stats()})")
            continue

        # talk to any new NPC within reach; diff the bag (free-Potion hunt)
        px, py = nav.vision.player_xy()
        for t in sorted(nav.vision.object_tiles(),
                        key=lambda t: abs(t[0] - px) + abs(t[1] - py)):
            if t in interacted or abs(t[0] - px) + abs(t[1] - py) > 4:
                continue
            interacted.add(t)
            say(f"npc at {t} — talking…")
            try:
                ow.interact(t)
                ow.wait_control(12)
            except Exception as e:
                say(f"  interact issue: {type(e).__name__}")
            bag1 = sb1_dump(b)
            d = [(i, int.from_bytes(bag0[i:i+2], "little"),
                  int.from_bytes(bag1[i:i+2], "little")) for i in range(0, DUMP_LEN, 2)
                 if bag0[i:i+2] != bag1[i:i+2]]
            if d:
                say(f"  BAG DELTA ({len(d)} u16s):")
                for off, was, now in d[:10]:
                    say(f"    SB1+{off:#05x}: {was:#06x}->{now:#06x}"
                        f" (qty^key {was ^ key16}->{now ^ key16})")
                bag0 = bag1
            break

        grid = nav.vision.nav_grid()
        px, py = nav.vision.player_xy()
        if py <= 1:
            say("at the top row — pushing UP across the connection")
            for _ in range(4):
                b.press_direction_settle("UP")
            continue
        target = reachable_northmost(nav, grid)
        if not target:
            say(f"no reachable progress from {px, py} — nudging")
            moved(b, "LEFT") or moved(b, "RIGHT")
            continue
        say(f"plan: {px, py} -> {target}")
        path = nav.plan(target)
        if not path:
            say("  no path (transient block?) — nudging")
            moved(b, "RIGHT")
            continue
        ok = nav.walk_path(path)
        if not ok:
            say(f"  walk interrupted at {nav.vision.player_xy()}"
                f" (battle={battle.active()})")

    m = nav.current_map()
    s = reader.read()
    say(f"END map {m} local {nav.vision.player_xy()} money {s.money}"
        f" CLAW {battle.my_stats()} flees={flees} fights={fights}"
        f" npcs={len(interacted)}")
    if m != ROUTE1:
        say(f"VIRIDIAN REACHED — map id {m}")
        if b.save_state(SLOTS + r"\slot_4.state"):
            with open(SLOTS + r"\slot_3.json", encoding="utf-8") as f:
                meta = json.load(f)
            meta.update(n=4, summary="Viridian City south entrance",
                        ts=time.strftime("%Y-%m-%d %H:%M"))
            with open(SLOTS + r"\slot_4.json", "w", encoding="utf-8") as f:
                json.dump(meta, f)
            say("saved slot 4 = Viridian City south entrance")
        return 0
    say("did not leave Route 1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
