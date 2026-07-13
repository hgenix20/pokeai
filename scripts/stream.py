"""Stream control process for the FireRed AI.

Owns the BizHawk bridge, runs the agent in a worker thread (Start/Pause/Stop +
manual takeover), and serves two web dashboards over a tiny local HTTP server:
  * operator  http://127.0.0.1:8777/operator  — your controls (off-stream)
  * viewer    http://127.0.0.1:8777/viewer    — OBS browser source (on-stream)

Flow: launch this, then load bizhawk/ai_bridge.lua in BizHawk. The bridge
connects, both boards flip to READY, and you press Start on the operator board
when you're ready to stream. If the script breaks, hit Manual and drive with the
operator's D-pad/buttons to keep the stream going.

Only the worker thread touches the bridge (single owner); the web handler just
reads a shared state snapshot and posts commands.
"""
from __future__ import annotations

import copy
import json
import os
import random
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pokeai.agents.firered_intro import Intro, StopRun, run_intro
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.rules.nuzlocke import NUZLOCKE_RULES, NuzlockeRuleset
from pokeai.emulator.firered_state_reader import (
    GPLAYER_PARTY,
    SLOT_CURHP_OFF,
    SLOT_LEVEL_OFF,
    SLOT_MAXHP_OFF,
    SLOT_SIZE,
    FireRedStateReader,
)
from pokeai.skills.battle import Battle
from pokeai.ui.overworld_map import render_art, render_cells
from pokeai.ui.stream_state import classify

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM_DIR = os.path.join(_ROOT, "stream")
SLOTS_DIR = os.path.join(_ROOT, "states", "slots")   # per-slot AI context (0-9)
PORT = 8777

# The viewer's "North Star" is the ACTIVE STRATEGY's goal. Selectable before a run,
# locked once running. BACKLOG: more strategies (e.g. "The ultimate shiny hunter",
# "Pokédex completer", "Nuzlocke survivor"), each its own goal + task tree + behavior.
STRATEGIES = {
    "storyline": {
        "name": "Storyline",
        "goal": "Become the Pokémon League Champion",
        "tasks": [
            {"id": "adventure", "name": "Begin the adventure", "status": "active", "children": [
                {"id": "name_self", "name": "Choose my name — CLAUDE", "status": "active"},
                {"id": "name_rival", "name": "Name my rival — GROK", "status": "pending"},
                {"id": "enter_world", "name": "Wake up in Pallet Town", "status": "pending"},
            ]},
            {"id": "pallet", "name": "Set off from Pallet Town", "status": "pending", "children": [
                {"id": "p1_mom", "name": "Say bye to Mom", "status": "pending"},
                {"id": "p1_oak", "name": "Head north — Prof. Oak stops me", "status": "pending"},
            ]},
            {"id": "starter", "name": "Get my first Pokémon from Prof. Oak", "status": "pending", "children": []},
            {"id": "rival1", "name": "Win my first battle vs GROK", "status": "pending", "children": []},
        ],
    },
    "catch_fill6": {
        "name": "Fill the Party",
        "goal": "Catch a full party of 6 Pokémon",
        # Behavioral driver: src/pokeai/strategies/catcher.py (CatcherStrategy).
        # Interchangeable per docs/CORE_GAMEPLAY.md §8; when balls/HP run low the
        # strategy yields and the NeedsArbiter fires the restock/heal drives.
        "tasks": [
            {"id": "cf_have_balls", "name": "Have Poké Balls to throw", "status": "active"},
            {"id": "cf_hunt", "name": "Hunt wild Pokémon in the grass", "status": "pending"},
            {"id": "cf_fill", "name": "Fill the party to 6", "status": "pending"},
        ],
    },
}
DEFAULT_STRATEGY = "storyline"

# Static, JSON-serializable Nuzlocke catalog for GET /api/nuzlocke (the bot's
# !nuzlockerules read). The SSOT is pokeai.rules.nuzlocke.NUZLOCKE_RULES; this
# is just the wire projection of those frozen NuzRule dataclasses.
NUZLOCKE_CATALOG_PUBLIC = [
    {"key": r.key, "name": r.name, "category": r.category,
     "description": r.description, "mandatory": r.mandatory,
     "enforced": r.enforced}
    for r in NUZLOCKE_RULES.values()
]

# Quests the operator can manually add to the quest log. EMPTY until Part 1+ quests
# are built. The Intro is intentionally NOT here: it belongs to the storyline and
# auto-runs only on a fresh game (no save), so it can't be queued manually.
QUEST_CATALOG: list[dict] = []

# stream_state classification moved to pokeai.ui.stream_state.classify (v2,
# pure + T0-tested); map sets like PALLET_MAPS live there now.


def _gen3_text(bs) -> str:
    """Decode Gen-3 fixed text (names): 0xBB..='A-Z', 0xD5..='a-z', 0xA1..='0-9'."""
    out = []
    for b in bs:
        if b == 0xFF:
            break
        if 0xBB <= b <= 0xD4:
            out.append(chr(ord("A") + b - 0xBB))
        elif 0xD5 <= b <= 0xEE:
            out.append(chr(ord("a") + b - 0xD5))
        elif 0xA1 <= b <= 0xAA:
            out.append(chr(ord("0") + b - 0xA1))
        elif b == 0x00:
            out.append(" ")
    return "".join(out).strip()


def _deepest(tasks, status):
    """The deepest task with the given status (children win over parents)."""
    for t in tasks:
        r = _deepest(t.get("children", []), status)
        if r:
            return r
        if t.get("status") == status:
            return t
    return None


def _encode_cells(grid) -> str:
    """One char per tile, row-major: '#' wall, '.' floor, 'g' grass, 'l' ledge.
    ~2KB for a 48x40 map; sent only when the map (version) changes."""
    w, h = grid["w"], grid["h"]
    walk, grass, ledge = grid["walk"], grid["grass"], grid["ledge"]
    out = []
    for y in range(h):
        for x in range(w):
            if (x, y) in grass:
                out.append("g")
            elif (x, y) in ledge:
                out.append("l")
            elif (x, y) in walk:
                out.append(".")
            else:
                out.append("#")
    return "".join(out)


class Control:
    def __init__(self):
        self.lock = threading.Lock()
        self.start_evt = threading.Event()
        self.paused = False
        self.manual = False
        self.stop = False
        self.manual_q: deque[str] = deque()
        strat = STRATEGIES[DEFAULT_STRATEGY]
        self.state = {
            "status": "starting", "connected": False,
            "strategy": DEFAULT_STRATEGY,
            "strategies": [{"id": k, "name": v["name"]} for k, v in STRATEGIES.items()],
            "goal": strat["goal"],
            "tasks": copy.deepcopy(strat["tasks"]),
            "addable": [{"id": q["id"], "name": q["name"]} for q in QUEST_CATALOG],
            "action": "Standing by…",
            "log": [], "game": {"map": None, "pos": None, "money": None,
                                 "party": None, "badges": None},
            "cc": None, "manual": False, "slots": [],
            # the Field Brain's winning drive: {"name","why","critical"} | None
            "drive": None,
            # the active Nuzlocke ruleset snapshot (nuzlocke.to_public()) | None;
            # worker-published each tick, rendered by the viewer/operator boards
            "nuzlocke": None,
        }
        # Viewer-driven Nuzlocke challenge (pokeai.rules.nuzlocke). WORKER-MUTATED
        # ONLY (single-owner rule): the set_nuzlocke directive + observe_party
        # run on the agent thread; handlers only read the published snapshot.
        self.nuzlocke = NuzlockeRuleset()
        # The AI's resume context (paired with a save slot). intro_done drives
        # whether a fresh game runs the intro vs resumes.
        self.context = {"intro_done": False, "summary": ""}
        self.slot_q: deque = deque()   # ("save"|"load", n) processed by the agent thread
        self.pending_from = "new"      # what Start begins from: "new" or a slot number
        # Bot->AI directive seam (B2 whitelist v1, docs/Native-Stream-Operator.md):
        # POST /api/directive enqueues; the WORKER consumes at safe points only
        # (single-owner rule). Each entry: {"id", "directive", "args", "status"}.
        self.directive_q: deque = deque()
        self.directive_log: list = []   # last N results for GET visibility
        self._directive_seq = 0
        # Read-only snapshot served at GET /api/context (for the Twitch bot).
        # Written ONLY by the agent thread (single-owner rule); handlers just read.
        self.ctx = {"connected": False, "status": "starting",
                    "stream_state": "OFFLINE", "map": None, "pos": None,
                    "money": None, "badges": None, "party": [], "task": None,
                    "next_task": None, "goal": self.state["goal"], "action": "",
                    "events": [], "nuzlocke": None, "updated_at": 0.0}
        # Minimap snapshot for GET /api/minimap: the STATIC walkability grid (one
        # compact string, refreshed only when the map changes) + the LIVE player
        # dot / NPCs / doors. Worker-owned, handlers only read.
        self.minimap = {"map": None, "w": 0, "h": 0, "version": "",
                        "cells": "", "player": None, "npcs": [], "warps": [],
                        "updated_at": 0.0}
        self._refresh_slots()

    # state helpers
    def set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def snapshot(self):
        with self.lock:
            return json.dumps(self.state)

    def ctx_snapshot(self):
        with self.lock:
            return json.dumps(self.ctx)

    def minimap_snapshot(self):
        with self.lock:
            return json.dumps(self.minimap)

    # --- bot directives (B2 whitelist v1) ---
    DIRECTIVE_WHITELIST = ("show_party", "explain_plan", "catch_next_encounter",
                           "nickname_next_catch", "enqueue_quest", "set_nuzlocke")

    def submit_directive(self, directive: str, args=None):
        """HTTP-side enqueue. Returns (ok, id-or-reason)."""
        if directive not in self.DIRECTIVE_WHITELIST:
            return False, "not_whitelisted"
        with self.lock:
            self._directive_seq += 1
            entry = {"id": self._directive_seq, "directive": directive,
                     "args": args or {}, "status": "queued",
                     "submitted_at": time.time()}
            self.directive_q.append(entry)
            return True, self._directive_seq

    def finish_directive(self, entry, status, note=""):
        """Worker-side completion; keeps the last 20 results visible."""
        entry["status"] = status
        entry["note"] = note
        entry["finished_at"] = time.time()
        with self.lock:
            self.directive_log.append(dict(entry))
            del self.directive_log[:-20]

    def directives_snapshot(self):
        with self.lock:
            return json.dumps({"queued": list(self.directive_q),
                               "done": list(self.directive_log)})

    def action(self, text):
        # the viewer's verbose "current move" narration (NOT the raw press log)
        with self.lock:
            self.state["action"] = text

    def log(self, text):
        # operator-only granular action log; does NOT touch the viewer narration
        with self.lock:
            lg = self.state["log"]
            lg.append(text)
            del lg[:-80]

    def _walk(self, tasks, tid):
        for t in tasks:
            if t["id"] == tid:
                return t, tasks
            r = self._walk(t.get("children", []), tid)
            if r[0]:
                return r
        return None, None

    def task_active(self, tid):
        with self.lock:
            t, _sib = self._walk(self.state["tasks"], tid)
            if t:
                t["status"] = "active"

    def task_done(self, tid):
        with self.lock:
            t, sibs = self._walk(self.state["tasks"], tid)
            if not t:
                return
            t["status"] = "done"
            nxt = [s for s in sibs if s["status"] == "pending"]
            if nxt:
                nxt[0]["status"] = "active"

    # strategy + quest queue
    def reset_tasks(self):
        """Reset the quest log to the active strategy's fresh state for a new run,
        keeping any manually-queued quests."""
        with self.lock:
            strat = STRATEGIES.get(self.state["strategy"], STRATEGIES[DEFAULT_STRATEGY])
            manual = [t for t in self.state["tasks"] if t.get("manual")]
            self.state["tasks"] = copy.deepcopy(strat["tasks"]) + manual

    def set_strategy(self, sid):
        if sid not in STRATEGIES:
            return
        with self.lock:
            if self.state["status"] in ("running", "paused", "manual"):
                return  # locked mid-game
            s = STRATEGIES[sid]
            manual = [t for t in self.state["tasks"] if t.get("manual")]
            self.state["strategy"] = sid
            self.state["goal"] = s["goal"]
            self.state["tasks"] = copy.deepcopy(s["tasks"]) + manual
        self.log(f"Strategy set to {STRATEGIES[sid]['name']}.")

    def queue_add(self, qid):
        q = next((x for x in QUEST_CATALOG if x["id"] == qid), None)
        if not q:
            return
        with self.lock:
            n = sum(1 for t in self.state["tasks"] if t.get("manual"))
            self.state["tasks"].append({"id": f"m{n}_{qid}", "name": q["name"],
                                        "status": "pending", "manual": True, "children": []})
        self.log(f"Queued quest: {q['name']}.")

    def queue_remove(self, tid):
        with self.lock:
            self.state["tasks"] = [t for t in self.state["tasks"]
                                   if not (t.get("manual") and t["id"] == tid)]

    # save slots (game state + AI context kept in sync, per slot 0-9)
    def request_save(self, n):
        self.slot_q.append(("save", int(n)))

    def request_load(self, n):
        self.slot_q.append(("load", int(n)))

    def _refresh_slots(self):
        slots = []
        for n in range(10):
            j = os.path.join(SLOTS_DIR, f"slot_{n}.json")
            st = os.path.join(SLOTS_DIR, f"slot_{n}.state")
            if os.path.exists(j) and os.path.exists(st):
                try:
                    with open(j, encoding="utf-8") as f:
                        d = json.load(f)
                    slots.append({"n": n, "summary": d.get("summary", ""), "ts": d.get("ts", "")})
                except Exception:
                    pass
        with self.lock:
            self.state["slots"] = slots

    def do_save_slot(self, n, bridge):
        """[agent thread] save the game state file AND the AI context together."""
        os.makedirs(SLOTS_DIR, exist_ok=True)
        state_path = os.path.join(SLOTS_DIR, f"slot_{n}.state")
        try:
            ok = bridge.save_state(state_path)
        except Exception:
            ok = False
        if not ok:
            self.log(f"Save to slot {n} failed (BizHawk state).")
            return
        # Reflect reality: if we're already in the overworld, the intro is done,
        # even if the control process was restarted and lost its in-memory flag.
        try:
            in_world = bridge.player_xy() != (0, 0)
        except Exception:
            in_world = False
        intro_done = bool(self.context.get("intro_done")) or in_world
        summary = (self.context.get("summary")
                   or ("In the overworld" if in_world else "Fresh start"))
        with self.lock:
            data = {"n": n, "intro_done": intro_done,
                    "strategy": self.state["strategy"], "goal": self.state["goal"],
                    "tasks": copy.deepcopy(self.state["tasks"]),
                    "summary": summary,
                    "ts": time.strftime("%Y-%m-%d %H:%M")}
        os.makedirs(SLOTS_DIR, exist_ok=True)
        with open(os.path.join(SLOTS_DIR, f"slot_{n}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.log(f"Saved slot {n}: {data['summary']}")
        self._refresh_slots()

    def do_load_slot(self, n, bridge):
        """[agent thread] load the game state file AND restore the paired AI context."""
        state_path = os.path.join(SLOTS_DIR, f"slot_{n}.state")
        if not os.path.exists(state_path):
            self.log(f"Slot {n} has no saved game state.")
            return
        p = os.path.join(SLOTS_DIR, f"slot_{n}.json")
        data = None
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = None
        try:
            ok = bridge.load_state(state_path)
        except Exception:
            ok = False
        if not ok:
            self.log(f"Load slot {n} failed (BizHawk state).")
            return
        if data:
            with self.lock:
                self.context = {"intro_done": data.get("intro_done", False),
                                "summary": data.get("summary", "")}
                self.state["strategy"] = data.get("strategy", self.state["strategy"])
                self.state["goal"] = data.get("goal", self.state["goal"])
                self.state["tasks"] = data.get("tasks", self.state["tasks"])
            self.action(f"Loaded a save — {data.get('summary', 'resuming')}.")
            self.log(f"Loaded slot {n}: {data.get('summary', '')}")
        else:
            self.log(f"Loaded slot {n} game state (no AI context found).")

    # manual / gating
    def push_manual(self, button):
        self.manual_q.append(button)

    def serve_manual(self, bridge):
        while self.manual_q:
            btn = self.manual_q.popleft()
            self.log(f"manual: {btn}")
            try:
                bridge.tap(btn, 8)
            except Exception:
                pass


CTRL = Control()


class ControlledBridge:
    """Wraps the real bridge: inputs are gated (pause/stop/manual) and logged so
    the operator board sees each action. Reads/screenshots pass straight through."""

    def __init__(self, real, ctrl: Control):
        self._b = real
        self._c = ctrl

    def _gate(self):
        c = self._c
        while True:
            if c.stop:
                raise StopRun()
            if not (c.paused or c.manual):
                return
            c.set(status="manual" if c.manual else "paused")
            c.serve_manual(self._b)
            time.sleep(0.03)

    def tap(self, btn, frames=8):
        self._gate()
        self._c.log(f"press {btn}")
        self._b.tap(btn, frames)

    def set_held(self, btns):
        self._gate()
        self._b.set_held(btns)

    def release(self):
        self._b.release()

    def tick(self, frames=1):
        self._gate()
        self._b.tick(frames)

    # movement/interaction presses go through here too, so Stop/Pause/Manual gate
    # them and the operator log shows walking — not just A taps.
    def press_direction_settle(self, btn, **kw):
        self._gate()
        self._c.log(f"walk {str(btn).lower()}")
        return self._b.press_direction_settle(btn, **kw)

    def press_button_held(self, btn, frames=16):
        self._gate()
        self._c.log(f"hold {btn}")
        return self._b.press_button_held(btn, frames)

    def press_button_pulse(self, btn, frames=16, hold=8):
        self._gate()
        self._c.log(f"press {btn}")
        return self._b.press_button_pulse(btn, frames, hold)

    def press_button(self, btn):
        self._gate()
        self._c.log(f"press {btn}")
        return self._b.press_button(btn)

    def screenshot(self, path, wait=1.0):
        return self._b.screenshot(path, wait)

    def __getattr__(self, name):
        return getattr(self._b, name)   # read_byte/u16/u32/read_range/player_xy…


class Hooks:
    def __init__(self, ctrl: Control):
        self.c = ctrl

    def phase(self, task_id, action):
        self.c.task_active(task_id)
        self.c.action(action)
        self.c.log(action)   # surface the step in the operator log too

    def done_task(self, task_id):
        self.c.task_done(task_id)

    def typed(self, name):
        self.c.action(f"Locked it in — {name}.")


def run_catch_fill6(cb, c, reader, tick):
    """Run the catch_fill6 strategy through the Field Brain (NeedsArbiter over
    live RAM) on the worker thread. Inputs go through the ControlledBridge (so
    Pause/Stop/Manual gate every press); the winning drive + reason is published
    to the boards via state['drive'] and mirrored into /api/context."""
    from pokeai.agents.field_brain import build_fill6_brain
    from pokeai.perception.navigator import Navigator
    from pokeai.skills.catch import Catch
    from pokeai.skills.overworld import Overworld
    from pokeai.skills.services import Services
    from pokeai.strategies.catcher import CatcherStrategy

    nav = Navigator(cb)
    ow = Overworld(cb, nav, reader)
    battle = Battle(cb, ruleset=c.nuzlocke)
    catch = Catch(cb, battle)
    services = Services(cb, nav, ow, reader)
    catcher = CatcherStrategy(cb, nav, battle, catch, target_party=6,
                              reader=reader, ruleset=c.nuzlocke)

    def narrate(m):
        c.action(m)
        c.log(m)
        try:
            tick()   # keep /api/context + boards fresh during the long run
        except (ConnectionError, OSError):
            raise
        except Exception:
            pass

    def on_decision(d, ctx):
        c.set(drive={"name": d.drive, "why": d.rationale,
                     "critical": d.critical})
        c.log(f"drive {d.drive} -> {d.goal} ({d.rationale})")

    brain = build_fill6_brain(cb, nav, battle, catch, services, reader, catcher,
                              narrate=narrate, on_decision=on_decision)
    res = brain.run(max_cycles=30)
    c.set(drive=None)
    if res["status"] == "complete":
        c.action("Party of six, healthy and ready — strategy complete!")
        c.log(f"catch_fill6 complete in {res['cycles']} cycles")
    else:
        c.action("Wrapping up the catching run.")
        c.log(f"catch_fill6 ended: {res['status']}")
    return res


def agent_thread(bridge: BizHawkBridge):
    c = CTRL
    c.set(status="connecting", action="Linking up to the game…")
    c.log("Waiting for ai_bridge.lua to connect…")
    bridge.wait_for_bizhawk()
    reader = FireRedStateReader(bridge)
    c.set(connected=True, status="ready", action="Waiting for the adventure to begin…")
    c.log("Bridge connected — press Start.")

    cb = ControlledBridge(bridge, c)
    battle_probe = Battle(bridge)
    from pokeai.perception.navigator import Navigator
    mini_nav = Navigator(bridge)          # read-only; single-owner (worker thread)
    last_stats = [0.0]
    last_battle = [False, 0.0]            # [was_in_battle, ended_at] edge tracker

    def build_minimap(grp, num, px, py, in_world):
        """Publish the walkability minimap. The static grid (cells) is rebuilt
        only when the map id changes (a ~10s socket sweep, cached in vision);
        the player/NPC/door overlay refreshes every call (cheap)."""
        if not in_world:
            with c.lock:
                c.minimap = dict(c.minimap, map=None, player=None, npcs=[],
                                 updated_at=time.time())
            return
        version = f"{grp}_{num}"
        try:
            static = c.minimap.get("version") != version
            grid = mini_nav.vision.nav_grid()          # cached per map in vision
            cells = _encode_cells(grid) if static else c.minimap["cells"]
            warps = [[w["x"], w["y"]] for w in mini_nav.map_warps_full()]
            npcs = [[x, y] for (x, y) in mini_nav.vision.object_tiles()]
            with c.lock:
                c.minimap = {"map": [grp, num], "w": grid["w"], "h": grid["h"],
                             "version": version, "cells": cells,
                             "player": [px, py], "npcs": npcs, "warps": warps,
                             "updated_at": time.time()}
        except (ConnectionError, OSError):
            raise
        except Exception as e:
            with c.lock:
                c.minimap = dict(c.minimap, err=f"{type(e).__name__}: {e}")

    def _read_party(count):
        party = []
        for i in range(min(count, 6)):
            base = GPLAYER_PARTY + i * SLOT_SIZE
            try:
                sp = reader.read_species(i)
            except Exception:
                sp = 0
            party.append({
                "species": sp,
                "name": _gen3_text(bridge.read_range(base + 0x08, base + 0x12)) or None,
                "level": bridge.read_byte(base + SLOT_LEVEL_OFF),
                "hp": bridge.read_u16(base + SLOT_CURHP_OFF),
                "max_hp": bridge.read_u16(base + SLOT_MAXHP_OFF),
            })
        return party

    def stats_tick():
        if time.time() - last_stats[0] < 0.8:
            return
        last_stats[0] = time.time()
        try:
            s = reader.read()
            grp, num = (s.current_map >> 8), (s.current_map & 0xFF)
            # Only publish once we're actually in the overworld (player object loaded:
            # x/y >= 0). Before that (title/intro) the reads are placeholders and would
            # show MAP 0,0 / POS -7,-7 on stream, so keep "—".
            in_world = (0 <= grp < 60 and 0 <= s.party_count <= 6
                        and 0 <= s.money < 1_000_000 and s.x_pos >= 0 and s.y_pos >= 0)
            if in_world:
                c.set(game={"map": [grp, num], "pos": [s.x_pos, s.y_pos],
                            "money": s.money, "party": s.party_count, "badges": s.badge_count})
            else:
                # not in the overworld (title/intro) — clear so the board shows "—"
                # instead of stale values
                c.set(game={"map": None, "pos": None, "money": None,
                            "party": None, "badges": None})

            # --- /api/context snapshot (for the Twitch bot; read-only consumers) ---
            party = _read_party(s.party_count) if in_world else []
            # in-battle: gMain.inBattle (gMain=0x030030F0, +0x43D bit 1) -
            # a LIVE flag, unlike gEnemyParty which lingers after every
            # battle and pinned stream_state at WILD_BATTLE for whole
            # sessions (nav audit 2026-07-06). battle_probe.active() stays
            # as the fallback if the IWRAM read hiccups.
            try:
                in_battle = bool(bridge.read_byte(0x0303352D) & 2) if in_world else False
            except Exception:
                try:
                    in_battle = battle_probe.active() if in_world else False
                except Exception:
                    in_battle = False
            # bag counts for the B3 ask engine's resource triggers (one
            # read_range block per pocket; cheap at this cadence)
            balls = heal_items = None
            if in_world:
                try:
                    balls = reader.ball_count()
                    heal_items = reader.count_heal_items()
                except Exception:
                    pass
            # Nuzlocke: worker owns c.nuzlocke, so death detection + snapshot
            # happen here (single-owner rule). observe_party records deaths on
            # hp==0 transitions when permadeath is active; to_public() is the
            # board/context payload (None when no ruleset is active -> boards
            # hide the section). Gathered OUTSIDE the lock; c.set() below takes
            # the lock (non-reentrant) so it must not be nested in a with-lock.
            if in_world:
                try:
                    c.nuzlocke.observe_party(party, (grp, num))
                except Exception:
                    pass
            nuz_pub = c.nuzlocke.to_public() if c.nuzlocke.is_active() else None
            c.set(nuzlocke=nuz_pub)
            with c.lock:
                status = c.state.get("status", "")
                active = _deepest(c.state["tasks"], "active")
                pending = _deepest(c.state["tasks"], "pending")
                goal = c.state.get("goal", "")
                action = c.state.get("action", "")
                events = list(c.state.get("log", []))[-5:]
                saving = bool(c.slot_q)
                drive = c.state.get("drive")
            # classifier v3 (pure, T0-tested in tests/test_stream_state.py);
            # wild-vs-trainer via gBattleTypeFlags bit 3 (VERIFIED 2026-07-05)
            hp_frac = None
            if in_world and party:
                alive = [m for m in party if m["hp"] > 0]
                if alive and alive[0]["max_hp"] > 0:
                    hp_frac = alive[0]["hp"] / alive[0]["max_hp"]
            wild = None
            if in_battle:
                try:
                    wild = not battle_probe.is_trainer_battle()
                except Exception:
                    wild = None
            # battle-end edge for the POST_BATTLE_SAFE grace window
            if last_battle[0] and not in_battle:
                last_battle[1] = time.time()
            last_battle[0] = in_battle
            since_battle = (time.time() - last_battle[1]
                            if last_battle[1] else None)
            # CUTSCENE: the player ObjectEvent script-lock bit (frozen);
            # force-walk cutscenes set it, plain boxes do not (probed 6/17)
            frozen = False
            if in_world and not in_battle:
                try:
                    frozen = bool(bridge.read_u32(0x02036E38) & 0x100)
                except Exception:
                    frozen = False
            stream_state = classify(
                connected=True, in_world=in_world, status=status,
                saving=saving, in_battle=in_battle,
                active_task_id=active.get("id") if active else None,
                cur_map=(grp, num) if in_world else None,
                active_hp_frac=hp_frac, wild_battle=wild,
                frozen=frozen, seconds_since_battle=since_battle,
                catch_armed=bool(c.state.get("catch_next")))
            with c.lock:
                c.ctx = {"connected": True, "status": status,
                         "stream_state": stream_state,
                         "map": [grp, num] if in_world else None,
                         "pos": [s.x_pos, s.y_pos] if in_world else None,
                         "money": s.money if in_world else None,
                         "badges": s.badge_count if in_world else None,
                         "balls": balls,
                         "heal_items": heal_items,
                         "party": party,
                         "task": ({"id": active["id"], "name": active["name"],
                                   "status": "active"} if active else None),
                         "next_task": pending["name"] if pending else None,
                         "goal": goal, "action": action, "events": events,
                         "drive": drive, "nuzlocke": nuz_pub,
                         "updated_at": time.time()}
            # minimap overlay (cheap) + static grid rebuild only on map change.
            # Built whenever in the overworld — the map behind a battle is still
            # valid, and battle detection false-positives on a lingering enemy.
            build_minimap(grp, num, s.x_pos, s.y_pos, in_world)
            # bot directives ride the same safe-point cadence during runs
            serve_directives()
        except (ConnectionError, OSError):
            raise   # let the agent loop reconnect
        except Exception:
            pass

    def serve_slots():
        while c.slot_q:
            op, n = c.slot_q.popleft()
            (c.do_save_slot if op == "save" else c.do_load_slot)(n, bridge)

    def serve_directives():
        """Consume bot directives at SAFE POINTS only (idle loop + stats
        ticks). v1 semantics: show_party/explain_plan answer immediately from
        live state; catch_next_encounter arms a flag; the rest fail visibly
        rather than pretending."""
        while c.directive_q:
            with c.lock:
                entry = c.directive_q.popleft() if c.directive_q else None
            if entry is None:
                break
            d = entry["directive"]
            try:
                if d == "show_party":
                    party = _read_party(reader.read().party_count)
                    line = " / ".join(
                        f"{m['name'] or '?'} lv{m['level']} {m['hp']}/{m['max_hp']}"
                        for m in party) or "no party yet"
                    c.action(f"Party check: {line}")
                    c.finish_directive(entry, "executed")
                elif d == "explain_plan":
                    with c.lock:
                        drive = c.state.get("drive")
                        goal = c.state.get("goal", "")
                    c.action(f"The plan: {drive['name']} — {drive['why']}"
                             if drive else f"The plan: {goal}")
                    c.finish_directive(entry, "executed")
                elif d == "catch_next_encounter":
                    c.set(catch_next=True)
                    c.log("Directive armed: catch the next wild encounter.")
                    c.finish_directive(entry, "armed")
                elif d == "set_nuzlocke":
                    # viewer-driven ruleset change. Worker owns c.nuzlocke, so
                    # the mutation happens here (single-owner rule). rng is
                    # seedable in tests; the live process uses module random.
                    rule = entry["args"].get("rule")
                    status = c.nuzlocke.apply_directive(rule, random)
                    c.action(f"Nuzlocke: {status.replace(':', ' ')}.")
                    c.log(f"Directive set_nuzlocke({rule}) -> {status}")
                    c.finish_directive(entry, "executed", status)
                else:
                    c.finish_directive(entry, "failed", "unsupported_v1")
            except (ConnectionError, OSError):
                raise
            except Exception as e:
                c.finish_directive(entry, "failed", type(e).__name__)

    def reconnect():
        with c.lock:
            c.ctx = dict(c.ctx, connected=False, stream_state="OFFLINE",
                         updated_at=time.time())
        c.set(connected=False, status="connecting", action="Reconnecting to the game…")
        c.log("Bridge connection lost — waiting for ai_bridge to reconnect…")
        try:
            bridge.reaccept()
        except Exception as e:
            c.log(f"Reconnect failed: {type(e).__name__}: {e}")
            return
        c.set(connected=True, status="ready", action="Reconnected — ready when you are.")
        c.log("Bridge reconnected.")

    while True:
        # idle until Start, serving manual takeover + slot save/load + live stats
        while not c.start_evt.is_set():
            try:
                if c.manual:
                    c.set(status="manual")
                c.serve_manual(bridge)
                serve_slots()
                serve_directives()
                stats_tick()
            except (ConnectionError, OSError):
                reconnect()
            time.sleep(0.05)
        c.start_evt.clear()
        c.stop = False
        c.set(status="running")
        try:
            # If the operator chose a slot to start from, load it first (game state
            # + AI context). "new" = a fresh game.
            fr = c.pending_from
            # The operator's LIVE strategy pick wins over the slot JSON's stored
            # one: do_load_slot restores the slot's strategy, which silently
            # reverted an explicit pre-Start selection (live 2026-07-05: picked
            # catch_fill6, started from slot 8, ran Part 1 instead).
            chosen = c.state.get("strategy")
            if fr != "new":
                try:
                    nslot = int(fr)
                except (TypeError, ValueError):
                    nslot = None
                if nslot is not None:
                    c.do_load_slot(nslot, bridge)
                    if (chosen in STRATEGIES
                            and c.state.get("strategy") != chosen):
                        strat = STRATEGIES[chosen]
                        c.set(strategy=chosen, goal=strat["goal"],
                              tasks=copy.deepcopy(strat["tasks"]))
                        c.log(f"Strategy kept as {strat['name']} "
                              "(operator pick overrides the slot's).")
            # Fresh game: REBOOT THE CORE first (FIXLIST FL-1 - "New Game"
            # used to silently run the intro script against a loaded save),
            # then run the intro, then CHAIN into Part 1 (FL-5).
            if fr == "new":
                c.log("New Game: power-cycling to the title screen.")
                try:
                    cb.reboot()
                    time.sleep(6.0)   # boot animation before the title
                except Exception as e:
                    c.log(f"reboot failed ({e}) - continuing from current state")
            def run_storyline():
                # CONTINUOUS STORYLINE (FIXLIST FL-2): parts run in order,
                # each FACT-GATED so any save resumes at the right place -
                # the old branch was hardwired to run_part1 and replayed
                # the bedroom script from Cerulean (live 2026-07-06).
                c.action("Picking the story up from the facts on the save.")
                c.log("Storyline: fact-gated part dispatch.")
                from pokeai.agents.firered_part1 import run_part1
                from pokeai.agents.story_part2 import run_part2
                from pokeai.agents.story_part3 import run_part3
                from pokeai.agents.story_part4 import run_part4
                from pokeai.perception.navigator import Navigator
                from pokeai.skills.battle import Battle
                from pokeai.skills.catch import Catch
                from pokeai.skills.journey import WildPolicy
                from pokeai.skills.navigate_to import NavigateTo
                from pokeai.skills.overworld import Overworld
                from pokeai.skills.services import Services
                nav = Navigator(cb)
                skill = NavigateTo(cb, nav)
                ow = Overworld(cb, nav, reader)
                svc = Services(cb, nav, ow, reader)
                battle_s = Battle(cb, reader, ruleset=c.nuzlocke)
                catch_s = Catch(cb, battle_s)
                # Nuzlocke wiring: the ONE WildPolicy at this line flows into
                # every story part, so the first-encounter/dupes/species gate +
                # nickname-on-catch + permadeath exclusion apply run-wide.
                policy = WildPolicy(cb, battle_s, catch_s, narrate=c.log,
                                    ruleset=c.nuzlocke, area_fn=nav.current_map)
                hooks = Hooks(c)
                # Part 1's own gate (it is not internally fact-gated yet,
                # FIXLIST FL-7): no starter = Part 1 territory.
                if reader.read().party_count == 0:
                    c.log("Storyline: Part 1 (no starter on this save).")
                    if not run_part1(ow, nav, skill, hooks):
                        raise StopRun()
                for name, runner in (
                        ("Part 2", lambda: run_part2(cb, reader, nav, ow,
                                                     svc, policy, hooks)),
                        ("Part 3", lambda: run_part3(cb, reader, nav, ow, svc,
                                                     battle_s, catch_s,
                                                     policy, hooks)),
                        ("Part 4", lambda: run_part4(cb, reader, nav, ow, svc,
                                                     battle_s, catch_s,
                                                     policy, hooks))):
                    c.log(f"Storyline: {name}.")
                    if not runner():
                        c.log(f"{name} stopped short - operator can restart "
                              "to resume from the facts.")
                        raise StopRun()
                c.action("Cerulean reached — the built story range is complete!")
                c.log("Storyline complete through Part 4 ([[STOP]] marker).")

            try:
                in_world = bridge.player_xy() != (0, 0)
            except Exception:
                in_world = False
            if not in_world:
                c.context = {"intro_done": False, "summary": ""}
                c.reset_tasks()
                intro = Intro(cb)
                intro.tick = stats_tick
                ok = run_intro(intro, Hooks(c))
                if ok:
                    c.context = {"intro_done": True,
                                 "summary": "Intro done — woke up in the bedroom in Pallet Town"}
                    c.action("I woke up in my bedroom in Pallet Town.")
                    c.log("Intro complete — in the bedroom (map 4,1).")
                else:
                    c.action("I'm not quite where I expected to be…")
                    c.log("Intro ended but not in the bedroom.")
                if ok and c.state.get("strategy") == "storyline":
                    # chain into the FULL dispatcher (FL-5): one Start press
                    # plays the entire built range, not just Part 1
                    c.log("Chaining into the storyline.")
                    run_storyline()
            elif c.state.get("strategy") == "catch_fill6":
                c.log("Strategy catch_fill6 — running the Field Brain.")
                run_catch_fill6(cb, c, reader, stats_tick)
            elif c.state.get("strategy") == "storyline":
                run_storyline()
            else:
                c.action("I'm already in the world, getting my bearings.")
                c.log("In the overworld but no saved context — load a slot to resume with context.")
            c.set(status="done")
        except StopRun:
            c.action("Taking a break — the operator has the controls.")
            c.log("Run stopped by operator.")
            c.set(status="stopped")
        except (ConnectionError, OSError):
            c.log("Bridge connection lost mid-run — reconnecting.")
            reconnect()
        except Exception as e:
            c.action("Hit a snag — the operator is stepping in.")
            c.log(f"Error: {type(e).__name__}: {e}")
            c.set(status="error")


# --- web server ---
def _send(h, code, body, ctype):
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def _file(name):
    with open(os.path.join(STREAM_DIR, name), "rb") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p == "/state":
                _send(self, 200, CTRL.snapshot().encode(), "application/json")
            elif p == "/api/context":
                _send(self, 200, CTRL.ctx_snapshot().encode(), "application/json")
            elif p == "/api/minimap":
                _send(self, 200, CTRL.minimap_snapshot().encode(), "application/json")
            elif p == "/api/directives":
                _send(self, 200, CTRL.directives_snapshot().encode(), "application/json")
            elif p == "/api/nuzlocke":
                # catalog is the static SSOT projection; active/tracker come
                # from the worker-published snapshot (read under the lock).
                with CTRL.lock:
                    snap = CTRL.state.get("nuzlocke")
                body = json.dumps({
                    "catalog": NUZLOCKE_CATALOG_PUBLIC,
                    "active": (snap or {}).get("rules", []),
                    "tracker": (snap or {}).get("tracker", {}),
                }).encode()
                _send(self, 200, body, "application/json")
            elif p == "/api/minimap.png":
                # real-art minimap: crop the Kanto stitch at the live tile;
                # interiors fall back to the live walkability cells. Pure
                # PIL over snapshots - no bridge access from the handler.
                with CTRL.lock:
                    mp = CTRL.ctx.get("map")
                    pos = CTRL.ctx.get("pos")
                    mm = dict(CTRL.minimap)
                png = None
                if mp and pos:
                    png = render_art(tuple(mp), pos[0], pos[1])
                if png is None:
                    png = render_cells(mm.get("cells", ""), mm.get("w", 0),
                                       mm.get("h", 0), mm.get("player"),
                                       mm.get("npcs"), mm.get("warps"))
                _send(self, 200, png, "image/png")
            elif p in ("/", "/operator", "/operator.html"):
                _send(self, 200, _file("operator.html"), "text/html")
            elif p in ("/viewer", "/viewer.html"):
                _send(self, 200, _file("viewer.html"), "text/html")
            elif p == "/style.css":
                _send(self, 200, _file("style.css"), "text/css")
            elif p == "/minimap.js":
                _send(self, 200, _file("minimap.js"), "application/javascript")
            elif p == "/minimap_sample.json":
                _send(self, 200, _file("minimap_sample.json"), "application/json")
            else:
                _send(self, 404, b"not found", "text/plain")
        except FileNotFoundError:
            _send(self, 404, b"missing asset", "text/plain")

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        if p == "/api/directive":
            # B2 whitelist v1: the bot's only write seam into the AI
            ok, ref = CTRL.submit_directive(str(data.get("directive", "")),
                                            data.get("args"))
            body = (json.dumps({"ok": ok, "id" if ok else "reason": ref})
                    .encode())
            _send(self, 200 if ok else 400, body, "application/json")
            return
        if p != "/cmd":
            _send(self, 404, b"", "text/plain")
            return
        cmd = data.get("cmd")
        c = CTRL
        if cmd == "start":
            c.stop = False; c.paused = False; c.manual = False
            c.pending_from = str(data.get("from", "new"))
            c.set(manual=False); c.start_evt.set()
        elif cmd == "pause":
            c.paused = True
        elif cmd == "resume":
            c.paused = False
            if c.state.get("status") in ("paused",):
                c.set(status="running")
        elif cmd == "stop":
            c.stop = True; c.paused = False
        elif cmd == "manual":
            c.manual = bool(data.get("on")); c.set(manual=c.manual)
        elif cmd == "press":
            c.push_manual(str(data.get("button", "")).upper())
        elif cmd == "strategy":
            c.set_strategy(str(data.get("id", "")))
        elif cmd == "queue_add":
            c.queue_add(str(data.get("id", "")))
        elif cmd == "queue_remove":
            c.queue_remove(str(data.get("id", "")))
        elif cmd == "save_slot":
            c.request_save(int(data.get("n", 0)))
        elif cmd == "load_slot":
            c.request_load(int(data.get("n", 0)))
        _send(self, 200, b'{"ok":true}', "application/json")


def main():
    bridge = BizHawkBridge(timeout=86400)  # serve all session
    threading.Thread(target=agent_thread, args=(bridge,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"operator  -> http://127.0.0.1:{PORT}/operator", flush=True)
    print(f"viewer    -> http://127.0.0.1:{PORT}/viewer   (OBS browser source)", flush=True)
    print("waiting for ai_bridge.lua to connect…", flush=True)
    if "--no-open" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/operator")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
