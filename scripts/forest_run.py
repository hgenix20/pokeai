"""G7 ACCEPTANCE: Viridian -> Route 2 -> Viridian Forest -> Pewter City.

From slot 9 (party of 6, full HP, 8 balls): travel NORTH through the gate
buildings and the forest. Trainer battles (sight-triggered) are fought with
fight_smart (type-scored moves via the Gen-3 chart, potions when low); wild
battles are fled; a blackout (whiteout warp back to the Viridian Center)
is logged and the journey resumes - that IS the recovery path.

PASS = reach Pewter City + heal at its Center (door discovered inline and
printed for services.py). Saves slot 3 = "Pewter Center". Map ids logged at
every transition (Route 2 / gates / forest ids get recorded for the roots).
stream.py STOPPED. Run in background; expect 20-40 min.
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.agents.field_brain import flee_or_fight
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
VIRIDIAN, PEWTER = (3, 1), (3, 2)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def flood_north(nav):
    delta = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    g = nav.vision.nav_grid()
    walk = g["walk"] - nav.vision.object_tiles()
    ledge_dir = g.get("ledge_dir", {})
    start = nav.vision.player_xy()
    seen = {start}
    q = deque([start])
    best = start
    while q:
        x, y = q.popleft()
        if y < best[1] or (y == best[1] and abs(x - start[0]) < abs(best[0] - start[0])):
            best = (x, y)
        for name, (dx, dy) in delta.items():
            nxt = (x + dx, y + dy)
            if ledge_dir.get(nxt) == name:
                land = (x + 2 * dx, y + 2 * dy)
                if land in walk and land not in seen:
                    seen.add(land)
                    q.append(land)
            elif nxt in walk and nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return None if best == start else best


def warp_navigate_north(b, nav, ow) -> bool:
    """In a warp-connected map (gate building OR the forest): exit via the
    NORTHMOST warp. Greedy edge-flooding dead-ends in the forest maze (live
    2026-07-05: the top-right pocket at (28,5) is walled off from the real NW
    exit); the warp table gives the exit deterministically."""
    cur = nav.current_map()
    warps = nav.map_warps_full()
    if not warps:
        return False
    w = min(warps, key=lambda t: (t["y"], t["x"]))
    say(f"  exiting {cur} via warp ({w['x']},{w['y']}) -> "
        f"({w['destGroup']},{w['destMap']})")
    for nb, push in (((w["x"], w["y"] + 1), "UP"),
                     ((w["x"] - 1, w["y"]), "RIGHT"),
                     ((w["x"] + 1, w["y"]), "LEFT"),
                     ((w["x"], w["y"] - 1), "DOWN")):
        if not nav.vision.walkable(*nb):
            continue
        if not nav.go_to(nb, attempts=10):
            continue        # battles/blocks surface on the next outer loop
        if nav.take_warp((w["x"], w["y"])) is not None or nav.current_map() != cur:
            ow.wait_control(10)
            return True
        b.press_button_held(push, 32)
        time.sleep(1.0)
        if nav.current_map() != cur:
            ow.wait_control(10)
            return True
    return nav.current_map() != cur


def main() -> int:
    b = BizHawkBridge(timeout=300)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    battle = Battle(b, reader)
    catch = Catch(b, battle)
    svc = Services(b, nav, ow, reader)

    if "--resume" in sys.argv:
        say("resuming from the LIVE state (no slot load)")
    else:
        if not b.load_state(SLOTS + r"\slot_9.state"):
            say("FAIL slot 9")
            return 1
        time.sleep(1.2)
    d = reader.read_party_details()
    say(f"start map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"party {len(d)} hp {[(m['hp'], m['max_hp']) for m in d]} "
        f"potions {reader.count_heal_items()} money {reader.read_money()}")

    trainer_wins = 0
    losses = 0
    flees = 0
    visited = []
    last_map = None
    deadline = time.time() + 2400
    stuck_at, stuck_n = None, 0

    while time.time() < deadline:
        m = nav.current_map()
        if m != last_map:
            say(f"MAP {m} (pos {nav.vision.player_xy()})")
            visited.append(m)
            last_map = m
        if m == PEWTER:
            say("PEWTER CITY REACHED")
            break

        if reader.read().all_party_fainted:
            say("BLACKOUT - riding the whiteout back to the Center")
            battle.ride_out_end(button="A", cap=80)
            losses += 1
            continue

        if battle.active() and catch.confirm_real_battle():
            if battle.is_trainer_battle():
                say("TRAINER battle!")
                res = battle.fight_smart(narrate=say)
                say(f"trainer battle -> {res}")
                if res == "win":
                    trainer_wins += 1
                elif res == "lose":
                    losses += 1
            else:
                r = flee_or_fight(b, battle, catch)
                flees += 1
                say(f"wild battle -> {r}")
            continue

        # position-freeze wedge breaker
        pos_now = nav.vision.player_xy()
        stuck_n = stuck_n + 1 if pos_now == stuck_at else 0
        stuck_at = pos_now
        if stuck_n >= 3:
            say(f"position frozen at {pos_now} - resolving")
            catch._ride_out_lead_faint()
            stuck_n = 0
            continue

        if m[0] != 3:
            # gates AND the forest are warp-connected: exit by warp table
            if not warp_navigate_north(b, nav, ow):
                say("  warp exit failed; retrying")
            continue

        px, py = nav.vision.player_xy()
        if py <= 1:
            for _ in range(4):
                b.press_direction_settle("UP")
            continue
        target = flood_north(nav)
        if not target:
            p0 = b.player_xy()
            b.press_direction_settle("LEFT")
            if b.player_xy() == p0:
                b.press_direction_settle("RIGHT")
            continue
        path = nav.plan(target)
        if not path:
            b.press_direction_settle("RIGHT")
            continue
        nav.walk_path(path)
    else:
        say(f"TIMEOUT - maps visited: {visited}")
        b.screenshot(OUT + r"\forest_timeout.png")
        return 1

    say(f"journey: maps {visited}; trainer wins {trainer_wins}, "
        f"losses {losses}, wild flees {flees}")
    d = reader.read_party_details()
    say(f"party hp {[(m['hp'], m['max_hp']) for m in d]} "
        f"levels {[m['level'] for m in d]}")

    # --- Pewter Center: discover the door, heal, record the row ---
    say("finding the Pewter Center…")
    center = None
    for w in nav.map_warps_full():
        wx, wy = w["x"], w["y"]
        if not nav.go_to((wx, wy + 1), attempts=8):
            continue
        dest = nav.take_warp((wx, wy))
        if dest is None or nav.current_map() == PEWTER:
            continue
        interior = nav.current_map()
        ow.wait_control(10)
        g = nav.vision.nav_grid()
        npcs = sorted(nav.vision.object_tiles())
        say(f"  interior {interior} {g['w']}x{g['h']} npcs {npcs}")
        if g["w"] == 15 and any(t[1] <= 2 for t in npcs):
            nurse = min(npcs, key=lambda t: (t[1], abs(t[0] - g["w"] // 2)))
            stand = (nurse[0], nurse[1] + 2)
            healed = svc.heal_here(nurse, stand=stand)
            s = reader.read()
            say(f"  heal -> {healed} (HP {s.party_total_hp}/{s.party_total_max_hp})")
            if healed:
                center = {"map": interior, "door": (wx, wy),
                          "nurse": nurse, "stand": stand}
                break
        nav.leave_building()
        ow.wait_control(10)

    b.screenshot(OUT + r"\forest_done.png")
    if not center:
        say("PARTIAL: Pewter reached but its Center was not confirmed")
        return 2
    say(f"CENTERS row for services.py: {PEWTER}: {center}")
    if b.save_state(SLOTS + r"\slot_3.state"):
        meta = json.load(open(SLOTS + r"\slot_9.json", encoding="utf-8"))
        meta.update(n=3, summary="Pewter City, healed at the Center (G7)",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + r"\slot_3.json", "w", encoding="utf-8"))
        say("saved slot 3 = Pewter Center")
    say(f"PASS - Pewter reached; {trainer_wins} trainer wins, {losses} losses recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
