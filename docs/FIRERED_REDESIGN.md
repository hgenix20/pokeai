# pokeai → FireRed — Target Architecture & Migration Design

> **Status:** Design, partially built, with one big deviation. Written
> 2026-06-16; status updated 2026-07-03. **The platform changed:** instead of
> mGBA/PyGBA in Docker, production runs **BizHawk (EmuHawk) natively on
> Windows** via `bizhawk/ai_bridge.lua` + `emulator/bizhawk_bridge.py`
> (TCP 51055). Reasons: native Windows (no container/socket split for
> streaming), built-in Lua scripting, and CrowdControl supports BizHawk
> directly. The mGBA spike (§1) succeeded and `mgba_wrapper.py` is kept
> dormant; the brain is emulator-agnostic so it runs on either backend.
> Current-stack map: `ARCHITECTURE.md` §0. Live plan: `docs/ROADMAP.md`.
> **Pairs with:** `docs/Walkthrough-notes-to-fix.md` (the annotated storyline
> working copy; supersedes `Pokemon-FireRed-Walkthrough.md` as the build
> source), `docs/AGENT_ROOTS.md` (human priors), and
> `docs/Native-Stream-Operator.md` (the Twitch bot layer, phases B0-B5).

This is a design doc, not a changelog. It is meant to be buildable: schemas,
seams, file paths, and gates are concrete. Nothing here is implemented yet.

---

## 0. What changes, in one paragraph

We move the game from **Pokémon Red (Game Boy, PyBoy)** to **Pokémon FireRed
(Game Boy Advance, mGBA)**, and we invert the agent. Today an RL-shaped reward
drives moment-to-moment movement, which is why the agent earns reward while
oscillating between tiles. The new agent is a **symbolic player** that pursues a
**persistent, prioritized task queue** (with dependencies) built from the
walkthrough storyline, executes those tasks through a library of **callable game
skills** (buy item, search for a Pokémon, use a field move, heal, navigate),
**sees** the map through a hybrid RAM+vision layer that is authoritative for
navigation, and uses **reinforcement learning only at the meta level**: deciding
*which task matters now and with what parameters*, including adapting to
**CrowdControl disruptions it detects but was never told about**.

---

## 1. The constraint that drives the rewrite

**PyBoy cannot run a `.gba` file.** It is a Game Boy / Game Boy Color emulator.
The current build also depends on Gen-1-only PyBoy conveniences that have **no
GBA equivalent**:

- `game_area()`, `game_area_collision()`, `get_sprite()` (Gen-1 game wrapper).
- The `wTileMap` (0xC3A0) / `wGrassTile` (0xD535) RAM decode in
  `emulator/screen_reader.py`.
- Every address in `emulator/state_reader.py` (Gen-1 WRAM map).
- The `pyboy.sound.ndarray` audio path in `emulator/pyboy_wrapper.py`.

FireRed (Gen 3) keeps its working state in **EWRAM (`0x02000000+`)** with a
completely different layout, documented by the `pret/pokefirered` disassembly and
community RAM maps. So the project's "swap only `pyboy_wrapper.py`" rule does
**not** hold: the whole emulator + state + perception base is rebuilt. The
control loop, config, evaluation, planner, and most agent *logic* survive (see
§10).

### 1.1 Chosen platform: mGBA via PyGBA

- **Emulator:** mGBA (cycle-accurate enough, headless-capable, full RAM access).
- **Binding:** **PyGBA** (`pip install pygba`), a Gymnasium-style wrapper around
  libmgba designed for AI agents, or `libmgba-py` directly. Precedent exists:
  `NousResearch/pokemon-agent` runs GB via PyBoy and **FireRed via PyGBA**.
- **Risk (now measured, 2026-06-16):** the `mgba` Python binding `pygba` needs
  has **no PyPI distribution on any platform** (`pip index versions mgba` →
  "No matching distribution found"); `pygba` itself is a 16 KB pure-Python wheel
  that just wraps `mgba.core` / `mgba._pylib` (CFFI). `libmgba-py` also ships
  **no prebuilt Windows wheel** — it builds from source (`build_win64.bat`, needs
  Visual Studio). And this machine has **neither CMake nor Visual Studio
  installed** (checked: `cmake` not found, `vswhere` not found). So a native
  Windows binding requires installing VS Build Tools + CMake first, then a C
  build. **Docker Desktop + WSL2 are present** (a `docker-desktop` WSL2 distro
  exists), which is the reliable build path. This is **Milestone 0** (§13) and
  the topology fork below.

- **Topology options (decision needed):**
  - **(A) Docker/WSL core (recommended to validate now):** build/run mgba+pygba on
    Linux via the already-installed Docker. Fastest to a green Milestone 0 with no
    VS install. For production streaming, run the headless emulator core in
    WSL/Docker and either render the UI via WSLg or keep the pygame dashboard
    **native on Windows** talking to the core over a thin local socket (the
    `EmulatorWrapper` seam becomes a client). The socket split is clean because
    the emulator is headless anyway (we render frames ourselves).
  - **(B) Native Windows build:** install Visual Studio Build Tools + CMake, build
    `libmgba-py` from source. Best for OBS/streaming (everything native), but a
    multi-GB install + an error-prone C build on a 16 GB machine.
  - The spike `scripts/spike_mgba.py` is written and platform-agnostic; it runs
    the moment `import mgba` works under either topology.

### 1.2 Milestone 0 acceptance (before any architecture work)

A 30-line spike, not the real wrapper, must prove all of:

1. Load `roms/Pokemon_FireRed.gba` headless under mGBA/PyGBA.
2. Read EWRAM bytes (confirm we can fetch the player map/x/y).
3. Press buttons and advance N frames; observe x/y change.
4. Grab the framebuffer as an RGB array.
5. Save and load a save state.

Until Milestone 0 is green, everything below is theory. The rest of this doc
assumes it passes.

**RESULT — GREEN (2026-06-16).** All 5 checks pass against
`roms/Pokemon_FireRed.gba` (header title `POKEMON FIRE`, code `BPRE` = FireRed
US). Run via Docker (`docker/Dockerfile.mgba` + `scripts/spike_mgba.py`); the
intro renders correctly (`states/spike/02_after_input.png` shows Oak's tutorial
text), EWRAM reads, input changes screen+RAM, and save/load raw state works. The
reproducible build recipe (Ubuntu 22.04, mgba 0.10.3 from source) required four
fixes, all captured in the Dockerfile: (a) `-DUSE_LIBZIP=OFF -DUSE_MINIZIP=OFF`
(Ubuntu 22.04 `libzip-dev` cmake config is broken, no `libzip-tools` pkg);
(b) copy the built `mgba` package from the build tree onto `sys.path` (mgba's
`make install` leaves it behind); (c) **`-DUSE_FFMPEG=ON`** + its dev libs (the
`EReaderScanLoadImage*` exports the cffi cdef binds live inside `#ifdef
USE_FFMPEG` in `ereader.c`, so with FFMPEG off the bindings fail to load with
`undefined symbol: EReaderScanLoadImageA`); (d) `pip install cached_property`
(mgba's Python package needs it). Best-effort player-coord read returned (0,0)
because the spike only boots to the intro; exact EWRAM offsets are an F1 task.

---

## 2. Design goals (your six asks → where they live)

| Goal | Lands in |
|---|---|
| Run FireRed, not Red | §4 platform, §5 state/vision |
| Stop checking every tile / dumb play | §5 vision-authoritative nav, §6 task queue |
| Callable components (buy item, find Pokémon) | §7 Skills |
| Storyline-driven play to kill loops | §8 Story driver |
| Running prioritized task queue with deps | §6 Planner |
| RL on complex meta-tasks, not D-pad | §9 Meta-RL |
| CrowdControl as an engaging feature | §9 Disruption detection + §10 UI |
| Better UI for viewers | §10 UI revamp (built alongside) |

### 2.1 The core inversion

```
OLD:  reward(state delta)  ->  RL policy  ->  button every step
NEW:  story + roots + meta-RL  ->  TASK QUEUE  ->  pick active task
      active task  ->  SKILL (resumable)  ->  button this step
      vision is authoritative for movement; RL never presses a button
```

RL is demoted from "the player" to "the producer": it decides *what's worth
doing* and *adapts to chaos*, while deterministic skills do the playing. This is
what makes the agent look like it is *learning to play well* instead of
twitching for novelty reward.

---

## 3. Architecture overview

```
                         ┌───────────────────────────────────────────┐
                         │            training/loop.py: run()          │  (kept)
                         │   reset → (pump → plan → act → step)* → log  │
                         └───┬───────────────┬──────────────────┬──────┘
                             │               │                  │
                    Planner  │       monitor │ (Dashboard v4)    │ env
                             ▼               ▼                  ▼
                  planner/ (NEW)        ui/ (revamped)     env/firered_env.py
       ┌─────────────────────────────┐                    Gymnasium step/reset
       │ TaskQueue ← StoryDriver      │                          │
       │           ← NeedsArbiter*    │                          ▼
       │           ← Vision tasks     │                  env/action_controller.py
       │           ← DisruptionMonitor│                          │
       │  MetaPolicy (RL) reorders    │                          ▼
       │  active Task → Skill         │            emulator/mgba_wrapper.py (NEW)
       └──────────────┬──────────────┘                  screen / RAM / audio
                      │ Skill.step() → Action                    │
                      ▼                                          ▼
              skills/ (NEW, resumable)            emulator/firered_state_reader.py (NEW)
              buy_item, find_pokemon,                    EWRAM → GameState
              use_field_move, heal,                              │
              navigate_to, talk_to, ...        perception/vision.py (NEW: RAM collision
                      │                          grid + light CV obstacle typing)
                      ▼                                          │
              brain/world_model.py (kept logic)  ← walkability ──┘
              brain/gamesense.py  (kept logic)
              battle_brain.py     (kept logic, Gen-3 addr update)

  *NeedsArbiter (knowledge/needs) and Roots are reused, but now they ENQUEUE and
   REPRIORITIZE tasks instead of selecting a single action each step.
```

**One env step (new):** `pump` (UI) → Planner picks the active Task → the Task's
Skill returns one `Action` (skills hold their own state, so a multi-step errand
resumes) → env applies it, reads the new FireRed state through vision → the
DisruptionMonitor checks for un-caused changes → metrics/log → repeat.

---

## 4. Platform layer — `emulator/mgba_wrapper.py`

A new `EmulatorWrapper` with the **same public surface** the rest of the code
already calls, so the env/loop/dashboard see no difference:

- `load_state/save_state`, `press_button(_held/_pulse)`, `tick`, `set_speed`,
  `set_frame_hook`, `read_byte`, `read_range`, `screen_rgb`, `audio_samples`,
  `close`.
- **Dropped (no GBA equivalent):** `game_area()`, `game_area_collision()`,
  `visible_sprites()`. Their consumers move to `perception/vision.py` (§5.2),
  which reconstructs the same information from EWRAM + pixels.
- **Input timing:** Gen-1's "hold ~17 frames per tile" and "pulse A on a new
  press edge" facts are PyBoy/Gen-1 specific. FireRed timing must be
  **re-measured** against mGBA (likely different frame counts; running-shoes
  changes walk speed). `press_direction_settle()` (move exactly one tile, then
  settle) is the right pattern to keep; its constants get re-derived.
- **Audio:** mGBA exposes audio buffers differently from PyBoy. The dashboard
  audio path (`ui/audio.py`) is re-pointed at mGBA's buffer; the "save state must
  be captured with sound on" Gen-1 gotcha does not apply, but a new
  sound-capture quirk may. Treat audio as a Phase-2 nicety, not a slice blocker.

Design rule (unchanged in spirit): **mGBA specifics live only in this file.**

---

## 5. State + perception (the biggest rebuild)

### 5.1 `emulator/firered_state_reader.py` — EWRAM → typed state

Re-implements the `GameState` / `BattleState` / `PartyMon` dataclasses (we keep
the *shapes* so downstream code is stable) against **Gen-3 FireRed addresses**.
Sources: `pret/pokefirered` symbol map + community RAM maps. The non-trivial ones:

- **Player:** map bank/number, x/y (object-event 0 coords), facing.
- **Party:** 100-byte `BoxPokemon` + battle stats per slot, and the **Gen-3
  substructure encryption** (the 48-byte data block is XOR-encrypted with the
  personality value + OTID and order-permuted by `PV % 24`). The reader must
  decrypt to get species/moves/PP/level. This is the single fiddliest item and
  gets its own probe script + unit tests with known captured blocks.
- **Money:** stored XOR-obfuscated with a security key in `SaveBlock2`; decode it.
- **Badges, event flags:** Gen-3 flag array (different base + width than Gen-1's
  176 bytes). Event flags are how we detect story-step completion (§8), so this
  is load-bearing.
- **Battle:** in-battle flag, active/enemy mon HP fraction / level / types /
  status. Re-verify live with a probe (the Red build learned the hard way that
  cited addresses lie).
- **Bag:** item ids + counts (also obfuscated with the security key). Needed for
  "buy antidote" success detection and ball selection.

Everything here is verified with a new `scripts/probe_firered_ram.py` against the
real ROM, the way the Red build verified battle/menu signatures.

**Probe findings (2026-06-16, FireRed BPRE):**
- **VERIFIED — money chain.** `gSaveBlock1Ptr@0x03005008`, `gSaveBlock2Ptr@
  0x0300500C`, `money = u32@(SB1+0x0290) ^ u32@(SB2+0x0F20)` decodes to a stable
  **3000** (FireRed's starting money) across many frames even as the raw word and
  the security key both change — a stable XOR over varying operands is proof.
- **VERIFIED — save blocks relocate every frame.** `gSaveBlock1/2Ptr` change
  continuously, so all SaveBlock reads MUST go through the pointer indirection
  (never a fixed absolute address). This is FireRed anti-tamper behaviour.
- **Gen-3 struct insight:** a party slot's **level (slot+0x54), current HP
  (+0x56), max HP (+0x58)** are in the UNENCRYPTED battle-stats region — the
  agent's key fields need no PV-decryption. Only species/moves (the encrypted
  growth/attacks substructures, key = PID^OTID, order = PID%24) require it.
- **Candidates pending live verification** (need a starter + controlled movement,
  a later F1 step): `gPlayerParty@0x02024284`, `gPlayerPartyCount@0x02024029`,
  player x/y, badge flags (`SB1` flags region), `current_map`. The probe's
  `scan_u*` helpers pin any that disagree once a known state is reached.

### 5.2 `perception/vision.py` — hybrid, authoritative-for-navigation

This replaces PyBoy's collision grid. **Two layers:**

**(a) RAM collision grid (primary).** FireRed keeps the loaded map's metatile
grid and per-metatile collision/behavior in EWRAM. We decode a walkability grid
centered on the player (the agent's "minimap"), plus tile *behavior* (normal,
tall grass, water, ledge-down, warp, door). This is exact and cheap, and it is
**authoritative**: the pather never routes into a cell the grid marks blocked,
which directly fixes "it sees the wall and walks into it anyway." Bump-and-learn
becomes a fallback for the rare unmapped case, not the primary mechanism.

> **BUILT + VERIFIED (2026-06-16).** `perception/vision.py` (`FireRedVision`)
> reads the live collision grid from `gMapHeader@0x02036DFC -> MapLayout
> {width,height,map}`; each map `u16` = metatile(0-9) | collision(10-11) |
> elevation(12-15); walkable <=> collision==0. Cross-validated live (the player's
> UP-blocked direction = collision WALL; others walkable) and against a
> screenshot; 5 ROM-free unit tests. v1 emits WALKABLE/WALL/UNKNOWN; GRASS/WARP/
> NPC (metatile-behavior + object-event scan) are the next F2 sub-steps.

**(b) Light CV obstacle typing (secondary).** Some cells are "blocked **for now**"
and become passable via a field move. RAM behavior bytes already distinguish many
of these (cuttable tree, rock-smash rock, strength boulder, surfable water,
waterfall), so the first implementation is RAM-only template logic. The **CV**
piece is a thin classifier (template-match first, a tiny CNN only if needed) over
the tile *in front of the player* to confirm/disambiguate the obstacle type and
to give viewers a real "the AI is looking at this tree" overlay. A typed obstacle
emits a **dependency task** (§6.3): facing a cuttable tree on the only path →
`UseFieldMove(cut)`, which depends on `ObtainHM(cut)` + `TeachMove(cut, mon)`.

**Output contract** (so `world_model.py` / `gamesense.py` keep working): the same
18×20-ish `semantic_tiles()` grid of `TileClass` codes the brain already
consumes, extended with new classes: `WATER`, `LEDGE`, `WARP`, `CUTTABLE`,
`BOULDER`, `WATERFALL`. `WorldModel` BFS gains "passable-if-skill-X" edges.

### 5.3 `perception/screen_reader.py` — GBA text/menus

The Gen-1 `wTileMap` character decode is gone. FireRed text rendering is
different (and font/tile based). Two options, decided at build time:

- **RAM text buffers** if a stable on-screen text mirror exists in EWRAM
  (preferred: deterministic, testable with the mock).
- **OCR/template** over the dialogue/menu region as a fallback.

The `ScreenContext` machine (FREE_ROAM / DIALOGUE / MENU / BATTLE) and the
`ScreenView` contract are **kept**, so `brain_agents.py`'s dialogue/menu handling
survives. Menu-cursor detection (which row the ▶ points at) is re-derived for
FireRed menus, which the buy/heal skills depend on.

---

## 6. The Planner — task queue with dependencies (`planner/`)

This is the heart of the upgrade and the thing viewers watch. New package.

### 6.1 The `Task` model (`planner/task.py`)

```python
class TaskKind(Enum):
    ADVANCE_STORY      # do the current walkthrough step
    NAVIGATE_TO        # reach map/coords (params: map_id | landmark)
    FIND_POKEMON       # encounter+catch a species (params: species, where?)
    EARN_MONEY         # reach a money floor (params: amount)
    BUY_ITEM           # purchase N of an item (params: item, qty)
    HEAL               # restore party (Center or items)
    USE_FIELD_MOVE     # cut/surf/strength/etc at a target tile
    OBTAIN_HM          # acquire an HM (params: hm)
    TEACH_MOVE         # teach a move to a party mon
    DEFEAT_TRAINER     # beat a specific/blocking trainer
    GRIND_TO_LEVEL     # train party to a level floor (params: level)
    RECOVER            # respond to a detected setback (often disruption-spawned)

class TaskStatus(Enum):
    PENDING; ACTIVE; BLOCKED; DONE; FAILED; ABANDONED

@dataclass
class Task:
    id: str
    kind: TaskKind
    params: dict
    base_priority: float                 # from story/roots
    priority: float                       # live, after meta-RL reweight
    status: TaskStatus
    depends_on: list[str] = []            # must be DONE before this runs
    source: str                           # story | roots | vision | disruption | crowd
    progress: float = 0.0                 # 0..1 for the UI
    note: str = ""                        # human text for the UI / thought bubble
    # callables (pure over state):
    def satisfied(self, state) -> bool    # success predicate (auto-DONE)
    def still_relevant(self, state) -> bool  # else auto-ABANDON
```

A task is **resumable** because its *Skill* (§7) holds the partial progress, not
the task. `BUY_ITEM(antidote, 2)` stays ACTIVE across the walk to the Mart, the
menu navigation, and the purchase; `progress` and `note` drive the UI ("at the
Mart counter, buying 2× Antidote").

### 6.2 `planner/task_queue.py`

- `enqueue(task)` — dedupes by `(kind, frozenset(params))`; raises priority if a
  duplicate is requested rather than adding twice.
- `active()` — the highest-`priority` task whose `status == PENDING/ACTIVE`, whose
  deps are all `DONE`, and whose `still_relevant(state)` holds. Blocked-by-deps
  tasks are skipped (shown as BLOCKED in the UI).
- `tick(state)` — every step: mark `satisfied` tasks DONE (cascade-unblock
  dependents), abandon irrelevant ones, recompute priorities.
- `reprioritize(meta_weights)` — the meta-policy (§9) nudges `priority` from
  `base_priority` using learned context weights.

### 6.3 Dependency expansion

When the active task cannot start because a precondition is missing, the Skill
returns a `Needs(...)` signal instead of an action, and the planner **spawns
dependency tasks**, sets the parent `BLOCKED`, and re-picks:

```
UseFieldMove(cut)  needs HM01 known by a party mon
   → spawn TeachMove(cut, best_mon)         depends_on: ObtainHM(cut)
   → spawn ObtainHM(cut)  (story: SS Anne / Capt.)  → which itself may
        spawn AdvanceStory(<the step that grants it>)
BuyItem(antidote, 2)  needs money >= cost and a known Mart
   → spawn EarnMoney(cost)    (if short)
   → spawn NavigateTo(<nearest Mart>)
```

This is the literal mechanism behind your example: "new task: use Cut →
dependency task: find/teach Cut." It also keeps the queue honest: nothing runs
until its prerequisites are DONE.

### 6.4 Where tasks come from

- **StoryDriver (§8):** always keeps exactly one `ADVANCE_STORY` task = the
  current walkthrough step. Highest base priority by default, so the agent makes
  forward progress and **loops collapse**: when navigation has wandered with no
  story progress for K steps, the planner re-asserts the story task and routes to
  its location (this is the loop-killer you asked for).
- **NeedsArbiter (reused, `knowledge/roots.py` + arbiter):** the existing drives
  (survive/rest-before-gym/shop/train) now **enqueue** `HEAL`, `BUY_ITEM`,
  `GRIND_TO_LEVEL` tasks with priorities, instead of returning one action.
- **Vision:** typed obstacles on the active path enqueue `USE_FIELD_MOVE` chains.
- **DisruptionMonitor (§9):** detected setbacks enqueue `RECOVER` tasks.

---

## 7. Skills — the callable game components (`skills/`)

A **Skill** is a small resumable state machine that executes one task kind. This
is your "components of the game we can call." Public contract:

```python
class Skill(Protocol):
    def reset(self, task: Task, ctx: Context) -> None
    def step(self, state, view, vision) -> SkillResult
        # SkillResult = Action(a) | Needs(task_specs) | Done | Failed(reason)
    progress: float
    note: str
```

Skills compose: most call **`navigate_to`** then a terminal interaction. They are
the only place that "presses buttons," and they are deterministic and unit-tested
against the mock emulator.

**Initial catalog (build order):**

1. `navigate_to(map|landmark|coords)` — inter-map BFS over learned warps
   (reuse `GameSense.route_toward_map`) + intra-map A* over the vision grid.
   Vision-authoritative. Foundation for everything else.
2. `talk_to(target)` — face an NPC/object, pulse A through dialogue, optionally
   answer a yes/no. (Reuse the brain's interact queue idea.)
3. `heal()` — at a Center, talk to the nurse (free full heal); else `navigate_to`
   nearest known Center first. (Red build already does this; port it.)
4. `buy_item(item, qty)` — `navigate_to` Mart → talk to clerk → drive the BUY
   menu → select item → set quantity → confirm → verify via bag delta. **This is
   the first never-finished executor we actually finish.**
5. `find_pokemon(species, where?)` — `navigate_to` a grass/area where the species
   appears (from a species→location table built off the walkthrough + RAM
   encounter slots) → walk grass until the species appears → weaken → throw best
   ball (reuse `BattleBrain` catch phase machine, Gen-3 bag addresses).
6. `use_field_move(move, target_tile)` — face the obstacle → open menu / use the
   field move → confirm the tile cleared via vision.
7. `defeat_trainer(id|blocking)` / `grind_to_level(n)` — route into the fight(s)
   and let `BattleBrain` win; grind = advance through grass/trainers (not camp a
   patch), reusing the Adventurer's `_go_train` logic.
8. `advance_story(step)` — dispatches to the above based on the step's verb
   (talk / go / get / beat), then waits for the step's expected state delta.

`battle_brain.py` is reused; its type chart (`knowledge/type_chart.py`) needs Gen
1→3 deltas (Dark/Steel types, the Special split, ability/held-item effects can be
ignored at first). Bag/menu RAM signatures re-verified for FireRed.

---

## 8. Story driver from the walkthrough (`planner/story.py`)

`docs/Pokemon-FireRed-Walkthrough.md` is already in a clean, machine-readable
step format (PART → section → numbered steps, with `BATTLE:` / `ITEM:` / `HM/TM:`
/ `NOTE:` tags). We parse it into an ordered list of `StoryStep`s:

```python
@dataclass
class StoryStep:
    id: str                  # "P1.oak.choose_starter"
    part: str; location: str
    verb: str                # talk | go | get | beat | deliver | choose | use
    target: str              # "Oak" | "Route 1" | "Oak's Parcel" | "Brock"
    preconds: list[str]      # event/badge/item flags required to attempt
    completes_when: dict      # the observable delta: {event_flag|badge|item|map}
    note: str
```

The **StoryDriver** tracks the current step, exposes it as the standing
`ADVANCE_STORY` task, and marks it DONE when `completes_when` is observed in the
FireRed state (event flag set, badge gained, item in bag, map reached). Two payoffs:

- **Loop prevention:** if `event_flags_set`/`badge_count` haven't moved in
  `STORY_STALL_LIMIT` steps (the Adventurer already tracks exactly this signal,
  `brain_agents.py`), the planner forcibly re-prioritizes `ADVANCE_STORY` and
  routes to the step's location. The agent stops wandering and goes does the
  story beat.
- **Purpose for viewers:** the UI can show "Chapter 3 of N: Win the Boulder
  Badge" with a real progress bar, because the step list is finite and ordered.

Parsing notes: the walkthrough has `[[Verify]]` / `[[Missing]]` markers and
optional branches (Route 22 optional, fossil choice). The parser tags steps
`optional`/`needs_verify`; the StoryDriver skips optional steps unless a task
requires them, and logs `needs_verify` steps so we can confirm against the ROM.
Starter is randomized per run (your walkthrough says so), so `completes_when` for
the starter step keys on "party_count went 0→1," not a specific species.

---

## 9. Meta-RL + CrowdControl disruption detection (`planner/meta.py`)

This is where RL belongs now, and where the CrowdControl feature lives. Two
cooperating pieces.

### 9.1 DisruptionMonitor — detect un-caused change (no injection)

Per your constraint: CrowdControl effects are **not** announced to the agent. So
the agent maintains a **self-model**: given the action it issued this step, what
state delta did it expect? Each step the monitor diffs *expected* vs *actual* and
flags **anomalies the agent did not cause**:

| Signature (actual vs expected) | Inferred disruption |
|---|---|
| Position jumps >1 tile with no move issued / map changes unexpectedly | Teleport / warp |
| Party HP drops with no battle and no poison tick due | Forced damage |
| A wild battle starts while standing still / off-grass | Forced encounter |
| Money or a bag item changes with no shop/pickup event | Economy tamper |
| Issued a move action repeatedly, position never changes, tile is walkable | Input freeze / inversion |
| Party composition changes outside a catch/evolution | Roster tamper |

Each flagged event has a `type`, `magnitude`, and `timestamp`. The monitor is
pure logic over consecutive `GameState`s + the issued action, so it is fully
unit-testable with the mock (feed two snapshots, assert the detected type).

On detection it does three things:
1. **Thought bubble:** sets an over-the-character bubble ("Hey, who moved me?!",
   "My Antidotes are gone?!") rendered by the UI (§10). This is the engagement.
2. **Reactive floor:** may enqueue a `RECOVER` task (re-locate, re-heal,
   re-buy) so the agent never softlocks even before it has "learned."
3. **Meta signal:** emits a **negative event** into the meta-policy's experience
   with full context (where, what task was active, what type).

### 9.2 MetaPolicy — RL over task selection/parameters

A small **contextual policy** (start with a contextual bandit / linear or tiny
MLP; not a from-scratch deep RL stack) that learns to **reweight task
priorities** and **set task parameters** from context, optimizing a reward that
finally matches "playing well":

- **Reward (per macro-step / per task outcome):** `+ story step completed`,
  `+ badge`, `- time/steps spent`, `- blackout`, `- disruption setback`
  (HP/money/position lost to a detected disruption), `- backtracking`.
- **Context features:** current route/map, party HP, top level vs next-gym
  recommended level, money, healing-item count, **poison-events-this-route**,
  **recent disruption types/frequency on this map**, story-stall length.
- **What it learns (your examples, now first-class):**
  - "On Route X my party got poisoned ≥2×" → it raises `BUY_ITEM(antidote)`
    priority and **pre-buys** before re-entering similar routes.
  - "This map is chaotic (CrowdControl keeps teleporting me)" → it favors robust,
    short-hop routing and keeps spare potions, lowering the cost of disruptions
    over time. The viewer sees the AI *get harder to grief*, which is the whole
    point.

Because RL only moves priorities/parameters (a tiny action space) and never
presses buttons, it trains fast, can't reintroduce tile-oscillation, and its
decisions are legible ("raised Buy Antidote because Route 3 poisoned me twice").

### 9.3 Why this reads as "really learning"

The dashboard can show, side by side: the task queue reordering, the thought
bubble reacting to a disruption, and a short "lesson" line ("Learned: pre-buy
Antidotes before Route 3"). That triad is far more compelling than a reward
curve, and it is honest: the adaptation is real, just scoped to the meta level.

---

## 10. UI revamp (built alongside) — Dashboard v4

You chose to revamp now, in parallel. Keep the pygame `StepMonitor` shell and the
split-render perf architecture (`ARCHITECTURE.md` §10.1 is still law: per-frame
game repaint cheap, full panel repaint once per step). New/changed panels:

- **TASK QUEUE panel (new, centerpiece):** the live prioritized list, with status
  chips (ACTIVE/BLOCKED/DONE), dependency arrows, and the active task's progress
  bar. This is the "agenda" viewers follow.
- **REASONING feed (new):** a rolling log of planner decisions and meta-RL
  "lessons" ("Story re-asserted: stopped wandering Route 2", "Raised Buy Antidote
  to P1").
- **Thought bubble over the player (new):** the in-game speech bubble for
  disruptions and key decisions, drawn on the game region (cheap, per-frame-safe).
- **CrowdControl reactions panel (new):** recent detected disruptions with the
  AI's response, framed for the audience ("Viewer teleported me → re-routing").
- **VISION overlay (upgraded):** the authoritative walkability grid + typed
  obstacles (highlight a cuttable tree the AI is about to Cut). Makes "the AI is
  seeing" literal.
- **Kept:** HUD, GOALS (now fed by StoryDriver chapters), session ticker, sound,
  manual takeover, view modes, speed control.

If we later want a richer streaming look, a browser/OBS overlay is a separate
workstream (out of scope here); the pygame revamp ships first.

---

## 11. Kept vs rebuilt (the migration map)

| Layer | Disposition |
|---|---|
| `training/loop.py`, `StepMonitor`, `RunControl` | **Keep** (planner plugs into `select_action`/pump seam) |
| `config.py`, `evaluation/*`, `utils/hashing.py` | **Keep**, add planner/meta config blocks |
| `knowledge/roots.py`, `AGENT_ROOTS.md`, `NeedsArbiter` | **Keep**, role shifts to enqueue/reprioritize |
| `knowledge/type_chart.py` | **Keep**, Gen 1→3 deltas |
| `agents/brain/world_model.py` (BFS, anti-loop) | **Keep logic**, feed from new vision; add skill-gated edges |
| `agents/brain/gamesense.py`, `battle_brain.py` | **Keep logic**, re-point at new state/menu addresses |
| `agents/brain_agents.py` | **Refactor**: Adventurer's arbiter/stall logic moves into the planner; brains become skill providers |
| `emulator/pyboy_wrapper.py` | **Replace** → `mgba_wrapper.py` |
| `emulator/state_reader.py` | **Replace** → `firered_state_reader.py` (Gen-3 EWRAM) |
| `emulator/screen_reader.py` | **Replace** → `perception/screen_reader.py` + `perception/vision.py` |
| `env/pokemon_red_env.py` | **Fork** → `env/firered_env.py` (obs now serves the planner, not a DQN vector) |
| RL reward engine (`env/reward_engine.py`) | **Demote**: extrinsic milestone signal feeds MetaPolicy reward; intrinsic curiosity retired as a driver |
| `agents/dqn_agent.py` / PPO | **Already retired**; not ported |
| `ui/dashboard.py` | **Revamp** → v4 panels (§10) |
| Save states, battle/bag RAM signatures, audio path | **Rebuild** for FireRed |

**New packages:** `planner/` (task, task_queue, story, meta, disruption),
`skills/`, `perception/`.

---

## 12. Testing strategy (keep the ROM-free discipline)

The Red build's best property is that pure logic is unit-tested with a
`MockEmulator` serving scripted RAM through the real reader. We keep this:

- **`MockGBAEmulator`** serves scripted EWRAM snapshots through
  `firered_state_reader` (extend `tests/mock_emulator.py`).
- **Planner tests:** enqueue/dedupe/priority, dependency expansion (assert
  `UseFieldMove(cut)` spawns the HM chain and goes BLOCKED), story completion
  cascade.
- **Skill tests:** drive each skill against scripted state sequences; assert it
  reaches `Done` and emits correct `Needs(...)`.
- **DisruptionMonitor tests:** feed (prev, action, next) triples, assert detected
  type/magnitude; assert no false positive on normal play (poison tick, ledge
  hop, legit warp the agent walked into).
- **StoryDriver tests:** parse the walkthrough fixture; assert step ordering,
  optional/needs_verify tagging, and `completes_when` matching.
- **MetaPolicy tests:** deterministic-seed bandit converges on a toy "pre-buy
  antidote" scenario.
- **Probe scripts (real ROM):** `scripts/probe_firered_ram.py` for addresses;
  `scripts/spike_mgba.py` for Milestone 0.

Machine gotchas from `ARCHITECTURE.md` §14 still apply (venv outside OneDrive,
absolute paths in Bash). The torch hang matters less now: meta-RL is small and
can run on CPU/numpy, so we may avoid heavyweight torch on the hot path entirely.

---

## 13. Phased sequence (gates)

> **Milestone 0 — ✅ GREEN (2026-06-16).** mGBA/PyGBA boots FireRed headless with
> RAM + screen + state-load (the §1.2 spike); all 5 checks pass via Docker. The
> emulator runs in a Linux container (`pokeai-mgba` image); the production UI/
> streaming topology (all-WSL vs native-Windows UI over a socket) is deferred to
> F7 and does not block F1–F6.

> **Progress (2026-06-16):** **F1 core ✅** and **F2 navigation core ✅** verified
> live. Built + verified: `mgba_wrapper.py`; `firered_state_reader.py` (money &
> position VERIFIED live; current_map live; party/PV-decrypt unit-tested);
> `perception/vision.py` (live collision grid, authoritative); `perception/
> pathing.py` (BFS); tile-accurate movement (`press_direction_settle`); warp
> navigation + `current_map` live; NPC avoidance (`object_tiles`); `perception/
> navigator.py` (`go_to`/`take_warp`/`leave_building`). **Multi-map navigation
> VERIFIED**: clean-API chain bedroom→1F→Pallet Town. 19 ROM-free FireRed unit
> tests pass on Windows. Remaining F2: GRASS/WARP/LEDGE tile classes via
> metatile-behavior; `screen_reader` text/context machine. Next big unblock:
> reach a starter (Oak cutscene + naming) to verify party/battle live.

> **Progress (2026-07-03):** platform pivoted to BizHawk (see the Status
> header). Starter reached, party verified live, and the FIRST RIVAL BATTLE
> WON on the real game (2026-07-02): Part 1 of the storyline runs end to end
> from the title screen (`scripts/part1_full_test.py`, RAM-gated, savestate
> retry on loss). Phase reality vs this doc's gates: **F1 done** (party/battle
> now live-verified). **F2 core done** (collision grid authoritative;
> GRASS/WARP/LEDGE metatile classes + the screen_reader context machine still
> open). **F3 partial** (navigate_to/talk_to proven in Part 1; heal-at-Center
> not yet). **F4 scaffold** (Task/TaskQueue exist; the StoryDriver/walkthrough
> parser is NOT built; Part 1 was hand-coded, and parser-vs-hand-code is the
> standing decision, tracked as ROADMAP G10). **F5/F6 not started.** **F7
> shipped differently:** web operator/viewer boards (`scripts/stream.py`,
> :8777) instead of pygame Dashboard v4, and the viewer-interaction layer is
> now specced as a Twitch bot (`docs/Native-Stream-Operator.md`, phases B0-B5
> synced to story parts).

| Phase | Deliverable | Gate |
|---|---|---|
| **F1 Platform** | `mgba_wrapper.py` (full surface) + `firered_state_reader.py` core fields (map/x/y/party/badges/money) + `probe_firered_ram.py` | ✅ Read live FireRed pos/money/map correctly; movement changes x/y. (party/badges live-verify pending a starter) |
| **F2 Perception** | `perception/vision.py` RAM walkability grid + `screen_reader` context machine; obstacle typing (RAM) | Walkability ✅ (matches screen + movement; BFS nav + multi-map warps verified). Still: metatile-behavior tile types + screen_reader context machine |
| **F3 Skills core** | `navigate_to`, `talk_to`, `heal` on FireRed | Agent walks Pallet→Viridian and heals at the Center, vision-authoritative (no wall-bumping) |
| **F4 Planner + Story** | `Task`/`TaskQueue`/dependency expansion + `StoryDriver` from the walkthrough; loop-killer | Plays the intro through the first 1–2 story chapters; re-asserts story on stall |
| **F5 Skills depth** | `buy_item` (finish it), `find_pokemon`, `use_field_move` + chains | Buys 2× Antidote end to end; catches a target species; the Cut dependency chain resolves |
| **F6 Meta-RL + Disruption** | `DisruptionMonitor` + `MetaPolicy` + thought bubble | Detects teleport/economy/forced-encounter in tests; demonstrably pre-buys antidotes after repeated route poison |
| **F7 UI v4** | Task-queue + reasoning + CrowdControl + vision panels (built alongside F3+) | Stream-watchable: agenda, reasoning, disruption reactions visible |

Phases F1–F5 are mostly engineering with clear gates. F6 is the research-y,
highest-novelty phase and the one that sells "it's really learning." F7 runs in
parallel from F3 onward so there's always something watchable.

---

## 14. Open decisions / risks to confirm

1. **mGBA Python build on Windows** (the big one). Confirmed only by Milestone 0.
   Fallback = WSL2/container + socket bridge.
2. **Gen-3 substructure decryption** (party/money/bag obfuscation) is the
   fiddliest reader work. Mitigation: dedicated probe + unit tests with captured
   blocks before building skills on top.
3. **Text perception** (RAM mirror vs OCR) decided during F2 by inspecting EWRAM.
4. **Manual takeover / action space:** FireRed wants START + SELECT (menus,
   running shoes). We expand the action set freely now (no DQN checkpoint to
   invalidate). Confirm the controller mapping early.
5. **CrowdControl integration surface:** this design assumes CrowdControl acts on
   the *game* (button injection / memory writes) and the agent only sees in-game
   effects. If CrowdControl can also be read via an API, we keep ignoring that on
   purpose (detection-from-effects is the feature) but could log ground truth to
   evaluate the DisruptionMonitor's precision/recall.
6. **Reward-engine reuse:** confirm we retire intrinsic curiosity entirely vs
   keep a tiny exploration bonus for genuinely-unmapped areas (recommend retire;
   the story task supplies direction).

---

## 15. Glossary deltas (vs `ARCHITECTURE.md`)

- **Skill** — a resumable state machine that executes one task kind by issuing
  button actions; the only "hands on the controller."
- **Task / TaskQueue** — the persistent prioritized agenda with dependencies; the
  agent's intent, made inspectable.
- **StoryDriver** — turns the walkthrough into the standing forward objective and
  kills loops by re-asserting it.
- **DisruptionMonitor** — detects un-caused state changes (CrowdControl) from a
  self-model; the agent is never told a disruption happened.
- **MetaPolicy** — the (small) RL layer that reweights tasks/parameters and adapts
  to disruptions over time. RL's only remaining job.

_Next step after approval: Milestone 0 spike (`scripts/spike_mgba.py`)._
