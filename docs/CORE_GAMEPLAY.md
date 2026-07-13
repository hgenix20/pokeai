# Core Gameplay Module — the Field Brain

> **Status:** design, 2026-07-03. The single most important module: the AI that
> *plays like a person who read the manual*. Written after the catcher work
> exposed that catching is not a script but one behavior of a whole field-
> intelligence loop (Kameron's direction).
>
> **Realizes, doesn't replace:** `docs/AGENT_ROOTS.md` (the human priors —
> drives, thresholds, services, items, gyms) + `docs/FIRERED_REDESIGN.md` §6-9
> (task queue, resumable skills, needs arbiter, meta-RL). This doc is the
> concrete plan for wiring those into one gameplay brain and the build order,
> with the CATCHER as the first vertical slice.

---

## 0. The one principle

**The agent is BORN knowing the rules; RL learns the CONTENT.**

A human starting Pokémon already knows: HP=0 faints, type advantage exists,
Poké Balls catch weakened wild mons, Potions heal, Centers heal free, Marts sell
for money, trainers give money and wild mons don't, you can't grind forever with
no PP. They do NOT know: which Pokémon live in *this* grass, what *this* item
does until they try it, which of their mons beats the gym. They learn *that* by
playing.

So we split knowledge two ways and RL only touches the second:

- **A-priori (hand-authored, in `knowledge/roots.py` from `AGENT_ROOTS.md`):**
  game mechanics + a small seed of Kanto specifics (services, gates, gym curve,
  item effect categories, catch/heal/economy rules). The agent never has to
  "discover" that a Potion heals or that Centers exist.
- **Learned (run memory + meta-RL):** encounter tables per area ("Route 1 has
  Pidgey/Rattata"), confirmed item effects, which of *my* mons wins which
  matchup, where grinding is profitable, how many balls a given catch takes.

**Anti-pattern we explicitly reject:** reward-shaping low-level behavior
("+1 for moving to a new tile", "+0.1 for pressing A"). That produces a twitching
mapper, not a player. RL operates at the *decision* level (which drive, which
target, which battle plan) over a reward that is *real progress* (badges, story
steps, catches of new species, efficiency), while deterministic **skills** that
already know the game do the button-pressing.

---

## 1. The loop (one field step)

```
perceive (RAM state: party HP/levels/species/moves/PP, money, bag by pocket,
          badges, position/map, in-battle?, encounter this tile)
   |
   v
LEARNED + PRIOR knowledge  ->  NEEDS ARBITER scores DRIVES (below)
   |                              (meta-RL nudges the weights + targets)
   v
active Drive + target (e.g. HEAL @ Viridian Center; CATCH Nidoran on Route 22)
   |
   v
SKILL for that drive (resumable state machine) -> ONE button this step
   |
   v
observe result; update learned knowledge; feed meta-RL a reward signal
```

The arbiter runs every step but a Skill holds its own progress, so a multi-step
errand ("buy 10 Poké Balls") stays the active drive across the walk to the Mart,
the menu, and the purchase. This is the FIRERED_REDESIGN task-queue/skills seam,
already partly built (`knowledge/roots.py`, `agents/brain/needs.py`).

---

## 2. Drives — the wants, in priority order (from AGENT_ROOTS §1, FRLG-tuned)

Each is `trigger` (when it fires) + `resolves_to` (the skill). Higher priority
wins ties. Meta-RL adjusts the thresholds/weights over time from experience.

| Drive | Fires when | Resolves to | Notes / the nuances Kameron called out |
|---|---|---|---|
| **survive / heal** | party is hurt enough | `heal` | NOT per-mon. Threshold is over the PARTY: heal when `party_hp_fraction < T` OR `fainted_count >= 1` OR (`hurt_count >= ceil(party_size/2)`). Don't trek to a Center for one lightly-scratched mon in a full party; do go if several are low or any fainted. `critical` (very low / multiple fainted) also flees battles. |
| **restock balls** | catching is a goal and `poke_balls < K` and a Mart is known | `buy_item(ball)` | "running out of Poké Balls → go to the Poké Mart." K scales with intent (hunting a species vs opportunistic). |
| **earn money** | need to buy but `money < cost` | `grind_trainers` | "low on money → go battle other trainers." TRAINERS give money (and are one-time); WILD mons give none. So the earn skill seeks unbeaten trainers / the Vs. Seeker, not grass. |
| **restock heals** | `money > buffer` and `healing_items < H` and Mart known | `buy_item(potion)` | stock potions/status cures before a dungeon or gym. |
| **prepare (gym)** | at a gym town, gym unbeaten, party < full HP/PP | `heal` | walk in fresh, not chipped. |
| **grow / train** | `party_top_level < next_gym_recommended_level` | `grind` / `train_or_catch` | level toward the gym floor while advancing, not camping one patch. |
| **catch / fill party** | roster below target (size or missing coverage) and a wanted species is here | `catch` | "fill up the party." Wants a target roster (types that cover the next gyms), not just 6 bodies. |
| **discover** | current area's encounter table unknown | `explore_grass` | "learn and discover what's there" — walk the grass, log the species/levels seen into the learned encounter table. |
| **progress / story** | nothing else pressing; a story gate is next | `advance_story` | the loop-killer: re-assert the walkthrough step so it never wanders forever. |
| **explore** | default | `explore` | map the area, meet NPCs. |

---

## 3. A-priori knowledge the agent ships with (the "manual")

Ported from `AGENT_ROOTS.md` (currently Gen-1 **Red**; needs a **FireRed/Gen-3**
pass — see §7). Lives in `knowledge/roots.py` + `knowledge/game_data.py` +
`knowledge/type_chart.py`:

- **Battle mechanics:** the type chart (Gen-3: adds Dark/Steel, the Special
  split, abilities/held items exist — a delta from Red), STAB, crit, status,
  the 6a battle quirks (freeze, high-crit, status-first) as a move-scoring layer
  above `battle_brain.score_moves`.
- **Catch mechanics:** wild-only; weaken/status the target first (lower HP +
  a status raises catch rate); ball preference (spend cheap balls first, save
  the Master Ball). The agent knows this before it ever throws one.
- **Item effects (categories):** heal_hp / heal_status / revive / capture /
  repel / escape / key / boost — so it never wastes a turn learning that a
  Potion heals. Exact per-item confirmation is learned.
- **Economy:** Centers heal free; Marts buy/sell; trainers pay, wild don't;
  Vs. Seeker re-battles for income (FRLG). Selling Nuggets = money.
- **Services + gates + gym curve:** which towns have a Center/Mart, the story
  gates (old man, Brock's guard, ...), the "don't walk in underleveled" targets.

---

## 4. Learned knowledge (run memory, persists across episodes)

A per-run store (extend `knowledge/visit_memory.py` / a new `field_memory.py`):

- **Encounter tables per area:** species + level ranges seen in each grass/cave
  map. Starts empty; the `discover` drive fills it. Answers "where do I catch X?"
- **Confirmed item effects:** used a Potion → HP rose → confirm `heal_hp` and its
  amount. Overwrites/greenlights the prior guess.
- **Matchup outcomes:** my Squirtle beat that Pidgey in 2 turns with Tackle →
  weight that plan up. Feeds move/lead selection.
- **Profitable spots:** which trainers/routes gave the most money/EXP per minute.
- **Caught-species set:** so `catch` doesn't re-catch what it has (unless told).
- **Service doors:** the exact Center/Mart door per town (the priors are coarse
  "this town has one"; the door is learned — like the Viridian landmarks we
  found live).

Blanks in the priors = "let it learn." The store is the difference between a bot
that re-derives the world every run and one that gets smarter.

---

## 5. Skills — the reusable, resumable, self-verifying hands (from REDESIGN §7)

Each Skill is a small state machine: `reset(task) / step(state) -> Action |
Needs(...) | Done | Failed`. They are the ONLY thing that presses buttons, they
are deterministic, and each verifies success via RAM (not narration). A skill
that needs something it lacks emits `Needs(...)`, which spawns a dependency drive
(catch needs a ball it doesn't have → `restock balls`).

Catalog (build order roughly this):
1. `navigate_to` — DONE (ledge-hop, waypoints, warps). Foundation.
2. `battle` — win a fight (A-mash today; needs move-scoring depth = REDESIGN §7).
3. **`catch`** — THE FIRST SLICE (see §6). Weaken → status(optional) → open BAG →
   pick best ball → throw → confirm via party/box count delta.
4. `heal` — Center nurse (proven in Part 2 approach) / use items in a pinch.
5. `buy_item` — Mart clerk → BUY menu → item → qty → confirm → verify bag delta.
6. `grind_trainers` — route to unbeaten trainers, win, collect money/EXP.
7. `defeat_trainer` / `advance_story` — story beats.

Menu-driving skills (catch/heal/buy) share the same hard part: **knowing which
menu state you're in from RAM**, not fixed-timing button mashes (see §6.1).

---

## 6. The catcher as the first vertical slice

The catcher is chosen first because a real catch forces the WHOLE economy loop:
catch → consumes a ball → low balls fires `restock` → needs money fires `earn` →
getting hit fires `heal`. Build the catcher and you've built the skeleton every
area reuses.

### 6.1 The immediate blocker — SOLVED (2026-07-03)

Reaching the in-battle **action menu** reliably. Intro is `"Wild X appeared!"`
(waits for A) → `"Go! CLAW!"` + a long, variable send-out animation → the
FIGHT/BAG/POKéMON/RUN menu appears on its own. Fixed sleeps never land on it;
`b.tick()` breaks input. **SOLVED via battle-state RAM, live-verified:**
- **Menu-up signal:** the action-selection cursor `0x02023FF8`
  (gActionSelectionCursor: 0=FIGHT 1=BAG 2=POKéMON 3=RUN). It is only live at the
  menu. Robust test = STABLE at rest ∧ CHANGES on a RIGHT tap ∧ RESTORES on LEFT;
  this rejects intro-animation/RNG noise (a naive before/after diff false-positives
  on drifting bytes like 0x02023BC8).
- **Advance the intro with B, not A:** B advances the text boxes but is a harmless
  no-op at the menu / backs out of a stray submenu, so the detection race can't
  strand us in FIGHT.
- **Real battle vs stale enemy:** `battle.active()` false-positives on a lingering
  gEnemyParty (slot 8 loads active); require active ∧ movement-locked.
- **Bag path:** ITEMS → KEY ITEMS → **POKé BALLS** (RIGHT ×2 from default) → A
  throws the top ball. Post-throw mash **B** (advances wobble/Gotcha text AND
  declines the "give a nickname?" YES/NO prompt = NO).
- **Confirm caught:** gPlayerPartyCount `0x02024029` +1.

Implemented in `src/pokeai/skills/catch.py` (retry until caught/out). Acceptance
test `scripts/catch_accept.py` PASSED live: party_count 1 → 2, wild Pidgey caught.

### 6.2 The catcher, once the menu is solved

`CatcherAgent` (a drive, not a mode): pick a target species (from the wanted
roster + this area's learned encounters), hunt grass until it appears, weaken it
with type-smart moves to below a catch-HP fraction (or land a status), throw the
best affordable ball, track it as caught. When `auto_catch` is on, ANY brain
catches a new species mid-fight. All of this already exists in spirit in the Red
build's `battle_brain` catch phase machine — it needs the Gen-3 bag addresses and
the RAM menu-state detection.

---

## 7. What has to happen (build order / next sessions)

1. **Catch menu-state RAM** — probe the Gen-3 battle struct for the action-menu
   signal (iterate from slot 8). Unblocks catch AND heal AND buy (same problem).
2. **`catch` skill** — throw + confirm; nature-from-PID for the Route 22 Mankey.
3. **FRLG roots pass** — port `AGENT_ROOTS.md` Red→FireRed (Gen-3 type chart,
   confirm FRLG gates/services; most Kanto carries over) into `knowledge/roots.py`.
4. **`buy_item` + `heal` skills** — reuse the menu-state work.
5. **Wire the NeedsArbiter** — score the §2 drives over the live state, dispatch
   to skills, show the winning drive + reason on the viewer board ("Party 22% →
   Viridian Center"). This is the "plays like a person" moment.
6. **`field_memory`** — the learned store (§4).
7. **Meta-RL** — a small contextual policy over drive weights + target selection
   (REDESIGN §9), reward = real progress. Only after the deterministic loop works.

Each is a phase; commit each; keep slots as checkpoints. The catcher (steps 1-2)
is the near-term goal and the proof that the architecture is right.

---

## 8. Strategy = a pluggable, viewer/operator-selectable policy (decided 2026-07-03)

The play POLICY is not hard-coded; it is a named **Strategy** the audience and
operator choose, and it reconfigures the Field Brain (drive weights, targets,
goal). Extends the `STRATEGIES` dict already in `scripts/stream.py`.

- A Strategy is a small config over the SAME brain: a goal + drive-weight/
  threshold overrides + a target-roster/catch policy + a board task tree. The
  arbiter, skills, and knowledge are shared; only weights/targets differ, so
  strategies are cheap to add and interchangeable.
- Selection surfaces:
  - Operator picks via the operator panel (already: `set_strategy`, locked once
    a run starts).
  - Viewers pick via the Twitch bot (command / poll / Channel Point) that posts
    a `set_strategy` or a vote to the stream.py control API (a B1/B2 bot feature
    on the `/api/directive` seam).
  - The viewer board shows the active strategy + goal (already rendered from
    `STRATEGIES[...]['name']/['goal']`); extend to a picker/vote display.
- Initial catalog (interchangeable from the start):
  - `storyline` (exists): progress/story-first. Goal: become Champion.
  - `catch_fill6`: the FIRST catch strategy, fill the party to 6 of anything
    (Kameron's start point). Catch drive high, no coverage planning.
  - later: `type_coverage`, `pokedex` (catch 'em all), `nuzlocke`, `shiny_hunter`.
  Each is a weights/target/goal preset over the drives in section 2.

## 9. Decisions locked (2026-07-03)

- Catch policy: start with FILL-TO-6-OF-ANYTHING, implemented as ONE
  interchangeable Strategy among many (section 8); viewers pick via the bot,
  operator via the panel, current strategy shown on the viewer board.
- Heal rule (section 2 survive): party_hp_fraction < 0.35 OR any fainted OR at
  least half the party low; critical (very low / multiple fainted) also flees.
- Roots: PORT AGENT_ROOTS.md Red -> FireRed NOW so the arbiter drives off real
  priors (Gen-3 type chart, confirm FRLG gates/services; most Kanto carries
  over) instead of hard-coded per-part scripts.
- Glitches (AGENT_ROOTS 6c): document-only default (unchanged).

## 10. Revised build order (with the decisions)

1. Catch menu-state RAM (unblocks catch/heal/buy) -> `catch` skill (throw +
   confirm). Proves the vertical slice.
2. FRLG roots port into knowledge/roots.py.
3. NeedsArbiter wired to the drives over live state; winning drive + reason on
   the viewer board.
4. Strategy layer (section 8): Strategy presets over drive weights/targets;
   `catch_fill6` + `storyline`; operator picker (exists) + expose set_strategy
   and a vote path for the bot; viewer board picker.
5. buy_item + heal + grind_trainers skills (reuse menu-state work).
6. field_memory (learned store) + meta-RL over strategy/drive weights.
