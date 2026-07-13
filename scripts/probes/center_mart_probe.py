"""G5 probe: discover the Viridian Pokemon Center door + nurse/stand tiles, then
live-test Services.buy_at_mart (5 Poke Balls, money+bag RAM verification).

From slot 5 (Viridian, Oak's Parcel in bag -> the Mart clerk SELLS now... note:
slot 5 predates delivery, so the clerk may still be in parcel mode; if the buy
fails here it is retried in the field run from a post-delivery state).

Center discovery: enumerate the city's warps, skip the five known interiors
((5,0) house, (5,1) gym, (5,2) school, (5,3) mart, (5,4) house), enter the
unknown one(s); a Pokemon Center is identified by its interior layout (NPC
behind a counter near the top-center). Prints the CENTERS row to hardcode in
services.py. Screenshots at each stage. stream.py STOPPED.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
KNOWN_DOORS = {(25, 11), (36, 10), (25, 18), (36, 19), (26, 26)}
VIRIDIAN = (3, 1)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    svc = Services(b, nav, ow, reader)

    if not b.load_state(SLOTS + r"\slot_5.state"):
        say("FAIL slot load")
        return 1
    time.sleep(1.0)
    say(f"map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"money {reader.read_money()} balls {reader.ball_count()}")
    if nav.current_map() != VIRIDIAN:
        say("FAIL: not in Viridian")
        return 1

    # ---- Center discovery ----
    warps = nav.map_warps_full()
    say(f"{len(warps)} warps on the city map")
    center = None
    for w in warps:
        wx, wy = (w["x"], w["y"]) if isinstance(w, dict) else (w[0], w[1])
        if (wx, wy) in KNOWN_DOORS:
            continue
        say(f"candidate door ({wx},{wy}) — approaching…")
        if not nav.go_to((wx, wy + 1)):
            say("  unreachable; skipping")
            continue
        dest = nav.take_warp((wx, wy))
        if dest is None or nav.current_map() == VIRIDIAN:
            b.press_button_held("UP", 32)
            time.sleep(1.0)
        if nav.current_map() == VIRIDIAN:
            say("  did not enter; skipping")
            continue
        interior = nav.current_map()
        ow.wait_control(10)
        npcs = sorted(nav.vision.object_tiles())
        grid = nav.vision.nav_grid()
        say(f"  interior map {interior} size {grid['w']}x{grid['h']} npcs {npcs}")
        b.screenshot(OUT + rf"\cmp_interior_{interior[0]}_{interior[1]}.png")
        # nurse heuristic: the NPC closest to top-center
        if npcs:
            cx = grid["w"] // 2
            nurse = min(npcs, key=lambda t: (t[1], abs(t[0] - cx)))
            stand = (nurse[0], nurse[1] + 2)
            say(f"  nurse guess {nurse}, stand {stand} "
                f"(walkable={nav.vision.walkable(*stand)})")
            say(f"  trying counter-talk heal…")
            healed = svc.heal_here(nurse, stand=stand)
            s = reader.read()
            say(f"  heal_here -> {healed} (HP {s.party_total_hp}/{s.party_total_max_hp})")
            b.screenshot(OUT + rf"\cmp_heal_{interior[0]}_{interior[1]}.png")
            if healed:
                center = {"map": interior, "door": (wx, wy),
                          "nurse": nurse, "stand": stand}
        say("  leaving…")
        nav.leave_building()
        ow.wait_control(10)
        if center:
            break
    if center:
        say(f"CENTER ROW for services.py: {VIRIDIAN}: {center}")
    else:
        say("NO CENTER CONFIRMED — check screenshots")

    # ---- Mart buy test ----
    say("testing buy_at_mart (5 Poke Balls)…")
    balls0 = reader.ball_count()
    res = svc.buy_at_mart(qty=5, slot=0, city_map=VIRIDIAN)
    b.screenshot(OUT + r"\cmp_buy_result.png")
    say(f"buy_at_mart -> {res} (balls {balls0} -> {reader.ball_count()})")

    ok = bool(center) and res.get("ok")
    say("PROBE PASS" if ok else "PROBE PARTIAL — see notes above")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
