"""Part 4 of the storyline — Pewter -> Route 3 -> Mt. Moon -> Cerulean.

Port of the G11 acceptance runner (scripts/part4_run.py, PASSED live
2026-07-06) into the reusable agents arsenal. Stages:

  A  east out of Pewter (Oak's aide's Running Shoes stop rides out) -> Route 3
  B  Route 3 trainer gauntlet crossing EAST -> Route 4 (west)
  C  Route 4 Center discovered + heal
  D  Mt. Moon: explore-by-warps (fight everything; Rockets + Miguel are just
     trainers en route), FOSSIL grabbed via object interact + bag delta;
     exit = back on Route 4 EAST of the x21-30 dividing wall
  E  Route 4 east -> Cerulean (first new city map)
  F  Cerulean Center discovered + heal (RAM ground truth). PASS.

FACT-GATED: every stage checks established facts before acting, so the same
entry point completes instantly on a save where the work is done and resumes
mid-journey anywhere else:
  * Cerulean's Center row in services.CENTERS  => the whole part is done
    (that row is only ever written by a live, RAM-verified heal).
  * current map group 1                        => resume INSIDE Mt. Moon
  * on Route 4 with x >= EAST_X                => Mt. Moon already behind us
  * on Route 4 west / Route 3 / Pewter         => resume that leg
  * Route 4 Center row known                   => stage C is a lookup

Geography that cost live hours to learn (do not "simplify"):
  * Route 3 runs EAST then BENDS NORTH into Route 4; its east edge is a dead
    end and corner grass knocks the walker off it (live 2026-07-05) — hence
    the alternating NORTH/EAST legs.
  * Route 4 is one 108-wide map SPLIT by an impassable wall at x21-30
    (probe_route4_east, 2026-07-06). BOTH 1F Mt. Moon doors land on the WEST
    shelf (x19); the B1F door (32,5)<->(1,2) is the ONLY true east exit, so
    x >= 31 is the one honest "past Mt. Moon" test.
  * SOUTH off Route 4 WEST drops through the map seam onto Route 3's dead-end
    corner (live 2026-07-06): stage E recovers NORTH instead of legging.

Slot saves are the acceptance script's concern and are OMITTED here; the
Mt. Moon visited sidecar (exploration knowledge) IS kept — losing it re-walks
solved pockets after every restart.

`hooks` (the dashboard) gets phase/done_task with 'p4_*' task ids, same
contract as run_part1.
"""
from __future__ import annotations

import json
import time

from pokeai.skills.journey import cross_edge, leave_building_safe
from pokeai.skills.services import CENTERS

PEWTER = (3, 2)
ROUTE3 = (3, 21)      # discovered live 2026-07-05
ROUTE4 = (3, 22)      # discovered live 2026-07-05
CERULEAN = (3, 3)     # Center discovered live 2026-07-06 (part4_run stage F)

# Probed 2026-07-06 (probe_route4_east): the true east side of Route 4 starts
# at x=31; anything west of the x21-30 wall is the shelf both 1F doors land on.
EAST_X = 31

ITEM_REPEL = 86

# START-menu cursor RAM (EWRAM-diff solved 2026-07-06, two mirrors both
# verified): index 0..6 = POKEDEX/POKEMON/BAG/CLAUDE/SAVE/OPTION/EXIT.
START_CURSOR_ADDR = 0x020370F4
BAG_INDEX, MENU_LEN = 2, 7

# The Mt. Moon visited sidecar persists across restarts (runs get killed and
# patched a lot; losing exploration knowledge re-walks solved pockets).
# Module-level so operators/tests can repoint it.
STATES_DIR = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
VISITED_PATH = STATES_DIR + r"\p4_moon_visited.json"

TASK_IDS = ("p4_route3", "p4_center", "p4_moon", "p4_east", "p4_cerulean")


def _say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class _NoHooks:
    def phase(self, task_id, action): ...
    def done_task(self, task_id): ...


def _fail(h, task_id, msg) -> bool:
    _say(f"FAIL: {msg}")
    h.phase(task_id, f"FAIL: {msg} - needs a look")
    return False


def bag_all(reader) -> dict:
    out = {}
    for p in ("items", "key_items", "balls"):
        for item, qty in reader.read_bag_pocket(p):
            out[item] = out.get(item, 0) + qty
    return out


def _load_visited(path) -> dict:
    """Load the visited sidecar. Keys reconstruct as ((group, num), x, y).

    The acceptance script's flat `tuple(json.loads(k))` left the inner map id
    a LIST (unhashable), so the dict comprehension raised and the sidecar
    never actually loaded — fixed here with a deep tuple. The ON-DISK format
    is unchanged ("[[g, n], x, y]" keys), so existing sidecar files load."""
    try:
        raw = json.load(open(path, encoding="utf-8"))
        out = {}
        for k, v in raw.items():
            m, x, y = json.loads(k)
            out[(tuple(m), int(x), int(y))] = v
        return out
    except Exception:
        return {}


def _save_visited(path, visited: dict) -> None:
    try:
        json.dump({json.dumps(list(k)): v for k, v in visited.items()},
                  open(path, "w", encoding="utf-8"))
    except Exception:
        pass


def discover_center(b, nav, ow, svc, reader, city) -> dict | None:
    """Cookie-cutter Center hunt: try city doors until a 15-wide interior with
    a top-counter NPC heals us (RAM-verified). Returns and RECORDS the
    services.CENTERS row — that write is the fact later runs gate on."""
    for w in nav.map_warps_full():
        wx, wy = w["x"], w["y"]
        if not nav.go_to((wx, wy + 1), attempts=8):
            continue
        if nav.take_warp((wx, wy)) is None:
            b.press_button_held("UP", 32)
            time.sleep(1.0)
        if nav.current_map() == city:
            continue
        interior = nav.current_map()
        ow.wait_control(10)
        g = nav.vision.nav_grid()
        npcs = sorted(nav.vision.object_tiles())
        _say(f"  interior {interior} {g['w']}x{g['h']} npcs {npcs}")
        if g["w"] == 15 and any(t[1] <= 2 for t in npcs):
            nurse = min(npcs, key=lambda t: (t[1], abs(t[0] - g["w"] // 2)))
            stand = (nurse[0], nurse[1] + 2)
            if svc.heal_here(nurse, stand=stand):
                row = {"map": interior, "door": (wx, wy),
                       "nurse": nurse, "stand": stand}
                CENTERS[city] = row
                _say(f"  CENTER row: {city}: {row}")
                leave_building_safe(b, nav)
                return row
        leave_building_safe(b, nav)
    return None


def try_fossil(b, nav, ow, reader) -> int | None:
    """Look for interactable objects near the player; a bag delta after an
    interact means we picked something up (the fossil is the payoff)."""
    before = bag_all(reader)
    px, py = nav.vision.player_xy()
    objs = [t for t in sorted(nav.vision.object_tiles(),
                              key=lambda t: abs(t[0] - px) + abs(t[1] - py))
            if abs(t[0] - px) + abs(t[1] - py) <= 6]
    for t in objs[:3]:
        try:
            ow.interact(t, rounds=3)
            ow.advance_dialogue(cap=30)
        except Exception:
            continue
        after = bag_all(reader)
        new = {k: v for k, v in after.items() if v > before.get(k, 0)}
        if new:
            item = next(iter(new))
            _say(f"  picked up item id {item} at {t}")
            return item
    return None


def run_part4(b, reader, nav, ow, svc, battle, catch, policy, hooks=None) -> bool:
    """Drive Part 4. `b`=bridge, `reader`=FireRedStateReader, `nav`=Navigator,
    `ow`=Overworld, `svc`=Services, `battle`/`catch`=battle skills,
    `policy`=WildPolicy (flee wilds / fight trainers). `hooks` (the dashboard)
    is notified per stage. Returns True when Cerulean's Center heal is a fact."""
    h = hooks or _NoHooks()

    # --- the whole-part fact gate. NOT the CENTERS row: that dict has held
    # a STATIC Cerulean entry since 2026-07-06 (services.py), so it is true
    # on a fresh game and would skip the whole part. Standing in Cerulean
    # is the live fact that the journey already happened on THIS save.
    # TODO: replace with the FLAG_VISITED_CERULEAN probe once its flag id
    # is live-verified (needed anyway when Part 5 makes the player leave).
    if nav.current_map() == CERULEAN:
        _say("already in Cerulean - Part 4 done on this save")
        h.phase("p4_cerulean", "Already in Cerulean - Part 4 complete")
        for t in TASK_IDS:
            h.done_task(t)
        return True

    d = reader.read_party_details()
    _say(f"start map {nav.current_map()} levels {[m['level'] for m in d]} "
         f"money {reader.read_money()} balls {reader.ball_count()}")

    _say("=== stage A/B: east out of Pewter -> Route 3 -> Route 4 ===")
    h.phase("p4_route3", "Heading east out of Pewter toward Route 3")
    in_cave_resume = nav.current_map()[0] == 1
    guard = 0
    while nav.current_map()[0] not in (1, 3):
        leave_building_safe(b, nav)
        guard += 1
        if guard >= 12:
            return _fail(h, "p4_route3", f"stuck indoors: {nav.current_map()}")
    if in_cave_resume:
        _say("resuming INSIDE Mt. Moon - skipping straight to exploration")
        route3, route4 = ROUTE3, ROUTE4
    elif nav.current_map() == ROUTE4:
        route3, route4 = ROUTE3, ROUTE4
        # Probed 2026-07-06 (probe_route4_east): Route 4 is one 108-wide map
        # SPLIT by an impassable wall at x21-30. West shelf (Center + both 1F
        # doors) is x<=21; the true east side starts at x31 and is reached
        # ONLY via the B1F door (32,5)<->(1,2). x>=31 = genuinely east.
        if nav.vision.player_xy()[0] >= EAST_X:
            _say("already on Route 4 EAST (past Mt. Moon) - going to Cerulean")
            in_cave_resume = None   # sentinel: skip stage D entirely
        else:
            _say("already on Route 4 - skipping to Mt. Moon")
    else:
        if nav.current_map() == PEWTER:
            if not cross_edge(b, nav, ow, reader, policy, None, "EAST",
                              budget=600, narrate=_say):
                return _fail(h, "p4_route3",
                             f"stuck leaving Pewter: {nav.current_map()}")
        route3 = nav.current_map()
    _say(f"ROUTE 3 = {route3}; bag {bag_all(reader)}")
    # Route 3 runs EAST then BENDS NORTH into Route 4; the east edge itself is
    # a dead end and corner grass keeps knocking the walker off it (live
    # 2026-07-05). Alternate short NORTH/EAST crossings until the map changes.
    if nav.current_map() != ROUTE4 and not in_cave_resume:
        h.phase("p4_route3", "Crossing Route 3's trainer gauntlet")
        for leg in range(8):
            d = "NORTH" if (leg % 2 == 0 and nav.vision.player_xy()[0] > 55) \
                or leg % 2 == 1 else "EAST"
            _say(f"Route 3 leg {leg + 1}: crossing {d} from {nav.vision.player_xy()}")
            cross_edge(b, nav, ow, reader, policy, None, d, budget=300, narrate=_say)
            if nav.current_map() != route3:
                break
        if nav.current_map() == route3:
            return _fail(h, "p4_route3", f"stuck on Route 3: {nav.current_map()}")
    route4 = ROUTE4 if in_cave_resume else nav.current_map()
    _say(f"ROUTE 4 (west) = {route4}")
    h.done_task("p4_route3")

    _say("=== stage C: Route 4 Center ===")
    h.phase("p4_center", "Looking for the Route 4 Pokemon Center")
    row = CENTERS.get(route4)
    if row:
        _say(f"Center already known: {row}")
    else:
        row = discover_center(b, nav, ow, svc, reader, route4)
        if not row:
            # optional stage: a miss is survivable (Pewter respawn covers us)
            _say("no Center on Route 4 west (continuing - Pewter respawn covers us)")
            h.phase("p4_center", "No Center found on Route 4 west - continuing")
    h.done_task("p4_center")

    _say("=== stage D: Mt. Moon ===")
    if in_cave_resume is None:
        _say("(skipped - already east of Mt. Moon)")
        h.phase("p4_moon", "Mt. Moon already behind us")
        h.done_task("p4_moon")
        return stages_east(b, reader, nav, ow, svc, battle, catch, policy,
                           route3, route4, None, h)
    return stage_moon(b, reader, nav, ow, svc, battle, catch, policy, row,
                      route3, route4, in_cave_resume, h)


def stage_moon(b, reader, nav, ow, svc, battle, catch, policy, row,
               route3, route4, in_cave_resume, h=None) -> bool:
    """Stage D: enter Mt. Moon and explore by warps until we pop out on Route 4
    EAST of the dividing wall. Every guard in here paid for itself live —
    see the inline citations before touching anything."""
    h = h or _NoHooks()
    h.phase("p4_moon", "Entering Mt. Moon")
    # the cave mouth = a non-Center warp on Route 4 west
    cave = nav.current_map() if in_cave_resume else None
    for w in ([] if in_cave_resume else nav.map_warps_full()):
        dest = (w["destGroup"], w["destMap"])
        if row and dest == tuple(row["map"]):
            continue
        if not nav.go_to((w["x"], w["y"] + 1), attempts=8):
            continue
        if nav.take_warp((w["x"], w["y"])) is None:
            b.press_button_held("UP", 32)
            time.sleep(1.0)
        if nav.current_map() != route4:
            cave = nav.current_map()
            break
        # not the cave; if we entered the center, step back out
        if nav.current_map() != route4:
            leave_building_safe(b, nav)
    if cave is None:
        return _fail(h, "p4_moon", "could not find the Mt. Moon entrance")
    _say(f"MT. MOON entered: {cave}")
    h.phase("p4_moon", "Exploring Mt. Moon by warps")
    ow.wait_control(10)

    fossil = None
    visited = _load_visited(VISITED_PATH)
    if visited:
        _say(f"  visited map loaded: {len(visited)} warp entries")

    def save_visited():
        _save_visited(VISITED_PATH, visited)

    def mark_arrival_warp():
        """Pre-count the warp we just arrived on so hops prefer FORWARD doors
        (hop #1 took the entrance right back outside, live 2026-07-05)."""
        m2 = nav.current_map()
        px, py = nav.vision.player_xy()
        ws = nav.map_warps_full()
        if not ws:
            return
        w = min(ws, key=lambda t: abs(t["x"] - px) + abs(t["y"] - py))
        if abs(w["x"] - px) + abs(w["y"] - py) <= 2:
            visited[(m2, w["x"], w["y"])] = visited.get(
                (m2, w["x"], w["y"]), 0) + 2

    repel_last = {"t": 0.0}

    def repel_tap():
        """Use a REPEL from the bag (FRLG cannot SELECT-register normal
        items - probed 2026-07-06). Deterministic by construction:
        START cursor was left on BAG (hand session convention), the bag
        reopens on its last pocket (normalized LEFT x2 -> ITEMS), the items
        list does NOT wrap at the top (probed), so UP x6 pins MOON STONE
        and one DOWN lands REPEL while the Moon Stone stays in the bag.
        Submenu opens with the cursor on USE. Wasted taps when out of
        repels just open/close menus; B-cleanup handles every path."""
        if reader.count_item(ITEM_REPEL) <= 0:
            return
        if time.time() - repel_last["t"] < 240:
            return                          # ~100 steps at crawl pace; do
                                            # not stack-waste the stock of 5

        def pace(t=0.5):
            time.sleep(t)

        # START-menu cursor RAM (EWRAM-diff solved 2026-07-06, two mirrors
        # both verified). The menu WRAPS, so blind normalization is impossible
        # - read the cursor and walk it to BAG (2) exactly.
        def cursor() -> int:
            return b.read_range(START_CURSOR_ADDR, START_CURSOR_ADDR + 1)[0]

        def attempt() -> bool:
            count0 = reader.count_item(ITEM_REPEL)
            ow.wait_control(6)              # entry transitions eat START
            b.tap("START", 8); pace(1.2)
            k0 = cursor()
            # the static persists while the menu is CLOSED - prove it is
            # live by moving it one step and watching it follow
            b.tap("DOWN", 5); pace(0.35)
            k = cursor()
            if k != (k0 + 1) % MENU_LEN:    # menu not open (stale byte)
                b.tap("B", 5); pace(0.5)
                return False
            downs = (BAG_INDEX - k) % MENU_LEN
            for _ in range(downs):
                b.tap("DOWN", 5); pace(0.35)
            if cursor() != BAG_INDEX:       # drifted: bail cleanly
                b.tap("B", 5); pace(0.5)
                return False
            b.tap("A", 6); pace(1.8)        # open BAG (slow animation)
            b.tap("LEFT", 5); pace(0.5)
            b.tap("LEFT", 5); pace(0.5)     # -> ITEMS pocket
            for _ in range(6):
                b.tap("UP", 5); pace(0.3)   # pin to top (no wrap - probed)
            b.tap("DOWN", 5); pace(0.4)     # -> REPEL
            b.tap("A", 6); pace(0.8)        # submenu (cursor on USE)
            b.tap("A", 6); pace(1.5)        # USE -> message, menus close
            # GENEROUS cleanup: an under-closed bag ate 18 minutes of
            # "walking" presses live 08:31-08:50 (the "lingered" message
            # ate a B and the bag stayed open through the whole approach).
            # Max menu depth here is 4; 8 settled B's cannot leave one up.
            for _ in range(8):
                b.tap("B", 5); pace(0.6)
            return reader.count_item(ITEM_REPEL) < count0

        used = attempt()
        if not used:
            pace(1.5)
            used = attempt()                # one retry (timing hiccups)
        if used:
            repel_last["t"] = time.time()   # gate only on SUCCESS
        _say(f"  repel: {'ACTIVE' if used else 'use FAILED'} "
             f"({reader.count_item(ITEM_REPEL)} left)")

    mark_arrival_warp()
    repel_tap()
    sticky: dict = {}
    deadline = time.time() + 3600

    # interrupt_check: walk_to/take_warp2 call this when a press is eaten
    # with the position frozen. Battle first (assume_locked - the walker
    # already proved the freeze, so no LEFT/RIGHT jiggle), then bounded B
    # taps for boxes/menus (safe in every state: they advance battle intros,
    # close bags, decline prompts, no-op in the overworld).
    def interrupt_check() -> bool:
        res = policy.handle(assume_locked=True)
        if res:
            _say(f"  [interrupt] {res}")
            return True
        for _ in range(4):
            b.tap("B", 5)
            time.sleep(0.4)
        return True  # optimistic: walk_to's own caps bound the retries

    while time.time() < deadline:
        # ORDER (nav audit 2026-07-06): battle FIRST - wait_control's
        # terminal-box probe taps A, which commits FIGHT if a battle menu is
        # up, and repel_tap would feed START/B into the battle.
        res = policy.handle()
        if res:
            if res.startswith("trainer:win") and fossil is None:
                fossil = try_fossil(b, nav, ow, reader)
            continue
        # then clear any lingering plain message box ("REPEL's effect wore
        # off" freezes movement; the move-learning-modal lesson's cousin)
        ow.wait_control(3)
        # refresh the repel every iteration, not just on landings: a long
        # approach outlived its repel and drowned in a 22-min flee loop
        # (live 09:12-09:30). The 240s gate + count guard keep this cheap.
        if nav.current_map()[0] == 1:
            repel_tap()
        m = nav.current_map()
        if m[0] == 3:
            px = nav.vision.player_xy()[0]
            _say(f"back outside at {m} x={px}")
            if m == route4 and px >= EAST_X:
                break   # genuinely out the EAST side (B1F door lands x~32)
            # popped back out the west side: re-enter and keep exploring
            _say("  west-side exit - re-entering the cave")
            for w in nav.map_warps_full():
                dest = (w["destGroup"], w["destMap"])
                if row and dest == tuple(row["map"]):
                    continue
                nav.take_warp2(w, interrupt_check=interrupt_check)
                if nav.current_map()[0] != 3:
                    ow.wait_control(8)
                    mark_arrival_warp()
                    break
            continue
        if reader.read().all_party_fainted:
            _say("BLACKOUT in Mt. Moon - riding out + re-entering")
            h.phase("p4_moon", "Blacked out in Mt. Moon - respawning and re-entering")
            battle.ride_out_end(button="A", cap=80)
            continue
        # NO per-iteration try_fossil: it interacted with every nearby NPC
        # (3 interacts + 30 A-mashes) on EVERY hop iteration - the silent
        # 10-minute sink in every run tonight (found 08:12). The fossil is
        # a later pass; only a trainer win warrants a pickup sweep here.
        # explore by warps: least-visited first AMONG REACHABLE ones. Cave
        # floors are DISCONNECTED POCKETS (live 04:43-04:45: three straight
        # hop picks in other pockets burned ~70s each on doomed walks), so
        # one flood-fill from the player gates the candidate list. Route-4
        # doors on any floor but B1F land on the WEST shelf (probed
        # 2026-07-06) - never hop them; the B1F -> (32,5) door is the ONLY
        # true east exit, so on B1F force it the moment it is reachable.
        warps = nav.map_warps_full()
        if not warps:
            break
        try:
            walk = nav.vision.nav_grid()["walk"]
            seen = {nav.vision.player_xy()}
            frontier = list(seen)
            while frontier:
                fx, fy = frontier.pop()
                for nx, ny in ((fx, fy + 1), (fx, fy - 1),
                               (fx + 1, fy), (fx - 1, fy)):
                    if (nx, ny) in walk and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        frontier.append((nx, ny))

            def touchable(t):
                return any(nb in seen for nb in
                           ((t["x"], t["y"] + 1), (t["x"], t["y"] - 1),
                            (t["x"] + 1, t["y"]), (t["x"] - 1, t["y"])))
            here = [t for t in warps if touchable(t)]
            warps = here or warps
        except Exception:
            pass  # grid hiccup: fall back to the unfiltered list
        if m == (1, 2):
            outward = [t for t in warps if t["destGroup"] == 3]
            if outward:
                _say("  B1F east-exit door reachable - taking it")
                warps = outward
        else:
            inner = [t for t in warps if t["destGroup"] != 3]
            warps = inner or warps
        # STICKY TARGET: keep walking at the same warp until it fires or
        # 5 GENUINE failures (no_fire/unreachable). Battle/menu-interrupted
        # attempts do NOT count (nav audit: counting them punished the
        # correct door for encounter density on its approach - the live
        # 05:05-05:27 30-min B2F pattern).
        sticky_key = sticky.get("key") if sticky.get("map") == m else None
        if sticky_key is not None and sticky.get("tries", 0) < 5:
            w = next((t for t in warps
                      if (t["x"], t["y"]) == sticky_key), None)
            if w is None:
                sticky_key = None
        if sticky_key is None:
            warps.sort(key=lambda w: (visited.get((m, w["x"], w["y"]), 0),
                                      abs(w["x"] - nav.vision.player_xy()[0])
                                      + abs(w["y"] - nav.vision.player_xy()[1])))
            w = warps[0]
            sticky.update(map=m, key=(w["x"], w["y"]), tries=0)
        _say(f"  cave hop: {m} warp ({w['x']},{w['y']}) -> "
             f"({w['destGroup']},{w['destMap']}) "
             f"[seen {visited.get((m, w['x'], w['y']), 0)}x"
             f" try {sticky.get('tries', 0) + 1}]")
        # take_warp2 owns the whole approach (plan-length neighbour choice,
        # resume-across-battles walking, geometry-guarded final press) -
        # the old go_to_fighting pre-walk doubled encounter exposure
        status = nav.take_warp2(w, interrupt_check=interrupt_check)
        _say(f"    -> {status}")
        ow.wait_control(8)
        if nav.current_map() != m:
            visited[(m, w["x"], w["y"])] = visited.get((m, w["x"], w["y"]), 0) + 1
            sticky.clear()
            mark_arrival_warp()
            save_visited()
            repel_tap()
        elif status in (nav.WARP_NOFIRE, nav.WARP_UNREACHABLE):
            sticky["tries"] = sticky.get("tries", 0) + 1
            if sticky["tries"] >= 5:
                # give up on this door for now; it re-enters the pool later
                visited[(m, w["x"], w["y"])] = (
                    visited.get((m, w["x"], w["y"]), 0) + 1)
                sticky.clear()
                save_visited()
        # interrupted/wrong-map outcomes do not burn tries or visits
    else:
        return _fail(h, "p4_moon", "Mt. Moon budget exhausted")
    _say(f"MT. MOON cleared; fossil item id: {fossil}; bag {bag_all(reader)}")
    h.phase("p4_moon", f"Mt. Moon cleared (fossil {fossil})")
    h.done_task("p4_moon")
    return stages_east(b, reader, nav, ow, svc, battle, catch, policy,
                       route3, route4, fossil, h)


def stages_east(b, reader, nav, ow, svc, battle, catch, policy,
                route3, route4, fossil, h=None) -> bool:
    """Stages E+F: Route 4 east -> Cerulean, then the Cerulean Center heal
    (the fact that gates the whole part)."""
    h = h or _NoHooks()
    _say("=== stage E: Route 4 east -> Cerulean ===")
    h.phase("p4_east", "Heading east down Route 4 toward Cerulean")
    # The east side is a downhill run (walkthrough: "head east -> downhill
    # to Cerulean"): alternate EAST/SOUTH legs. Insurance: SOUTH off Route 4
    # WEST drops through the map seam onto Route 3's dead-end corner (live
    # 2026-07-06) - if that ever happens, recover NORTH instead of legging.
    city = None
    for leg in range(12):
        m = nav.current_map()
        if m == route3:
            _say(f"Route 4 east leg {leg + 1}: dropped onto Route 3 - recovering NORTH")
            cross_edge(b, nav, ow, reader, policy, None, "NORTH", budget=300, narrate=_say)
            continue
        d = "EAST" if leg % 2 == 0 else "SOUTH"
        _say(f"Route 4 east leg {leg + 1}: crossing {d} from {nav.vision.player_xy()}")
        cross_edge(b, nav, ow, reader, policy, None, d, budget=300, narrate=_say)
        m = nav.current_map()
        if m[0] == 3 and m not in (route3, route4, PEWTER):
            city = m
            break
    if city is None:
        return _fail(h, "p4_east", f"did not reach a new city: {nav.current_map()}")
    _say(f"CERULEAN = {city}")
    h.done_task("p4_east")

    _say("=== stage F: Cerulean Center ===")
    h.phase("p4_cerulean", "Looking for the Cerulean Pokemon Center")
    # fact gate: a known row means a prior run already RAM-verified this
    # Center - heal via the recorded geometry instead of re-hunting doors
    row = CENTERS.get(city)
    if row:
        _say(f"Center already known: {row}")
        if not svc.heal_at_center(city):
            return _fail(h, "p4_cerulean", "known-Center heal not confirmed")
    else:
        row = discover_center(b, nav, ow, svc, reader, city)
        if not row:
            return _fail(h, "p4_cerulean", "Cerulean Center not confirmed")
    s = reader.read()
    d = reader.read_party_details()
    _say(f"PASS - Cerulean reached + healed ({s.party_total_hp}/{s.party_total_max_hp}); "
         f"levels {[m['level'] for m in d]}; fossil {fossil}")
    h.phase("p4_cerulean", "Cerulean Center reached and healed - Part 4 complete")
    h.done_task("p4_cerulean")
    return True
