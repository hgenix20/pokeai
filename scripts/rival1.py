"""First rival battle (GROK, Oak's lab). Walk toward the lab door — GROK's
scripted challenge fires — then fight by settle-based A-mash (FIGHT is the
default cursor; first move = Tackle), narrating both HP bars from RAM.

Battle detection v1: gEnemyParty slot 0 (0x0202402C, directly before the
verified gPlayerParty at +600) gains a valid lv1-100 mon with HP > 0 when the
battle engine loads GROK's starter. Win = money +$80. On a white-out, reload
slot 1 and try again (fresh RNG). Verified live before promotion to a skill."""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import (
    GPLAYER_PARTY,
    SLOT_CURHP_OFF,
    SLOT_LEVEL_OFF,
    SLOT_MAXHP_OFF,
    FireRedStateReader,
)
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOT1 = ROOT + r"\states\slots\slot_1.state"
OUT = ROOT + r"\states\bizhawk"

GENEMY_PARTY = 0x0202402C     # gEnemyParty (FireRed BPRE): +600 = gPlayerParty
PRIZE = 80                    # walkthrough: BATTLE: Rival [Grok] | starter (lv5) | $80


def enemy_stats(b):
    lvl = b.read_byte(GENEMY_PARTY + SLOT_LEVEL_OFF)
    hp = b.read_u16(GENEMY_PARTY + SLOT_CURHP_OFF)
    mx = b.read_u16(GENEMY_PARTY + SLOT_MAXHP_OFF)
    return lvl, hp, mx


def my_stats(b):
    lvl = b.read_byte(GPLAYER_PARTY + SLOT_LEVEL_OFF)
    hp = b.read_u16(GPLAYER_PARTY + SLOT_CURHP_OFF)
    mx = b.read_u16(GPLAYER_PARTY + SLOT_MAXHP_OFF)
    return lvl, hp, mx


def in_battle(b) -> bool:
    lvl, hp, mx = enemy_stats(b)
    return 1 <= lvl <= 100 and 0 < hp <= mx <= 999


def ride_scene_to_control(b, ow, timeout=150.0) -> str:
    """Ride out the post-starter scripted scene (GROK claiming his ball) until
    the player can actually MOVE — ground truth borrowed from starter_commit's
    backout_to_control, because frame-compare control checks false-negative in
    this NPC-dense room (idle animations). Returns 'control'|'battle'|'timeout'."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if in_battle(b):
            return "battle"
        if ow.dialogue_open():
            b.tap("A", 6)
            time.sleep(0.35)
            continue
        # no dialogue up: a real step proves control (no-ops while script-frozen)
        if b.press_direction_settle("DOWN") or b.press_direction_settle("UP"):
            return "control"
        b.tap("A", 6)
        time.sleep(0.3)
    return "timeout"


def trigger_battle(b, ow, nav) -> bool:
    """Walk toward the lab door until GROK's challenge fires and the battle
    engine loads his mon."""
    warps = nav.map_warps_full()
    door = max(warps, key=lambda w: w["y"]) if warps else None
    print(f"  door warp: {door}", flush=True)
    for round_ in range(8):
        if in_battle(b):
            return True
        if ow.dialogue_open():                 # GROK is talking — ride it in
            b.tap("A", 6)
            time.sleep(0.3)
            continue
        # step toward the door; the trigger interrupts en route
        if door:
            nav.go_to((door["x"], door["y"] - 1))
        res = ow.walk_until_event("down", max_steps=6)
        print(f"  walk round {round_}: {res} pos={ow.pos()}", flush=True)
        time.sleep(0.3)
    # last chance: ride any open dialogue until the engine loads the enemy
    for _ in range(40):
        if in_battle(b):
            return True
        b.tap("A", 6)
        time.sleep(0.4)
    return in_battle(b)


def fight(b, ow) -> str:
    """A-mash the battle to a verdict: 'win' | 'lose' | 'stuck'."""
    last = ""
    for _ in range(400):                       # ~4 min hard cap
        elvl, ehp, emx = enemy_stats(b)
        mlvl, mhp, mmx = my_stats(b)
        line = f"CLAW lv{mlvl} {mhp}/{mmx}  vs  GROK's lv{elvl} {ehp}/{emx}"
        if line != last:
            print("  " + line, flush=True)
            last = line
        if ehp == 0:
            return "win"
        if mhp == 0:
            return "lose"
        b.tap("A", 6)
        time.sleep(0.5)
    return "stuck"


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)

    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)

    saved_ready = False
    for attempt in range(1, 7):
        money0 = reader.read_money()
        print(f"attempt {attempt}: map={nav.current_map()} pos={ow.pos()} "
              f"money={money0}", flush=True)

        print("riding out any scripted scene…", flush=True)
        state = ride_scene_to_control(b, ow)
        print(f"  scene -> {state} pos={ow.pos()}", flush=True)
        if state == "timeout":
            print("never got control — needs a look.", flush=True)
            b.screenshot(OUT + r"\rival1_noctrl.png")
            b.close()
            return 1
        if state == "control" and not saved_ready:
            # overwrite slot 1 at walk-ready so retries skip the scene
            b.save_state(SLOT1)
            saved_ready = True
            print("  slot 1 re-saved at walk-ready.", flush=True)

        print("walking toward the door — GROK should stop me…", flush=True)
        if state != "battle" and not trigger_battle(b, ow, nav):
            print("battle never started — needs a look.", flush=True)
            b.screenshot(OUT + r"\rival1_notrigger.png")
            b.close()
            return 1
        elvl, ehp, emx = enemy_stats(b)
        print(f"BATTLE ON — enemy lv{elvl} {ehp}/{emx}", flush=True)
        b.screenshot(OUT + r"\rival1_battle.png")

        verdict = fight(b, ow)
        print(f"verdict: {verdict}", flush=True)
        b.screenshot(OUT + r"\rival1_end.png")

        if verdict == "win":
            # ride out exp/level-up/GROK's exit until control, then check money
            print("riding post-battle dialogue…", flush=True)
            for _ in range(60):
                if ow.has_control() and not ow.frozen():
                    break
                b.tap("A", 6)
                time.sleep(0.4)
            money1 = reader.read_money()
            mlvl, mhp, mmx = my_stats(b)
            print(f"after: money={money1} (delta {money1 - money0:+d}) "
                  f"CLAW lv{mlvl} {mhp}/{mmx} map={nav.current_map()} "
                  f"pos={ow.pos()}", flush=True)
            b.screenshot(OUT + r"\rival1_after.png")
            b.close()
            return 0

        if verdict == "lose":
            print("white-out — reloading slot 1 for a fresh try…", flush=True)
            for _ in range(20):                # ride the white-out text first
                b.tap("A", 6)
                time.sleep(0.4)
            b.load_state(SLOT1)
            time.sleep(1.5)
            continue

        print("battle stuck — needs a look.", flush=True)
        b.close()
        return 1

    print("lost 6 attempts — needs a look at strategy.", flush=True)
    b.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
