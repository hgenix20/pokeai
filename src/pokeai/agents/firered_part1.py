"""Part 1 of the storyline — Pallet Town start.

Walkthrough: downstairs, talk to Mom -> north toward the grass, Oak
intercepts -> Oak's lab, pick a starter (nicknamed; FireRed DOES prompt
right after the "received" message - verified 2026-06-17) -> GROK's rival
battle on the way out -> exit the lab and head north to Route 1.

The starter choice and both names are hardcoded for now; the walkthrough's
[[Feature]] tags make them operator-input/viewer-poll seams (FIXLIST
player-rival-naming-feature-missing / starter-nickname-feature-missing).
The bedroom-PC Potion step is still missing (FIXLIST pc-potion-step-skipped).

Built entirely from the reusable arsenal (Overworld skill + Navigator) so the
same moves serve later parts; every step was verified on the real game
(the rival battle logic is the live-verified scripts/rival1.py port).
"""
from __future__ import annotations

import time

from pokeai.emulator.firered_state_reader import (
    GPLAYER_PARTY,
    SLOT_CURHP_OFF,
    SLOT_LEVEL_OFF,
    SLOT_MAXHP_OFF,
)

GENEMY_PARTY = 0x0202402C     # gEnemyParty (BPRE): +600 = gPlayerParty

# FireRed internal species ids (match National Dex for the original 151)
_STARTER_NAMES = {1: "Bulbasaur", 4: "Charmander", 7: "Squirtle"}
ROUTE1 = (3, 19)


def _enemy_stats(b):
    return (b.read_byte(GENEMY_PARTY + SLOT_LEVEL_OFF),
            b.read_u16(GENEMY_PARTY + SLOT_CURHP_OFF),
            b.read_u16(GENEMY_PARTY + SLOT_MAXHP_OFF))


def _my_stats(b):
    return (b.read_byte(GPLAYER_PARTY + SLOT_LEVEL_OFF),
            b.read_u16(GPLAYER_PARTY + SLOT_CURHP_OFF),
            b.read_u16(GPLAYER_PARTY + SLOT_MAXHP_OFF))


def _in_battle(b) -> bool:
    lvl, hp, mx = _enemy_stats(b)
    return 1 <= lvl <= 100 and 0 < hp <= mx <= 999


def _ride_scene_to_control(b, ow, timeout=150.0) -> str:
    """Ride the post-starter scripted scene (GROK claiming his ball) until
    the player can MOVE; a real settle-step is the ground truth (frame-
    compare control checks false-negative in this NPC-dense room).
    Returns 'control' | 'battle' | 'timeout'. (scripts/rival1.py port.)"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _in_battle(b):
            return "battle"
        if ow.dialogue_open():
            b.tap("A", 6)
            time.sleep(0.35)
            continue
        if b.press_direction_settle("DOWN") or b.press_direction_settle("UP"):
            return "control"
        b.tap("A", 6)
        time.sleep(0.3)
    return "timeout"


def _trigger_rival(b, ow, nav) -> bool:
    """Walk toward the lab door until GROK's challenge fires."""
    warps = nav.map_warps_full()
    door = max(warps, key=lambda w: w["y"]) if warps else None
    for _ in range(8):
        if _in_battle(b):
            return True
        if ow.dialogue_open():
            b.tap("A", 6)
            time.sleep(0.3)
            continue
        if door:
            nav.go_to((door["x"], door["y"] - 1))
        ow.walk_until_event("down", max_steps=6)
        time.sleep(0.3)
    for _ in range(40):
        if _in_battle(b):
            return True
        b.tap("A", 6)
        time.sleep(0.4)
    return _in_battle(b)


def _fight_rival(b) -> str:
    """A-mash to a verdict (lv5 mirror match; FIGHT is the default cursor).
    Returns 'win' | 'lose' | 'stuck'."""
    for _ in range(400):
        _, ehp, _ = _enemy_stats(b)
        _, mhp, _ = _my_stats(b)
        if ehp == 0:
            return "win"
        if mhp == 0:
            return "lose"
        b.tap("A", 6)
        time.sleep(0.5)
    return "stuck"


class _NoHooks:
    def phase(self, task_id, action): ...
    def done_task(self, task_id): ...


def run_part1(ow, nav, skill, hooks=None) -> bool:
    """Drive Part 1. `ow`=Overworld skills, `nav`=Navigator, `skill`=NavigateTo
    (map-edge traversal). `hooks` (the dashboard) is notified at each step for the
    quest log + narration. Returns True if the wired steps completed."""
    h = hooks or _NoHooks()

    # we're resuming post-intro: roll the intro quests off the board
    for t in ("name_self", "name_rival", "enter_world"):
        h.done_task(t)

    # --- Step 1: downstairs and talk to Mom ---
    h.phase("p1_mom", "Heading downstairs to see Mom")
    warps = nav.map_warps()                 # the bedroom's only warp = the stairs
    if warps:
        nav.take_warp(warps[0])             # -> Player's house 1F
    ow.wait_control()                        # let the warp/step animation finish
    h.phase("p1_mom", "Saying bye to Mom")
    mom = ow.nearest_npc()                    # 1F has one NPC: Mom
    if mom:
        ow.interact(mom)                      # walk to her, face, A, advance dialogue
    ow.wait_control()
    h.done_task("p1_mom")

    # --- Step 2: out the door, north across Pallet, Oak intercepts -> his lab ---
    h.phase("p1_oak", "Heading out the door into Pallet Town")
    nav.leave_building()                       # exit the house to Pallet Town
    ow.wait_control()
    h.phase("p1_oak", "Heading north — Prof. Oak stops me at the grass")
    # navigate AROUND the house and north toward the grass (straight up just
    # re-enters the house); the Oak intercept fires en route and walks me to the lab
    skill.overworld_exit("north")
    ow.ride_cutscene()                         # finish any remaining Oak dialogue
    h.done_task("p1_oak")

    # --- Step 3: in Oak's lab, pick a starter (RANDOM; viewers vote later) ---
    h.phase("starter", "In Oak's lab — Prof. Oak offers three Poké Balls")
    species = ow.pick_starter(nickname="CLAW")  # rides Oak's intro, walks to a ball, confirms, names it
    if species:
        name = _STARTER_NAMES.get(species, "a starter")
        h.phase("starter", f"Chose {name}, nicknamed CLAW! (party has 1 Pokémon)")
        h.done_task("starter")
    else:
        h.phase("starter", "Couldn't confirm a starter — needs a look")
        return False

    # --- Step 4: GROK's challenge on the way out (FIXLIST FL-6 port) ---
    b = nav.emu
    h.phase("rival1", "GROK wants a battle before I can leave!")
    state = _ride_scene_to_control(b, ow)
    if state != "battle" and not _trigger_rival(b, ow, nav):
        h.phase("rival1", "GROK's battle never started — needs a look")
        return False
    h.phase("rival1", "Battling GROK's starter!")
    verdict = _fight_rival(b)
    if verdict == "win":
        for _ in range(60):                    # ride exp/level-up/GROK's exit
            if ow.has_control() and not ow.frozen():
                break
            b.tap("A", 6)
            time.sleep(0.4)
        h.phase("rival1", "Beat GROK's starter!")
        h.done_task("rival1")
    elif verdict == "lose":
        # LOSABLE by design (FRLG): white-out -> home, healed, story intact,
        # GROK never re-challenges. Ride the white-out text until control
        # and continue - a loss is honest content, not a failure.
        h.phase("rival1", "Lost to GROK — waking up at home, shaking it off")
        for _ in range(80):
            if ow.has_control() and not ow.frozen():
                break
            b.tap("A", 6)
            time.sleep(0.4)
        ow.wait_control()
        h.done_task("rival1")
    else:
        h.phase("rival1", "Battle stuck — needs a look")
        return False

    # --- Step 5: out of whatever building, north across Pallet to Route 1 ---
    h.phase("route1", "Exit the lab, head north to Route 1")
    for _ in range(3):                         # lab after a win; HOME after a loss
        if nav.current_map()[0] == 3:          # already outdoors
            break
        nav.leave_building()
        ow.wait_control()
    for _ in range(4):
        if nav.current_map() == ROUTE1:
            break
        skill.overworld_exit("north")
        ow.wait_control()
    if nav.current_map() == ROUTE1:
        h.phase("route1", "Route 1 — the adventure is on!")
        h.done_task("route1")
    else:
        h.phase("route1", "Didn't reach Route 1 — needs a look")
        return False

    return True
