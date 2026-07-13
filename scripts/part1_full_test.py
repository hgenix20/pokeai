"""ACCEPTANCE TEST — the whole of Part 1 on a FRESH game, end to end:

  title -> NEW GAME -> name CLAUDE/GROK -> bedroom     (run_intro)
  -> Mom -> Oak intercept -> lab -> starter CLAW       (run_part1)
  -> GROK's ball scene -> walk to door -> RIVAL BATTLE (skills.battle)
  -> win (savestate-reload retries on a loss) -> GROK leaves -> control
  -> READY FOR ROUTE 1

Every stage gate is RAM/behavior ground truth, never narration: map ids,
party count, species, nickname bytes, money delta (+$80 prize), movement
test. Regenerates save slots 0/1/2 at the verified checkpoints as it goes.

Run me against a freshly-launched EmuHawk (title screen). I bind 51055 and
wait, so start me first, then launch EmuHawk with --lua=ai_bridge.lua."""
from __future__ import annotations

import json
import sys
import time

# Windows stdout defaults to cp1252; our narration + the win banner use é, —, ✓.
# Force UTF-8 so a redirected run doesn't UnicodeEncodeError on the final print.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.agents.firered_intro import Intro, run_intro
from pokeai.agents.firered_part1 import run_part1
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import GPLAYER_PARTY, FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.navigate_to import NavigateTo
from pokeai.skills.overworld import Overworld

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOTS = ROOT + r"\states\slots"
OUT = ROOT + r"\states\bizhawk"
SPECIES = {1: "Bulbasaur", 4: "Charmander", 7: "Squirtle"}
BATTLE_TRIES = 5


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fail(b, msg, shot):
    say(f"FAIL: {msg}")
    try:
        b.screenshot(OUT + "\\" + shot)
        say(f"  screenshot -> {shot}")
    except Exception:
        pass
    return 1


def decode_name(bs) -> str:
    out = []
    for x in bs:
        if x == 0xFF:
            break
        if 0xBB <= x <= 0xD4:
            out.append(chr(ord("A") + x - 0xBB))
        elif 0xD5 <= x <= 0xEE:
            out.append(chr(ord("a") + x - 0xD5))
        else:
            out.append("?")
    return "".join(out)


def save_slot(b, n, tasks_done, active, summary):
    b.save_state(rf"{SLOTS}\slot_{n}.state")
    base = [
        {"id": "adventure", "name": "Begin the adventure", "status": "done",
         "children": [
             {"id": "name_self", "name": "Choose my name — CLAUDE", "status": "done"},
             {"id": "name_rival", "name": "Name my rival — GROK", "status": "done"},
             {"id": "enter_world", "name": "Wake up in Pallet Town", "status": "done"}]},
        {"id": "starter", "name": "Get my first Pokémon from Prof. Oak",
         "status": "done" if "starter" in tasks_done else "pending", "children": []},
        {"id": "rival1", "name": "Win my first battle vs GROK",
         "status": "done" if "rival1" in tasks_done else "pending", "children": []},
    ]
    if active:
        for t in base:
            if t["id"] == active:
                t["status"] = "active"
        if active == "route1":
            base.append({"id": "route1", "name": "Exit the lab, head north to Route 1",
                         "status": "active", "children": []})
    ctx = {"n": n, "intro_done": True, "strategy": "storyline",
           "goal": "Become the Pokémon League Champion", "tasks": base,
           "summary": summary, "ts": time.strftime("%Y-%m-%d %H:%M")}
    with open(rf"{SLOTS}\slot_{n}.json", "w", encoding="utf-8") as f:
        json.dump(ctx, f)
    say(f"slot {n} saved: {summary}")


class Hooks:
    def phase(self, task_id, action):
        say(f"  [{task_id}] {action}")
    def done_task(self, task_id):
        say(f"  [{task_id}] DONE")
    def typed(self, name):
        say(f"  typed: {name}")


def trigger_battle(b, ow, nav, battle) -> bool:
    """Walk toward the lab door until GROK's challenge loads his mon."""
    warps = nav.map_warps_full()
    door = max(warps, key=lambda w: w["y"]) if warps else None
    say(f"  door warp: {door}")
    for round_ in range(10):
        if battle.active():
            return True
        if ow.dialogue_open():          # riding GROK's challenge lines in
            b.tap("A", 6)
            time.sleep(0.3)
            continue
        if door:
            nav.go_to((door["x"], door["y"] - 1))
        res = ow.walk_until_event("down", max_steps=6)
        say(f"  walk round {round_}: {res} pos={ow.pos()}")
        time.sleep(0.3)
    for _ in range(40):                 # ride any last dialogue into the engine
        if battle.active():
            return True
        b.tap("A", 6)
        time.sleep(0.4)
    return battle.active()


def main() -> int:
    b = BizHawkBridge(timeout=120)
    say("waiting for ai_bridge (launch EmuHawk now if not up)…")
    b.wait_for_bizhawk()
    say(f"connected: ping={b.ping()}")

    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)
    skill = NavigateTo(b, nav)
    battle = Battle(b)
    intro = Intro(b)

    # ---- stage 0: fresh game ------------------------------------------------
    xy = b.player_xy()
    if xy != (0, 0):
        return fail(b, f"expected a FRESH boot at the title (xy=(0,0)), got {xy} — "
                       "restart EmuHawk before running me", "t_notfresh.png")
    say("stage 0 OK: fresh boot at title")

    # ---- stage 1: intro -----------------------------------------------------
    say("stage 1: intro (title -> names -> bedroom)…")
    if not run_intro(intro, Hooks()):
        return fail(b, "intro never landed in the bedroom", "t_intro.png")
    s = reader.read()
    if intro.cur_map() != (4, 1) or s.party_count != 0 or s.money != 3000:
        return fail(b, f"bedroom state wrong: map={intro.cur_map()} "
                       f"party={s.party_count} money={s.money}", "t_bedroom.png")
    say(f"stage 1 OK: bedroom, money={s.money}, party=0")
    save_slot(b, 0, set(), "starter", "Intro done — woke up in the bedroom in Pallet Town")

    # ---- stage 2: part 1 to the starter ------------------------------------
    say("stage 2: Mom -> Oak -> lab -> starter…")
    if not run_part1(ow, nav, skill, Hooks()):
        return fail(b, "run_part1 returned False", "t_part1.png")
    s = reader.read()
    species = reader.read_species(0) if s.party_count else 0
    nick = decode_name(b.read_range(GPLAYER_PARTY + 8, GPLAYER_PARTY + 18))
    if nav.current_map() != (4, 3) or s.party_count != 1 or species not in SPECIES:
        return fail(b, f"post-starter state wrong: map={nav.current_map()} "
                       f"party={s.party_count} species={species}", "t_starter.png")
    if nick != "CLAW":
        return fail(b, f"nickname wrong: {nick!r}", "t_nick.png")
    say(f"stage 2 OK: {SPECIES[species]} 'CLAW' in Oak's lab")

    # ---- stage 3: GROK's ball scene -> walk-ready ---------------------------
    say("stage 3: riding GROK's ball scene to control…")
    if not ow.ride_to_control(timeout=150):
        return fail(b, "never got control after the starter scene", "t_scene.png")
    say(f"stage 3 OK: control at {ow.pos()}")
    save_slot(b, 1, {"starter"}, "rival1",
              f"Starter {SPECIES[species]} 'CLAW' in hand — GROK battle next")

    # ---- stage 4: the rival battle (retry on loss) --------------------------
    for attempt in range(1, BATTLE_TRIES + 1):
        money0 = reader.read_money()
        say(f"stage 4 attempt {attempt}: walking into GROK's challenge (money={money0})…")
        if not trigger_battle(b, ow, nav, battle):
            return fail(b, "battle never triggered", "t_trigger.png")
        elvl, ehp, emx = battle.enemy_stats()
        say(f"  BATTLE ON — GROK's mon lv{elvl} {ehp}/{emx}")
        verdict = battle.fight(narrate=lambda l: say("  " + l))
        say(f"  verdict: {verdict}")
        if verdict == "win":
            money_won = money0 + 80
            break
        if verdict == "lose":
            say("  white-out — riding it out, reloading slot 1…")
            for _ in range(20):
                b.tap("A", 6)
                time.sleep(0.4)
            b.load_state(rf"{SLOTS}\slot_1.state")
            time.sleep(1.5)
            if b.player_xy() == (0, 0):     # OneDrive-dehydrated state guard
                b.load_state(rf"{SLOTS}\slot_1.state")
                time.sleep(1.5)
            continue
        return fail(b, "battle stuck", "t_stuck.png")
    else:
        return fail(b, f"lost {BATTLE_TRIES} battles — strategy needs work", "t_lost.png")

    # ---- stage 5: GROK leaves; verify the win by ground truth ---------------
    say("stage 5: riding GROK's exit to control…")
    if not ow.ride_to_control(timeout=120):
        return fail(b, "never got control after the battle", "t_exit.png")
    money1 = reader.read_money()
    s = reader.read()
    if money1 != money_won:
        return fail(b, f"money wrong after win: {money1} (expected {money_won})",
                    "t_money.png")
    say(f"stage 5 OK: money={money1} (+80 prize), CLAW "
        f"{s.party_total_hp}/{s.party_total_max_hp}")
    save_slot(b, 2, {"starter", "rival1"}, "route1",
              f"Beat GROK! CLAW the {SPECIES[species]} — Route 1 next")
    b.screenshot(OUT + r"\t_done.png")

    say("")
    say("=" * 60)
    say(f"PART 1 CLEAN ✓  {SPECIES[species]} 'CLAW' lv{battle.my_stats()[0]} "
        f"{s.party_total_hp}/{s.party_total_max_hp}, ${money1}, GROK beaten.")
    say("READY FOR ROUTE 1.")
    say("=" * 60)
    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
