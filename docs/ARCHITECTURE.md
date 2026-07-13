# pokeai — Architecture & Operations Manual

> A complete reference to how this application works, written so a future
> engineer (or AI assistant) can understand the whole system without re-reading
> every file. Pair this with `README.md` (user-facing quickstart),
> `PHASE1_PLAN.md` (original plan), and, for the CURRENT era, §0 below plus
> `docs/ROADMAP.md`. Last reviewed: 2026-07-03.

---

## 0. Current era (2026-07): FireRed on BizHawk. READ THIS FIRST.

Sections 1-16 document the original **Pokémon Red / PyBoy** framework. That
code still runs, but active development moved to **Pokémon FireRed on BizHawk**
with a symbolic, story-driven player. The FireRed stack:

| Layer | File(s) | State |
|---|---|---|
| Emulator bridge | `bizhawk/ai_bridge.lua` (in EmuHawk) + `emulator/bizhawk_bridge.py` (Python binds TCP 51055; start Python FIRST, then EmuHawk with the Lua script) | live, verified |
| State reading | `emulator/firered_state_reader.py` (SaveBlock pointer indirection, money XOR, unencrypted party battle-stats; species via PV decrypt) | core verified live |
| Perception | `perception/vision.py` (EWRAM collision grid, authoritative), `perception/pathing.py` (BFS), `perception/navigator.py` (warps, clean door exits) | verified live |
| Skills | `skills/overworld.py` (interact / cutscene / starter pick), `skills/navigate_to.py`, `skills/battle.py` (v1 A-mash, RAM verdicts, gEnemyParty @ 0x0202402C) | Part-1 proven |
| Story | `agents/firered_intro.py` + `agents/firered_part1.py` (hand-coded steps), `agents/firered_story.py` (emulator-agnostic brain) | Part 1 complete 2026-07-02: first rival battle WON |
| Planner | `planner/task.py`, `planner/task_queue.py` (StoryDriver / walkthrough parser NOT built yet) | scaffold only |
| Stream ops | `scripts/stream.py` control process: owns the bridge (single owner), operator board `:8777/operator`, viewer board `:8777/viewer`; launcher `run_stream.bat` | live |
| Acceptance | `scripts/part1_full_test.py` (fresh title through rival win, RAM-gated, regenerates save slots 0-2) | passing |
| Twitch bot | `docs/Native-Stream-Operator.md` (spec + phased implementation plan B0-B5, synced to story parts) | spec, not built |

Key facts that differ from the sections below:

- The emulator seam is the **BizHawk bridge**, not `pyboy_wrapper.py`. The mGBA
  wrapper from the redesign spike (`emulator/mgba_wrapper.py`) is retained but
  dormant; see `docs/FIRERED_REDESIGN.md` for what landed vs changed.
- The UI for the FireRed era is the **web operator/viewer boards**, not the
  pygame dashboard (§10), which remains Red-only.
- The roadmap, goal ladder, loop-engineering protocol, and the whole-system
  validation matrix live in `docs/ROADMAP.md`. The story source of truth is
  `docs/Walkthrough-notes-to-fix.md` (built through its `[[STOP]]` marker).
- The repo is NOT under git (no `.git`; a `.gitignore` exists). Savestates and
  docs are the only record until that is fixed (first task in ROADMAP.md).

---

## 1. What this project is

**pokeai** is a modular framework for training and evaluating AI agents that
play **Pokémon Red** (Game Boy) through the **PyBoy** emulator. It is the
software substrate for an experimental cognitive-architecture research program
called **HCQM** (a "Hierarchical Cognitive Capability Model" — see the glossary).
The framework:

- Runs the game headlessly via PyBoy and exposes it as a **Gymnasium**
  environment with a 7-action discrete action space.
- Reads game state directly from emulator **RAM** (party, position, badges,
  battle, etc.) — no pixel/vision model is required for the agent.
- Computes a **reward** from state deltas (extrinsic milestones + HCQM intrinsic
  signals like curiosity and anti-perseveration).
- Supports three agents: `random`, `heuristic`, and a from-scratch PyTorch
  **DQN** learner.
- Logs every episode to JSONL and aggregates a summary + an HCQM "capability
  acquisition profile."
- Ships a rich **pygame dashboard** that doubles as (a) a diagnostic tool and
  (b) a **streaming/manual-play** front-end (sound, manual takeover, live
  strategy switching, goal tracker, clean/stream view modes).

The author uses the dashboard to stream the AI playing across Twitch/TikTok/
YouTube (capturing the window + system audio; overlays are added externally).

---

## 2. Mental model (data flow)

```
                 ┌──────────────────────────────────────────────────────┐
                 │                  training/loop.py: run()              │
                 │   episode loop: reset → (pump → select → step)* → log │
                 └───┬───────────────┬──────────────────┬───────────────┘
                     │               │                  │
        build_agent()│       monitor │ (StepMonitor)    │ env
                     ▼               ▼                  ▼
              agents/*.py      ui/dashboard.py    env/pokemon_red_env.py
              act()/observe()  (pygame window)    Gymnasium step/reset
                                     │                  │
                                     │                  ▼
                                     │         env/action_controller.py
                                     │           (action → buttons)
                                     │                  │
                                     ▼                  ▼
                              emulator/pyboy_wrapper.py (PyBoy)
                                     │            screen/RAM/audio
                                     ▼
                              emulator/state_reader.py (RAM → GameState)
                                     │
                          env/reward_engine.py (+ knowledge/visit_memory.py)
                                     │
                          evaluation/{metrics,logger,aggregate}.py → runs/<id>/
```

**One env step** = the agent picks one of 7 actions; the action controller holds
that button for `frame_skip` (default 24) emulated frames; the state reader reads
the new RAM state; the reward engine diffs it against the previous state; the env
returns `(obs, reward, terminated, truncated, info)`.

**One episode** = repeated steps from the loaded init save-state until all 8
badges (success), a party blackout (failure), `max_steps` (truncation), or a
manual stop. `reset()` always reloads the same init save-state.

---

## 3. Repository layout

```
pokeai/
├── configs/                 # YAML run configs (one per scenario)
│   ├── random.yaml heuristic.yaml dashboard.yaml
│   ├── train_dqn.yaml watch_dqn.yaml watch.yaml
├── roms/                    # Pokemon_Red.gb (user-provided, gitignored)
├── states/                  # save states (init_state*, *_sound, battle_sample)
├── runs/                    # per-run output: episodes.jsonl, run.json, reports
├── scripts/                 # state generators + smoke tests (not shipped)
├── src/pokeai/
│   ├── cli.py __main__.py   # `python -m pokeai run|report`
│   ├── config.py            # pydantic config models (single source of truth)
│   ├── emulator/
│   │   ├── pyboy_wrapper.py  # the ONLY file that knows PyBoy specifics
│   │   └── state_reader.py   # RAM addresses → GameState/BattleState/PartyMon
│   ├── env/
│   │   ├── pokemon_red_env.py   # Gymnasium env, observation assembly
│   │   ├── action_controller.py # 7-action space → button holds
│   │   └── reward_engine.py      # reward from state deltas + HCQM intrinsics
│   ├── agents/
│   │   ├── base.py random_agent.py heuristic_agent.py dqn_agent.py __init__.py
│   ├── knowledge/
│   │   ├── game_data.py      # species/type/status/map lookup tables
│   │   └── visit_memory.py   # per-position visit counts (curiosity/novelty)
│   ├── training/loop.py      # the episode loop + StepMonitor protocol
│   ├── evaluation/
│   │   ├── metrics.py logger.py aggregate.py   # JSONL + reports + HCQM profile
│   ├── ui/                   # the dashboard (pygame)
│   │   ├── dashboard.py run_control.py thoughts.py audio.py goals.py
│   └── utils/hashing.py      # config hash for experiment attribution
└── tests/                   # pytest; mock_emulator.py replaces PyBoy
```

**Design rule:** emulator specifics live ONLY in `emulator/pyboy_wrapper.py`.
Everything downstream talks to `EmulatorWrapper`, so swapping emulators or PyBoy
versions touches one file. Pure-logic modules (`reward_engine`, `visit_memory`,
`thoughts`, `goals`, `run_control`, `state_reader` parsing, `aggregate`) have no
pygame/PyBoy import and are unit-tested with a `MockEmulator`.

---

## 4. The control loop (`training/loop.py`)

`run(config, emulator=None, monitor=None) -> run_dir` is the heart of the app.

1. Hashes the config, makes `runs/<run_id>/`, writes `run.json` metadata.
2. `build_agent(config)` and `PokemonRedEnv(config)`.
3. If `config.ui.enabled` and no monitor passed, builds a `Dashboard` monitor.
4. For each episode: `env.reset()` → `agent.reset()` → `monitor.on_episode_start`.
5. Inner step loop until terminated/truncated:
   ```python
   monitor.pump(last_action, info)          # draws UI; BLOCKS while paused
   if monitor.stop_requested: break          # graceful stop
   if monitor.consume_restart_request(): break  # discard + rerun this episode
   select = getattr(monitor, "select_action", None)
   action = select(obs, agent) if select else agent.act(obs)   # ← override hook
   next_obs, reward, terminated, truncated, info = env.step(action)
   agent.observe(obs, action, reward, next_obs, terminated)    # learning hook
   ```
6. Writes a `RunMetrics` row per completed episode; `agent.end_episode()`
   (DQN checkpointing).
7. `finally`: `env.close()`, `logger.finalize()` (writes `ended_at`),
   `monitor.close()`, then `aggregate(run_dir)`.

**Fail-safes:** Ctrl+C and the dashboard STOP both end the run gracefully and
finalize logs. A run that crashes hard leaves `run.json` with `started_at` but no
`ended_at` and an empty/short `episodes.jsonl` — a useful crash signature.

### 4.1 StepMonitor protocol (the UI seam)

The loop only knows the `StepMonitor` Protocol (duck-typed, `runtime_checkable`):
`attach(env, agent)`, `on_episode_start`, `pump(last_action, info)`,
`on_episode_end(metrics)`, `stop_requested` (property), `consume_restart_request()`,
`close()`. The `Dashboard` implements it; tests use stubs.

**Two OPTIONAL hooks** are probed with `getattr`, so any monitor lacking them
falls back to default behavior (keeps tests + headless runs unchanged):
- `select_action(obs, agent) -> int` — lets the dashboard override the action
  (manual takeover, or a live-switched strategy). If absent, the loop calls
  `agent.act(obs)`.
- (Audio/render happen inside the emulator frame hook, not the loop — see §10.)

Note: `agent.observe(...)` always runs on the **loop's** agent (the learner). If
the dashboard is acting with a different strategy, the learner still observes the
transitions — valid because Q-learning is off-policy.

---

## 5. Configuration (`config.py`)

Pydantic models; invalid configs fail at load. `Config.from_yaml(path)` parses a
YAML run config. Sections:

- **`emulator`** — `rom_path`, `init_state_path` (both must exist),
  `render` (open PyBoy's own SDL2 window), `sound` (PyBoy native-window audio),
  `emulation_speed` (0 = unlimited, 1 = real time, N = Nx).
- **`environment`** — `max_steps` (truncation), `frame_skip` (frames per action,
  24), `observation_mode` ∈ {`ram`, `ram+tiles`}.
- **`agent`** — `type` ∈ {`random`, `heuristic`, `dqn`}, `seed`.
- **`reward.weights`** — `badge`, `event`, `map`, `level`, `blackout`, plus HCQM
  intrinsics `curiosity`, `stuck_penalty`, `stuck_threshold`.
- **`logging`** — `run_id` (auto if null), `output_dir`, `episodes`.
- **`ui`** (UIConfig) — `enabled`, `scale` (game ×N), `start_paused`, and the
  streaming options: `sound` (dashboard in-window audio), `volume`,
  `view_mode` ∈ {`full`,`clean`,`game`}, `smooth_rendering`.
- **`training`** (TrainingConfig) — DQN hyperparameters (see §8.4).

The config is hashed (`utils/hashing.py`, SHA256 over JSON-normalized content) so
identical experiments share a `config_hash` regardless of YAML formatting.

---

## 6. Emulator layer

### 6.1 `emulator/pyboy_wrapper.py` — `EmulatorWrapper`

Thin wrapper over **PyBoy 2.7**. Key constructor args:
`render` (SDL2 window vs `window="null"`), `sound` (native audio device),
`emulation_speed`, `capture_screen` (render frames into the buffer even with the
window off — used by the dashboard), `emulate_sound` (run the APU so
`pyboy.sound.ndarray` fills even headless — used for dashboard audio).

Important methods:
- `press_button_held(button, frames)` — Gen 1 needs ~17 consecutive frames of
  input per tile, so this presses the button **every** frame (not once).
- `tick(frames)` / `_tick_frames(frames)` — advance the emulator.
- `set_frame_hook(fn)` — register a callback fired **after every emulated frame**
  (the dashboard uses it for smooth rendering + audio capture; `None` on the
  headless path so ticking uses PyBoy's fast batched call).
- `screen_rgb()` → (144,160,3) uint8; `game_area()` / `game_area_collision()` →
  18×20 tile/walkability grids (from PyBoy's Gen-1 game wrapper);
  `visible_sprites()`.
- `audio_samples()` → (N,2) int8 stereo for the most-recent frame;
  `sound_sample_rate` → 48000.
- `read_byte` / `read_range` → RAM access.

### 6.2 `emulator/state_reader.py` — RAM → typed state

Reads verified Pokémon Red RAM addresses and parses them. Three dataclasses:

- **`GameState`** (the canonical 12-field snapshot): `party_count`,
  `party_total_{hp,max_hp,level}`, `money` (BCD-decoded), `current_map`,
  `y_pos`, `x_pos`, `badge_count` (popcount of the badge byte),
  `event_flags_set` (popcount across 176 event bytes), `battle_type`
  (`wIsInBattle` @ `0xD057`: 0 none / 1 wild / 2 trainer), `menu_cursor`.
  Property `all_party_fainted`.
- **`BattleState`** — in-battle flag + own (party lead at the active slot) and
  enemy (`wEnemyMon`) HP-fraction/level/types/status. Enemy fields zeroed when
  not in battle.
- **`PartyMon`** — full per-slot detail (species, level, HP, types, moves, PP,
  stats, and the Gen-1 hidden **DVs** "genome"). Used by the HUD.

Each party slot is 44 bytes; offsets and addresses are constants at the top of
the file. Battle addresses were chosen by live verification (the commonly-cited
`0xCFC4` was unreliable).

---

## 7. Environment & actions

### 7.1 `env/action_controller.py`

`Action` IntEnum, **7 discrete actions**: `NOOP, A, B, UP, DOWN, LEFT, RIGHT`
(`ACTION_SPACE_SIZE = 7`). START/SELECT are intentionally excluded (Phase 1
decision; expanding the space would change the DQN's output dim and invalidate
checkpoints). `ActionController.apply(action)` holds the mapped button for
`frame_skip` frames.

### 7.2 `env/pokemon_red_env.py` — `PokemonRedEnv` (Gymnasium)

- **`reset()`** loads the init save-state, reseeds the reward engine, returns
  `(obs, info)`.
- **`step(action)`** applies the action, reads state, computes reward, checks
  termination (8 badges or blackout) / truncation (`max_steps`), returns the
  Gym 5-tuple.
- **Observation assembly (`_build_obs`)** — order is fixed and treated as opaque
  by agents:
  - `ram` mode: 12 RAM scalars + 14 battle-perception features = **26 dims**.
  - `ram+tiles` mode: 12 + 360 (18×20 walkability grid) + 5 novelty features
    (current tile + 4 neighbors) + 14 battle = **391 dims** (HCQM "Gv" spatial
    vision). The walkability grid and novelty are zeroed in battle/menus.
- `obs_dim_for(mode)` is the single source of truth shared by the env and the
  agent factory so they can never disagree.
- `info` carries step/reward/badge/event/map counts plus the HCQM capability
  counters from the reward engine.

### 7.3 `env/reward_engine.py` — `RewardEngine`

Stateful across an episode; diffs the current `GameState` against the previous.
`compute(state, action)` returns a `RewardBreakdown` whose components are:

- **Extrinsic:** `badge` (×weight per new badge), `event` (per new event flag),
  `map` (per newly-seen map), `level` (per total-level increase), `blackout`
  (one-shot negative when all party faints).
- **HCQM intrinsic** (off by default; enabled in `train_dqn.yaml`):
  - `curiosity` (5.1): `weight × novelty(pos)` where
    `novelty = 1/sqrt(1+visit_count)` — pushes toward unseen tiles. Visit counts
    persist **across episodes within a run**.
  - `stuck` (5.2): negative penalty when the same action repeats with no
    position change past `stuck_threshold` (anti-perseveration).

It also accumulates episode counters read back for the **capability metrics**
(`unique_tiles_visited`, `repeat_action_rate`, `total_steps_stuck`,
`curiosity_reward_total`, `recovered_from_low_hp` — a 5.3 adversity proxy).

### 7.4 `knowledge/visit_memory.py` — `VisitMemory`

Counts visits to `(map, x, y)` positions, per-episode and per-run. Provides
`novelty()` (curiosity shape), `visit_count`, `top_visited` (loop hotspots),
`maps_seen_run/episode`. Reused by both the reward engine (curiosity) and the
dashboard MEMORY panel. Run-scoped counts persist; episode-scoped reset each
episode.

### 7.5 `knowledge/game_data.py`

Static lookup tables: `species_name` (Gen-1 internal indices, not Pokédex #),
`type_name`, `status_text`, `map_name`. Unknown IDs fall back to hex. Map IDs
here are the source of truth for the goal tracker (§10.6).

---

## 8. Agents (`agents/`)

All implement `Agent` (`base.py`): `act(obs) -> int`, optional `reset()`,
`observe(obs, action, reward, next_obs, terminated)`, `end_episode(ep, run_dir)`.
Each sets `self.thought` (human-readable rationale shown in the dashboard).
`build_agent(config)` (`agents/__init__.py`) is the factory; **torch is imported
lazily**, only when a DQN is actually built.

- **`RandomAgent`** — uniform random over the 7 actions.
- **`HeuristicAgent`** — scripted: mash **A** in battle; otherwise an UP-biased
  random walk over the 4 directions (no NOOP/A/B). A pipeline-validation harness,
  not a real player.
- **`DQNAgent`** (`dqn_agent.py`) — from-scratch PyTorch DQN (chosen over
  stable-baselines3 for full control of the HCQM modules):
  - MLP Q-network (`obs_dim → hidden → hidden → 7`), **Welford running
    normalizer** on observations, **circular numpy replay buffer**.
  - **Double-DQN** target (online net selects a*, target net evaluates it) to
    curb the overestimation bias that caused early Q-value collapse.
  - **Boltzmann exploitation** over **z-scored** Q-values: a temperature-scaled
    softmax that caps the top action's probability even if Q-values diverge — a
    structural "entropy floor" (HCQM §5.3 no-collapse rule). `temperature=0`
    falls back to greedy argmax.
  - Epsilon-greedy floor (`epsilon` property = linear decay), periodic target
    sync, periodic checkpointing (`ep{N}.pt` + `latest.pt`). Fresh start by
    default; `resume_from` loads a checkpoint (dims must match the obs mode).
  - Warms up CUDA kernels in `__init__` so the first inference doesn't stall the
    UI.

> **Note (current roster):** the DQN/PPO learners were retired. The live agent
> roster is `random`, `heuristic`, `strategist`, and the **GameSense brains**
> `planner` / `tactician` / `learner` / `catcher` (see §8.1). `base.Agent` now
> also has an optional **`full_reset()`** hook, called by the loop alongside
> `env.full_reset()` (periodic wipe / title-screen restart), so an agent can keep
> run-scoped memory across episodes but forget it on a genuine fresh start.

### 8.1 GameSense brains, anti-loop navigation & catching

The `planner`/`tactician`/`learner`/`catcher` agents (`agents/brain_agents.py`)
share a body (`BrainAgent`) built on `agents/brain/`:

- **`world_model.py` (`WorldModel`)** — a remembered per-map grid of cells
  (FLOOR/WALL/GRASS/NPC/WARP), learned from vision + movement feedback, with BFS
  path queries (`path_to`, `path_to_frontier`, `path_to_adjacent_npc`).
- **`gamesense.py` (`GameSense`)** — the policy over the map. `explore_action`
  priority: grow the frontier → route to a frontier → warp toward somewhere
  worth exploring → **go talk to an un-met NPC** → warp toward someone new →
  idle. `battle_brain.py` (`BattleBrain`) drives fights (type-aware move scoring,
  flee, and now catching).

**Anti-loop design (why it no longer paces in/out of buildings):**

1. A **warp tile is not a frontier** (`is_frontier` only matches FLOOR/GRASS) —
   a door's unknown neighbours are on *another* map, so the explorer stops
   treating doors as unexplored ground to walk into.
2. **Warp-pair cooldown** (`WARP_COOLDOWN_STEPS`): after crossing maps A↔B, the
   reverse crossing is refused for a while. Directly kills in/out oscillation.
3. **Exhausted-destination skip**: `_best_warp` never routes to a warp whose
   destination map has no frontier and nobody left to talk to.
4. **Event-seeking**: once walking is exhausted, the agent routes to the nearest
   un-talked-to NPC and presses A (`BrainAgent` queues face+A; handled tiles are
   recorded in `GameSense._interacted`, the single source of truth shared with
   routing). Talking is what fires the events (Pokédex, parcel, gym doors) that
   reopen the world. A rise in `event_flags_set` clears `_interacted` + cooldowns
   so people/doors are reconsidered after real progress.
5. **Cross-episode memory**: `GameSense.reset()` (per episode) keeps the world
   map and who's been met; only `full_reset()` wipes it. So the agent doesn't
   re-explore a house it already knows.
6. **Calm terminal state**: when everything reachable is explored and everyone's
   been spoken to, it idles (wanders open ground without stepping on a door, or
   NOOP) instead of thrashing — progress there needs an in-game event.

**Catching** (`catcher` agent + shared `BattleBrain` skill): the bag is read from
RAM (`state_reader.read_bag` / `best_ball`, `BALL_PREFERENCE` spends cheap balls
first). When the driving agent sets `brain.want_catch`, `BattleBrain._drive_catch`
runs a phase machine in a **wild** battle: open the **ITEM** menu (left column,
bottom row) → walk the bag cursor onto the chosen ball (self-verified via
`list_selection_index = wListScrollOffset + wCurrentMenuItem`) → select to throw →
advance the throw text. Bounded by `MAX_CATCH_ATTEMPTS` and the existing menu
wedge-detection, so a mis-read can only fall back to fighting, never softlock.
The `CatcherAgent` hunts grass for new species, **weakens** a target with
type-smart moves until it's below `CATCH_HP_FRAC` (or statused), then catches it,
tracking caught species so it doesn't re-catch.

The catch policy + caught-species tracking live on **`BrainAgent`** (shared), so
**any** brain catches when its `auto_catch` flag is set. The dashboard exposes
this as an **Auto-catch** toggle (Options ▸ Auto-catch; `ui.auto_catch`, default
on) and pushes it onto whatever strategy is acting each step — so on stream the
agent catches new Pokémon by itself in battle without switching to the Catcher.
The Catcher sets `_always_catch` so it catches regardless of the toggle.

### 8.2 The Adventurer — roots-driven Needs/Goal arbiter

The `adventurer` agent adds a **decision layer** above GameSense/BattleBrain so it
plays with intent (heal / progress / prepare / grow / explore) instead of only
mapping. It's the first consumer of the human **roots**:

- **`docs/AGENT_ROOTS.md`** — human-authored priors: drives (+ thresholds),
  story gates (blocker → what unlocks it), town services (Center/Mart), item
  effects, and an offensive gym curve. Markdown with fenced ```yaml blocks.
- **`knowledge/roots.py`** — parses those blocks into typed `Roots`
  (drives/gates/towns/items/gyms) with lookups (`next_gym`, `item_effect`,
  `center_town_names`…). Missing file ⇒ empty roots, agent still runs.
- **`agents/brain/needs.py` (`NeedsArbiter`)** — each step scores the drives
  (highest `priority` first) against a live context dict, returns the winning
  `Decision(drive, goal, rationale, critical)`. Triggers are short boolean
  expressions in the roots, evaluated with a restricted `eval` (no builtins) over
  the context — the roots file is trusted/local, so this keeps triggers
  expressive without hard-coding each.
- **`GameSense.route_toward_map(cur, x, y, target)`** — inter-map BFS over the
  warps the agent has learned (`_warp_dest`), returning the first step toward a
  distant map. This is how "go heal at the Viridian Center" actually walks there.
- **`AdventurerAgent`** — runs the arbiter every step, puts the rationale on the
  dashboard **GOAL** line (so you watch it reason: *"Party down to 18% HP — head
  to a Pokémon Center to heal"*), and dispatches the overworld goal to an
  executor. Centers/Marts are identified by `map_name` ("…Pokecenter"/"…Mart").

**Executor status (built in increments):** `explore` (GameSense) and
`train_or_catch` (grass-hunt + `auto_catch`) work; `heal` retreats to the nearest
known Center and talks to the nurse (free full heal); `shop` and `unblock_gate`
currently surface the right *intent* + best-effort navigation but don't yet drive
the purchase menu or run the multi-map errand (that's the next increment, and
needs live menu/NPC verification). The §6a move-scorer upgrades (accuracy, status,
crits, freeze) and the §6c glitch options are **not** wired (glitches default to
document-only).

### 8.3 LLM advisor (consulted when stuck)

`knowledge/llm_advisor.py` (`LLMAdvisor`) is an optional "strategist" the
Adventurer consults **only when it stalls at a gate**. A reasoning LLM can't run
every step at real time, so it sits above the symbolic agent: the agent sends a
short situation summary + the places it could go, the model replies with a
sub-goal (`{"goal":"go_to","target":"Viridian Mart","reason":…}`), and the agent
routes there (`route_toward_map`).

- **Off unless `HF_TOKEN` is set** in the environment (never stored in the repo).
  No token ⇒ disabled, agent uses its own judgement.
- Runs on a **background thread** so the game keeps rendering; the agent stands
  still (NOOP) while it waits and the dashboard draws a **thinking animation**
  (`Dashboard._draw_thinking`) with a spinner, the **estimated** time (rolling
  average of past call durations, `DEFAULT_ESTIMATE_S` until measured) and
  elapsed/progress bar. Overruns past `REQUEST_TIMEOUT_S` are abandoned.
- Model via `HF_MODEL` env (default a large instruct model on the HF router,
  OpenAI-compatible chat). HTTP is isolated in `_http_call` (injectable), so the
  threading/timing/prompt/parse logic is unit-tested with a fake call. Reasoning
  `<think>…</think>` scratchpads are stripped before JSON parsing.

> ⚠ **Live-verification TODO:** the LLM `_http_call` (HF router request/response
> shape) is **untested against the live API** — written but never run with a real
> token. Verify once a fresh `HF_TOKEN` is set. Also the in-battle **bag menu**
> addresses
> (`ADDR_LIST_SCROLL_OFFSET = 0xCC36`, and that selecting a ball in the bag
> throws it directly) are from the pokered map but were **not** verified live in
> this environment like the FIGHT/RUN menu signatures were. Confirm with
> `scripts/probe_battle_ram.py` against the real ROM; if catch nav misses, that
> address is the first suspect.

---

## 9. Evaluation & logging (`evaluation/`)

- **`metrics.py`** — `RunMetrics` dataclass (one per episode) + `TerminationReason`
  enum (`MAX_STEPS`, `BLACKOUT`, `ALL_BADGES`, `MANUAL`). Includes HCQM capability
  fields and DQN internals (`agent_epsilon`, `agent_loss`).
- **`logger.py`** — `RunLogger` writes `episodes.jsonl` (append, one JSON/line)
  and `run.json` (metadata; `finalize()` adds `ended_at`/`duration_seconds`).
- **`aggregate.py`** — `aggregate(run_dir)` reads `episodes.jsonl` and writes:
  - `eval_report.json` — mean/median/max/min/std per numeric metric, termination
    reason counts, blackout rate, "left starting map" count.
  - `capability_profile.json` — HCQM §7: per-capacity per-episode series + a
    collapse-aware **verdict** (`developing`/`stable`/`regressing`/`collapsed`/
    `not_developing`). Capabilities map metrics → desired direction (e.g. 5.1
    curiosity = `unique_tiles_visited` ↑; 5.2 = `repeat_action_rate` ↓; 5.3 =
    `blackout` rate ↓; 6.1 = reward ↑; 8.x = badges ↑).

`python -m pokeai report --run-dir runs/<id>` re-runs the aggregation.

---

## 10. The dashboard (`ui/`) — the largest subsystem

A pygame window implementing `StepMonitor`. It is BOTH a diagnostic tool and a
streaming/manual-play front-end. Default window at `scale=3`: game 480×432, full
window 1160×560 (game + two 340px side columns; 128px bottom bar). Imports pygame
lazily so headless installs never need a display.

### 10.1 Rendering architecture (READ THIS before touching draw code)

The single most important perf fact: a **full** window repaint (game + all
panels) costs ~5–20ms, which is more than the 16.6ms/frame budget at 60fps.
Repainting everything every frame drops the emulator below 1x (it was measured at
**0.53x**), which makes audio stutter and gameplay sluggish. So rendering is
**split**:

- **`_render_game_region()`** — per-frame, lightweight (~2.4ms): repaints ONLY
  the game view + HUD + overlays, then `pygame.display.update(self._game_rect)`
  (partial present). This is what makes motion smooth.
- **`_draw()`** — full window repaint (game + panels + bottom bar + options),
  ends with `display.flip()`. Called **once per env step** from `pump()`, and on
  any interaction. Clears the `_dirty` flag.
- A **`_dirty`** flag (set by any key/click in `_handle_events`) forces the next
  frame to do a full `_draw()` so menus/view changes appear immediately;
  otherwise the per-frame path uses `_render_game_region()`.

`_compute_layout()` sets `_game_rect` and `_bottom_h` from `view_mode`. Per-step
work runs at the step cadence (≈2.5 Hz at 1x), which is plenty for the diagnostic
panels.

### 10.2 The frame hook (`_frame_tick`) — smoothness + audio

Registered on the emulator via `set_frame_hook` (gated by
`_apply_frame_hook()`: active when `smooth_rendering`, `sound_on`@1x, or manual).
It fires after **every** emulated frame during a step and:
1. If `sound_on` and `current_speed == 1`: `audio.feed(emulator.audio_samples())`
   then `audio.pump()` (every frame, so no audio gaps).
2. Throttled to `RENDER_FPS` (60): `_handle_events()` then either `_draw()`
   (if `_dirty`/options open) or `_render_game_region()`.

At higher speeds audio is muted (it only makes sense at real time); the throttle
caps redraws so MAX-speed fast-forward stays fast.

### 10.3 Run control (`run_control.py`) — `RunControl`

Pure state machine shared between loop and UI: `RUNNING / PAUSED / STOPPED`, plus
one-shot `step` and `restart` requests. The loop's `pump()` **blocks** in a
30fps redraw loop while `PAUSED`. STOP is terminal (finalizes logs).

### 10.4 Manual takeover

`M` (or Options ▸ Manual) sets `manual_mode`. Then `select_action` returns a
**manual** action from `_read_manual_action()` (polls `pygame.key.get_pressed()`:
**X**=A, **Z**=B, **arrows**=D-pad; A/B prioritized over movement; else NOOP).
Entering manual: resumes running, drops to 1x if at MAX, and **reduces the
controller `frame_skip` to `MANUAL_FRAME_SKIP=8`** for responsiveness (restored
on exit). START/SELECT are not available (not in the action space).

### 10.5 Live strategy switching

`active_strategy` selects which agent acts. `_agent_for(name)` returns the loop's
learner if names match, else lazily `build_agent`s and **caches** an agent of
that type (from a deep-copied config). Failures (e.g. torch unavailable for DQN)
are caught: it shows a toast and falls back to the learner. Switching is
verified to change behavior (heuristic → pure directional; random → includes
A/B/NOOP). The learner keeps `observe`-ing regardless (off-policy-safe).
Strategy can also be set **before launch** via the config `agent.type` or the CLI
`--agent {random,heuristic,dqn}` flag.

Friendly names (`STRATEGY_NAMES`): random→"Random Walk", heuristic→"Heuristic",
dqn→"Deep Q-Net". The bottom bar shows `AI Strategy: <name>` (not the old
`agent: random`).

### 10.6 Panels, views, indicators

- **View modes** (`Tab` cycles, `VIEW_MODES`): `full` (game + AI VISION minimap +
  DIAGNOSTICS + THOUGHTS + MEMORY + CAPABILITIES), `clean` (enlarged game + a
  sidebar with mode/strategy, GOALS checklist, SESSION stats — for streaming),
  `game` (game only + minimal mode/goal overlay). Clean/game use the thin
  (72px) bottom bar; full uses the 128px bar.
- **Mode/strategy indicators:** `● AI` (green) / `● MANUAL` (purple) in the
  bottom bar, the clean sidebar, and an on-game chip.
- **HUD** (`_draw_hud`) — semi-transparent strips over the game: location/badges/
  money on top; lead Pokémon (species/level/types/status/DVs/HP bar) on the
  bottom; battle indicator.
- **AI VISION minimap** (`_draw_minimap`) — 18×20 walkability grid + sprites +
  player; a battle variant shades the battle tile grid and shows enemy stats.
- **THOUGHTS** (`thoughts.py`, `ThoughtTracker`) — the active agent's live
  rationale bubble + an event log generated by diffing `GameState`s (new maps,
  stuck, battles, damage, catches, badges, blackout).
- **MEMORY** — `VisitMemory` readout (positions known, maps known, novelty,
  hotspots, last-episode result).
- **CAPABILITIES (HCQM)** — per-episode acquisition sparklines + the DQN
  learner's internals (ε, loss, steps, buffer).
- **GOALS** (`goals.py`, `GoalTracker`) — a sticky milestone checklist (get
  starter, reach each city, earn each badge, train to Lv10) keyed off
  `GameState`/map IDs; surfaces a celebratory banner on unlock and the current
  objective. Shown in clean/game views.
- **Options modal** (`O`) — control mode, AI strategy, sound on/off, volume,
  view, smooth video, speed. Click or key-driven; Esc closes the menu first
  (then STOP).
- **Toasts** (`_set_toast`) — transient on-game notifications confirming setting
  changes ("AI Strategy → Heuristic", "Sound ON", "View: clean").
- **Controller** glyph + **speed** buttons (1x/2x/4x/MAX) live in the bottom bar.

### 10.7 In-window sound (`audio.py`, `AudioPlayer`) — and the state gotcha

The dashboard plays real game audio through **its own** window (no second PyBoy
window) via `pygame.mixer`. The emulator runs the APU headless
(`emulate_sound=True` when `ui.enabled`), the frame hook pulls
`pyboy.sound.ndarray` (48kHz stereo int8) every frame, `AudioPlayer` removes DC
(slow EMA), scales to int16, and streams ~33ms chunks through a reserved mixer
channel (play/queue). Audio plays **only at 1x** (real time); other speeds mute.
It degrades to a silent no-op if no audio device exists.

> **CRITICAL GOTCHA:** PyBoy fills the audio buffer headlessly only if sound is
> emulated AND the loaded **save state** was created with sound on. A state saved
> with `sound_emulated=False` restores a **disabled APU sampler**
> (`cycles_target=MAX`), so loading it yields silence (buffer head stuck at 0).
> The dashboard therefore uses **`states/init_state_starter_sound.gb_state`**,
> regenerated with the `--sound` pipeline (see §12). Any new dashboard init state
> needs that pipeline. The plain `init_state_starter.gb_state` (sound off) is kept
> for training/eval.

---

## 11. CLI & configs

```
python -m pokeai run --config configs/<name>.yaml [--episodes N] [--ui] [--agent X]
python -m pokeai report --run-dir runs/<run_id>
```
`--ui` forces the dashboard on; `--agent {random,heuristic,dqn}` overrides
`agent.type`. `cli.py` also forces UTF-8 stdout so the DQN's `ε` thought text
doesn't crash under Windows cp1252 when output is redirected.

Configs (what each is for):
- `random.yaml` / `heuristic.yaml` — headless baselines.
- `dashboard.yaml` — the streaming/diagnostic dashboard (1x, sound on, sound
  state, `random` agent by default).
- `train_dqn.yaml` — headless DQN training, `ram+tiles` obs, curiosity +
  anti-loop rewards, 100 episodes, fresh start, MAX speed.
- `watch_dqn.yaml` — load a checkpoint (`training.resume_from`) and watch it in
  the dashboard (pure inference: `learn_start` huge, small buffer).
- `watch.yaml` — watch a scripted agent.

---

## 12. State generation (`scripts/`)

Episodes always start from a save-state (a specific in-game moment). Generators:
- **`auto_init_state.py`** — boots the ROM fresh and navigates intro → bedroom →
  Pallet Town → Oak's lab → pick starter (best-effort; navigation is timing-
  sensitive and can land pre-starter). `--sound` keeps the APU sampler valid.
- **`make_starter_state.py`** — the **reliable** way to a "starter in Pallet
  Town, rival beaten" state: it **loads** a pre-starter base and completes the
  Oak sequence. `--sound`/`--base`/`--out` are parameterized.

**Sound-enabled state pipeline** (the only way to get dashboard audio):
```
python scripts/auto_init_state.py  --rom roms/Pokemon_Red.gb \
    --out states/init_state_sound.gb_state --sound          # sound-valid base
python scripts/make_starter_state.py --sound \
    --base states/init_state_sound.gb_state \
    --out states/init_state_starter_sound.gb_state          # sound-valid starter
```
A fresh sound-on boot keeps the sampler valid; loading that sound-on base
preserves it through `make_starter_state`. Verify the result has `party=1` AND a
non-zero audio buffer head before adopting it.

Other scripts: `smoke_dashboard.py` (renders the dashboard ~30 steps against the
real ROM, saves `states/dashboard_preview.png`), `check_acceptance.py`,
`debug_movement.py`, `generate_init_state.py`.

---

## 13. Testing

`pytest` (`tests/`). `mock_emulator.py` (`MockEmulator` + `encode_state`) replaces
PyBoy by serving scripted RAM snapshots through the **real** `StateReader`, so
parsing/logic is exercised without a ROM. Notable suites: `test_run_control.py`
(state machine + loop manual-stop/restart + the `select_action` override),
`test_goals.py`, `test_cognition.py`, `test_battle_vision.py`, `test_hcqm_2a.py`,
`test_phase1_*`, `test_cli.py`, `test_dqn_agent.py`.

> On this machine, run with `--ignore=tests/test_dqn_agent.py` to avoid a torch
> import hang (a known WMI/winmgmt issue, see §14). All non-torch tests (~81)
> should pass. Lint with `ruff check` (line-length 100, py310).

---

## 14. Machine-specific gotchas (this dev environment)

These are environmental, not code bugs (also captured in the assistant memory):
- **venv must live OUTSIDE OneDrive.** The project is under OneDrive; the venv is
  at `C:\pokeai-venv`, junctioned in as `.venv`. venvs inside OneDrive hang.
- **torch import can hang** because Windows WMI (`winmgmt`) is stalled (Py3.12
  platform calls block). Affects DQN configs and `test_dqn_agent.py`.
- **2nd concurrent torch+CUDA load** can fail `WinError 1455` (cufft) when the
  Windows page file is too small.
- Always run Python via `C:\pokeai-venv\Scripts\python.exe` (Bash) or `.venv`.
  The Bash tool's CWD resets to `C:\Program Files\Git` each call — use absolute
  paths.

---

## 15. Glossary (HCQM terms seen in code)

- **HCQM** — the cognitive-capability research model this framework evaluates.
  Capability IDs appear throughout: **5.1 Curiosity** (exploration/novelty),
  **5.2 Adaptability** (anti-perseveration), **5.3 Adversity** (recover from
  failure / no-collapse), **6.1 Learning agility**, **1.4 Gv** (spatial/visual
  perception = the tile grid), **§7** (developmental capability profiling),
  **§3.2** (the failure "death-spiral"/collapse the design guards against).
- **Capability profile / acquisition curve** — per-episode metric series + a
  verdict on whether a capability is developing or collapsing.
- **DV ("genome")** — Gen-1 hidden per-stat genetic values (0–15), shown in HUD.

---

## 16. How to extend (quick recipes)

- **Add an agent:** subclass `Agent`, set `name`/`thought`, implement `act`
  (+ optional `observe`/`end_episode`); register it in `build_agent`
  (`agents/__init__.py`) and in `STRATEGY_NAMES`/`STRATEGY_ORDER`
  (`ui/dashboard.py`) + the CLI `--agent` choices.
- **Add a reward term:** add a weight to `RewardWeights` (`config.py`), a field to
  `RewardBreakdown`, and the computation in `RewardEngine.compute`.
- **Add a goal:** append a `_GoalDef` (key, label, predicate over the small
  `_Ctx`) in `ui/goals.py`. Predicates see badge_count/party_count/level/maps_seen.
- **Add an observation feature:** extend `_build_obs` in `pokemon_red_env.py` and
  update `obs_dim_for` so the agent factory stays in sync (DQN checkpoints are
  obs-dim-specific — bump or retrain).
- **Add a dashboard panel:** draw it from `_draw()` (full repaint) — NOT from the
  per-frame `_render_game_region()` unless it must update at 60fps; keep per-frame
  work cheap or you'll drop below 1x (§10.1).
- **Change emulator behavior:** edit only `emulator/pyboy_wrapper.py`.

---

_See also: `README.md` (quickstart), `PHASE1_PLAN.md` (original plan),
`docs/ROADMAP.md` (current goal ladder + loop runbook),
`docs/Native-Stream-Operator.md` (Twitch bot spec and plan), and the assistant
memory note `pokeai_dashboard_streaming` for the streaming/sound work._
