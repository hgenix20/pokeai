"""G8 prep: GRIND the Viridian Forest until CLAW can face Brock.

From slot 3 (Pewter Center, party 6 healed): walk back into the forest,
serpentine-sweep the floor FIGHTING every wild (fight_smart - XP, no flees)
and crossing the remaining Bug Catcher sight lines (Rick/Doug - the G7
caveat). Heal trips go BACK to the Pewter Center (closer than Viridian's)
whenever the party is low; a blackout is ridden out and the sweep resumes
(exercising the recovery path). Exit when CLAW (slot 0) reaches TARGET_LEVEL:
return to Pewter, heal, save slot 3. stream.py STOPPED; 30-60 min.
"""
from __future__ import annotations

import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import CENTERS, Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
PEWTER, ROUTE2, FOREST = (3, 2), (3, 20), (1, 0)
GATE_N = (15, 3)
TARGET_LEVEL = 11
# Pewter Center (live-confirmed by forest_run 2026-07-05)
PEWTER_CENTER = {"map": (6, 5), "door": (17, 25), "nurse": (7, 2), "stand": (7, 4)}
CENTERS.setdefault(PEWTER, PEWTER_CENTER)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def warp_toward(b, nav, ow, pick) -> bool:
    """Exit the current warp-connected map via the warp chosen by `pick`.

    Multi-tile doormats have DUD tiles (the 7/2 Pallet-door lesson, re-hit
    live at the forest north gate: (6,10)/(8,10) dead, (7,10) real): try every
    warp on the picked mat row, CENTER tile first, approaching from the map
    interior and pushing outward."""
    cur = nav.current_map()
    warps = nav.map_warps_full()
    if not warps:
        return False
    w0 = pick(warps)
    row = [w for w in warps if abs(w["y"] - w0["y"]) <= 1]
    cx = sum(w["x"] for w in row) / len(row)
    row.sort(key=lambda w: abs(w["x"] - cx))
    g = nav.vision.nav_grid()
    outward = "DOWN" if w0["y"] >= g["h"] // 2 else "UP"
    inward_dy = -1 if outward == "DOWN" else 1
    for w in row:
        say(f"  {cur}: trying warp ({w['x']},{w['y']}) -> "
            f"({w['destGroup']},{w['destMap']})")
        nb = (w["x"], w["y"] + inward_dy)
        if nav.vision.walkable(*nb) and nav.go_to(nb, attempts=10):
            b.press_button_held(outward, 32)
            time.sleep(1.0)
            if nav.current_map() != cur:
                ow.wait_control(10)
                return True
        if nav.take_warp((w["x"], w["y"])) is not None or nav.current_map() != cur:
            ow.wait_control(10)
            return True
    return nav.current_map() != cur


def handle_battles(b, battle, catch, say_fn) -> str | None:
    """Fight any real battle to a verdict (grind mode: no fleeing)."""
    if battle.active() and catch.confirm_real_battle():
        kind = "TRAINER" if battle.is_trainer_battle() else "wild"
        res = battle.fight_smart(narrate=say_fn)
        say(f"{kind} battle -> {res}")
        return res
    return None


def go_heal_pewter(b, nav, ow, battle, catch, reader, svc) -> bool:
    """From wherever (forest/route/gate), travel to the Pewter Center + heal.
    Wild battles on the way are FLED (a battered roster fighting everything
    made heal trips take longer than the grinding); trainers can't be."""
    from pokeai.agents.field_brain import flee_or_fight
    say("heal trip to Pewter…")
    deadline = time.time() + 600
    while time.time() < deadline:
        m = nav.current_map()
        if m == PEWTER:
            ok = svc.heal_at_center(PEWTER)
            say(f"  heal_at_center -> {ok}")
            if nav.current_map() != PEWTER:
                nav.leave_building()
                ow.wait_control(10)
            return ok
        if battle.active() and catch.confirm_real_battle():
            if battle.is_trainer_battle():
                say(f"  trainer mid-heal-trip -> {battle.fight_smart(narrate=say)}")
            else:
                say(f"  wild mid-heal-trip -> {flee_or_fight(b, battle, catch)}")
            continue
        if m == FOREST or m[0] == 15:
            warp_toward(b, nav, ow, lambda ws: min(ws, key=lambda t: (t["y"], t["x"])))
        elif m[0] != 3:
            # a stray building (mis-entered en route): plain exit, not warps
            if nav.leave_building() is None:
                for _ in range(8):
                    p0 = b.player_xy()
                    b.press_direction_settle("DOWN")
                    if b.player_xy() != p0:
                        break
                    b.tap("B", 5)
                    time.sleep(0.4)
        elif m == ROUTE2:
            # push north to Pewter
            from collections import deque
            g = nav.vision.nav_grid()
            walk = g["walk"] - nav.vision.object_tiles()
            start = nav.vision.player_xy()
            seen, q, best = {start}, deque([start]), start
            while q:
                x, y = q.popleft()
                if y < best[1]:
                    best = (x, y)
                for nb in ((x, y-1), (x, y+1), (x-1, y), (x+1, y)):
                    if nb in walk and nb not in seen:
                        seen.add(nb)
                        q.append(nb)
            if best != start:
                nav.go_to(best, attempts=10)
            for _ in range(4):
                b.press_direction_settle("UP")
        else:
            say(f"  unexpected map {m} on the heal trip")
            return False
    return False


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

    if "--resume" not in sys.argv:
        if not b.load_state(SLOTS + r"\slot_3.state"):
            say("FAIL slot 3")
            return 1
        time.sleep(1.2)
    d = reader.read_party_details()
    say(f"start map {nav.current_map()} party levels {[m['level'] for m in d]} "
        f"hp {[(m['hp'], m['max_hp']) for m in d]} money {reader.read_money()}")

    wins = {"wild": 0, "trainer": 0}
    losses = 0
    blackouts = 0
    deadline = time.time() + 3600
    sweep_rows = list(range(46, 6, -6))
    row_i = 0
    sweep_left = True

    while time.time() < deadline:
        d = reader.read_party_details()
        lead_lvl = d[0]["level"] if d else 0
        if lead_lvl >= TARGET_LEVEL:
            say(f"TARGET: CLAW lv{lead_lvl}")
            break

        s = reader.read()
        if s.all_party_fainted:
            say("BLACKOUT - riding it out")
            battle.ride_out_end(button="A", cap=80)
            blackouts += 1
            continue
        frac = s.party_total_hp / max(s.party_total_max_hp, 1)
        lead_down = bool(d) and d[0]["hp"] == 0
        if frac < 0.35 or lead_down:
            # CLAW is the XP carrier (and the Brock answer): a heal trip when
            # he faints keeps the levels going to slot 0, not the bench
            if not go_heal_pewter(b, nav, ow, battle, catch, reader, svc):
                say("heal trip failed; continuing anyway")
            continue

        res = handle_battles(b, battle, catch, say)
        if res:
            if res == "win":
                kind = "trainer" if battle.is_trainer_battle() else "wild"
                wins[kind] += 1
            elif res == "lose":
                losses += 1
            continue

        m = nav.current_map()
        if m == PEWTER or m == ROUTE2:
            # walk back down into the forest (southmost warp/edge)
            if m == ROUTE2:
                # gate door into the forest is a warp on Route 2's south part
                if not warp_toward(b, nav, ow,
                                   lambda ws: max(ws, key=lambda t: t["y"])):
                    for _ in range(4):
                        b.press_direction_settle("DOWN")
            else:
                from collections import deque
                g = nav.vision.nav_grid()
                walk = g["walk"] - nav.vision.object_tiles()
                start = nav.vision.player_xy()
                seen, q, best = {start}, deque([start]), start
                while q:
                    x, y = q.popleft()
                    if y > best[1]:
                        best = (x, y)
                    for nb in ((x, y-1), (x, y+1), (x-1, y), (x+1, y)):
                        if nb in walk and nb not in seen:
                            seen.add(nb)
                            q.append(nb)
                if best != start:
                    nav.go_to(best, attempts=10)
                for _ in range(4):
                    b.press_direction_settle("DOWN")
            continue
        if m[0] == 15:
            # gate between: head SOUTH into the forest
            warp_toward(b, nav, ow, lambda ws: max(ws, key=lambda t: t["y"]))
            continue
        if m[0] not in (1, 3):
            # a building (the Center): doormat exits need leave_building,
            # not warp_toward (walk-through mats don't fire on take_warp)
            if nav.leave_building() is None:
                for _ in range(8):
                    p0 = b.player_xy()
                    b.press_direction_settle("DOWN")
                    if b.player_xy() != p0:
                        break
                    b.tap("B", 5)
                    time.sleep(0.4)
            continue
        if m != FOREST:
            continue

        # serpentine sweep across the forest floor (crosses sight lines)
        y = sweep_rows[row_i % len(sweep_rows)]
        x = 4 if sweep_left else 44
        say(f"sweep leg -> ({x},{y}) (CLAW lv{lead_lvl})")
        nav.go_to((x, y), attempts=14)
        row_i += 1
        sweep_left = not sweep_left
    else:
        say("TIME CAP hit")

    say(f"grind result: wins {wins}, losses {losses}, blackouts {blackouts}")
    d = reader.read_party_details()
    say(f"levels {[m['level'] for m in d]} money {reader.read_money()}")
    say("returning to Pewter to heal + save…")
    if go_heal_pewter(b, nav, ow, battle, catch, reader, svc):
        if b.save_state(SLOTS + r"\slot_3.state"):
            meta = json.load(open(SLOTS + r"\slot_3.json", encoding="utf-8"))
            meta.update(summary=f"Pewter, party leveled (CLAW lv{d[0]['level']}) pre-Brock",
                        ts=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(meta, open(SLOTS + r"\slot_3.json", "w", encoding="utf-8"))
            say("saved slot 3 = leveled pre-Brock")
        say(f"PASS - CLAW lv{d[0]['level']}, trainer wins {wins['trainer']}, "
            f"wild wins {wins['wild']}, blackouts recovered {blackouts}")
        return 0
    say("PARTIAL - grind done but the final heal failed")
    return 2


if __name__ == "__main__":
    sys.exit(main())
