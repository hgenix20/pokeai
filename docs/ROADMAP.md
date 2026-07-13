# pokeai ROADMAP + Loop-Engineering Runbook

> The single working file for iteration. Created 2026-07-03. This file gets
> EDITED every iteration: goals move, tasks check off, outcomes get logged in
> §6. Read §1 before building anything.
>
> Companion docs: `ARCHITECTURE.md` §0 (current stack map),
> `docs/Native-Stream-Operator.md` (bot spec + phases B0-B5),
> `docs/Walkthrough-notes-to-fix.md` (story source; built through `[[STOP]]`),
> `docs/FIRERED_REDESIGN.md` (original target design + what changed),
> `docs/CORE_GAMEPLAY.md` (the Field Brain: drives/skills/learned-vs-prior/meta-RL; the catcher is its first slice).

---

## 1. The loop protocol

Every work session (human-driven or /loop-driven) runs this cycle:

1. **Check current goal**: the topmost unchecked goal in §2.
2. **Check its tasks**: the goal's block in §3.
3. **Build** the smallest task that moves the goal.
4. **Validate through testing** (§4): run the task's stated check; run the
   goal's acceptance test whenever the goal might be complete.
5. **Update tasks**: check off what passed; add what was discovered.
6. **Update the goal** when all tasks are done AND the acceptance test passed
   on the real surface. Then repeat with the next goal.

Hard rules (paid for in past iterations):

- **Every goal has ONE real-surface acceptance test, stated up front.** Real
  surface = real game RAM through BizHawk, or real Twitch chat. If an
  iteration cannot self-verify on a real surface, do not loop on it; stop and
  surface the blocker.
- Mock/unit tests (T0) make failures cheap; they never mark anything done.
- A task blocked on a Kameron prerequisite (§5) is parked visibly here, never
  mocked into a fake "done".
- Log every iteration's outcome in §6, one line each, newest first.
- Model tiering for subagent work: Fable only for design/tricky debugging;
  Sonnet/Opus for well-scoped implementation; Haiku for sweeps, scans, and
  mechanical verification. Prefer scripts over hand-editing for mechanical
  changes.

---

## 2. Goal ladder

Ordered. Work the topmost unchecked goal; G1 may run in parallel with G2 since
they touch different surfaces. Bot phases (B0-B5) are specced in
`Native-Stream-Operator.md`.

- [x] **G0 · Foundations.** (DONE 2026-07-03) `git init` + first commit (audit `.gitignore`:
  roms and large states stay out, slots policy decided); read-only
  `GET /api/context` endpoint on stream.py.
  **Acceptance:** repo committed; `curl 127.0.0.1:8777/api/context` returns
  live party/map/money during a running Part 1 session.
- [x] **G1 · Bot B0, read-only companion. LIVE 2026-07-03.** OAuth, EventSub, greetings,
  moderation v1, commands incl. `!party !badges !route` from /api/context.
  **Acceptance:** B0 acceptance (operator doc): T1 watchdog script passes in
  offline 6genix chat; `!party` answers from live RAM in a T2 run.
- [x] **G2 · Storyline Part 2 (Oak's Parcel quest) DONE 2026-07-03.** Route 1 (XP grind skill + free
  Potion man), Viridian Center heal skill, Mart parcel pickup.
  **Acceptance:** scripted run from the Part-1-end slot reaches Viridian,
  heals (party HP full from RAM), holds Oak's Parcel (bag read).
- [x] **G3 · Storyline Part 2, second half — DONE 2026-07-05.** Parcel
  delivered (FLAG_SYS_POKEDEX_GET 0x829 SET, gated in-run), 5 balls in bag,
  Town Map from Daisy (key item 361, rival's house door (15,7) -> (4,2), Daisy
  (5,4)), Teachy TV from the old man (key item 366, north path (18,5)).
  Event-flag region live-verified by id (probe_event_flags: 0x829 flips
  exactly across the delivery, slot 2 vs 6 diff). Slots 5/6/7 regenerated;
  slot 6 = "Part 2 COMPLETE".
  **Acceptance:** `part2_full_test.py` end to end from slot — PASSED as a
  slot-chained pass per the checkpoint workflow: stages A-C from slot 4
  (saving slot 7), stages D-H resumed from that slot 7 (--from7) after a
  stage-D fix. The script runs unbroken end-to-end on demand.
- [~] **G4 · Bot B1, state-aware interaction.** BUILDABLE HALF DONE 2026-07-05:
  stream_state classifier v2 (pure fn, ui/stream_state.py, 11 tests; Center/
  Mart/LOW_HP states live; wild/trainer split unblocked by 0x02022B4C but not
  yet wired into stats_tick), gating engine from the State Rules matrix
  (bot/gating.py, 28 states). PARKED on K6 (affiliate): polls/predictions +
  the rival-named-by-poll clause. Still open: naming operator input, Q&A
  queue, clip marker (scope check), operator bot tab.
  **Acceptance:** B1 acceptance: states gate correctly in a Part 2 rehearsal;
  rival named by poll; a real clip created.
- [x] **G5 · Catching = FIRST SLICE of the CORE GAMEPLAY module — DONE 2026-07-05.**
  The FULL economy loop ran autonomously (scripts/field_run.py, PASS):
  survive->heal (Viridian Center) -> restock_balls->mart buy -> fill_party->
  weaken-first catch -> complete with a party of 6 at full HP, all stages
  RAM-verified. Weaken-first = ~1 ball/catch (v1 was ~7%/ball). NeedsArbiter
  drives over live RAM (agents/field_brain.py); drive+reason on the viewer
  board through stream.py (catch_fill6 dispatch wired + validated on-stream).
  nature-from-PID in the reader. slot 9 = full party of 6.
  **Acceptance:** catches a wild Pokémon on Route 1/22 in a real run;
  party/box delta confirms; species tracked. (Exceeded: 7+ catches across
  runs, species logged each time, economy loop closed.)
- [~] **G6 · Bot B2, game-effect queue (Low tier).** BUILDABLE HALF DONE +
  VALIDATED IN REAL CHAT 2026-07-05: effect catalog + queue with refund
  marks (bot/effects.py, SQLite-backed), POST /api/directive whitelist v1 +
  safe-point consumption in stream.py, DirectiveClient/EffectConsumer in the
  bot pump, !effects/!redeem/!questlist/!quest. LIVE T2 PROOF: !redeem
  show_party in #6genix -> queued -> executed at a safe point (status via
  GET /api/directives) while the Field Brain ran on stream. PARKED on K6:
  the Channel-Point redemption source (the acceptance's payment leg);
  catch_next_encounter arming exists, its in-battle execution clause rides
  the next wild-battle rehearsal.
  **Acceptance:** B2 acceptance: catch-next-encounter redemption executes in
  a live wild battle; blocked-state redemption refused + refund-marked.
- [x] **G7 · Viridian Forest + battle v2 — DONE 2026-07-05 (caveats below).**
  Battle v2 live-proven: type-scored moves (gen3_battle over live decode of
  BOTH parties), multi-mon trainer battles with send_next_mon after our
  faints, potion-by-bag-index path, gBattleTypeFlags 0x02022B4C wild/trainer
  split (VERIFIED), win = all enemy slots down + payout money delta. Journey
  PASSED (forest_run.py): Viridian -> Route 2 (3,20) -> gates (15,0)/(15,3)
  -> forest (1,0) -> Pewter (3,2); Bug Catcher Sammy's lv9 Weedle beaten
  across two of our faints; Pewter Center discovered (door (17,25) -> (6,5),
  nurse (7,2)) + heal RAM-verified; slot 3 = Pewter Center.
  **Acceptance caveats (folded into G8 prep):** Rick/Doug sight-lines were
  dodged by warp-directed pathing (only Sammy fought); no full blackout
  occurred (per-mon faint recovery exercised instead; blackout ride-out code
  exists unexercised). The G8 grind sweep clears the remaining trainers.
- [~] **G8 · Brock + Bot B3 (Interaction Request Engine).** GAME HALF DONE
  2026-07-05: **BOULDER BADGE EARNED** — FLAG_BADGE01 (0x820) SET + badges==1
  from RAM, Brock's Geodude lv12 + Onix lv14 swept by CLAW lv12's 4x Bubble
  (fight_smart type scoring), payout verified (money 1524 -> 3144). Prep:
  forest_grind.py leveled CLAW 7->10 (25+ wild wins, Pewter heal trips).
  slot 2 = Boulder Badge.
  **B3 ENGINE BUILT 2026-07-06** (bot/asks.py, 34 T0 tests, 220 bot total):
  opportunity detector (60s loop: trigger table + chat velocity + suppression
  states), seed builder (all doc fields, recent-5 history), HF generation (3
  candidates, K7 HF_TOKEN via bot/.env) with honest template fallback (rows
  record generator=hf|template), guardrail filter (blocked/guilt/lurker
  phrases, no-deception interaction-handle rule, length, shouting), scorer
  (context match/freshness/brevity/clarity), interaction_prompts +
  interaction_prompt_results tables with the 3-minute lift window, per-type
  cooldown budgets exactly as tabled (boss prep once per boss; ledger seeds
  from the store across restarts), wired into bot/live.py behind the kill
  switch. REMAINING: the stream-rehearsal clause (T2: 5+ asks, every ask
  matches live state at send time, transcript review clean).
  **Acceptance:** Boulder Badge earned (badge flag from RAM) in a stream
  rehearsal; B3 transcript review clean (every ask matches live state, zero
  guardrail violations).
- [ ] **G9 · Chaos era.** CrowdControl integration + game-side
  DisruptionMonitor + Bot B4 (chaos meter, Medium tier).
  **Acceptance:** a CC effect fires in ROUTE_TRAVEL, is detected and reacted
  to on the viewer board, and is blocked in GYM_BATTLE.
- [x] **G10 · StoryDriver / walkthrough parser — DONE 2026-07-05.**
  planner/story_parser.py (21 parts / 703 steps from the doc, battles/items/
  tags structured, 24 tests) + planner/story_driver.py (completes_when
  predicates over live facts: item-in-bag, map-id, badge/flag; ADVANCE_STORY
  to_task adapter; 22 tests).
  **Acceptance PASSED live** (scripts/story_replay.py): Parts 1-2 replayed
  against the recorded slots with facts read from RAM at each checkpoint -
  5 fact-mode steps completed from facts alone (Route 1 map, parcel 349,
  Town Map 361, Teachy TV 366), cursor at Part 3, no hand-coded steps
  (manual marks = the driver's designed runtime mechanism for non-fact
  steps; the final forest-entry map step marked because no recorded slot
  stands in the forest).

- [~] **G11 · Storyline Part 4 — JOURNEY DONE 2026-07-06 (caveats below).**
  PASS at 11:27: Cerulean reached (map (3,3) logged), Center discovered
  (interior (7,3), door (22,19), nurse (7,2)), healed 167/167 from RAM,
  slot 4 = "Cerulean Center (G11)". Route 3 gauntlet + Route 4 + all of
  Mt. Moon traversed (2 Rocket guards beaten by the bot; the east half +
  pickups finished by Kameron manually after the walker redesign landed).
  OPEN CLAUSES: fossil chosen by HAND (Dome - and the choice is a designed
  viewer-poll moment, see status note), and the catch_next redeem clause
  rides the same stream rehearsal as G8's. Original spec text follows.
  Storyline Part 4: Route 3 -> Mt. Moon -> Cerulean. Running
  Shoes from Oak's aide (Pewter east exit), Route 3 trainer gauntlet, Route 4
  Center landmark, Mt. Moon (ladders = warps, Rocket battles, fossil choice:
  HELIX/Omanyte locked in AGENT_ROOTS, item-ball pickup = NEW skill), Route 4
  east, Cerulean. The journey runs as the STORYLINE strategy under stream.py
  (Field-Brain-hosted) — this also satisfies G8's stream-rehearsal clause and
  consumes the catch_next directive at wild battles (B2 acceptance).
  **Acceptance:** from slot 2, one run reaches the Cerulean Center and heals
  (RAM), with a fossil in the bag and >= 3 trainer wins logged; a
  catch_next_encounter redeem from chat executes in a live wild battle
  en route (directive status EXECUTED + party delta).
  **2026-07-06 status:** Mt. Moon traversed (2 Rocket guards beaten by the
  bot; the east half + pickups finished by KAMERON manually after the walker
  redesign landed - TM46, TM09, Rare Candy, Star Piece, and the DOME fossil,
  overriding AGENT_ROOTS' Helix default). Kameron's call: the FOSSIL CHOICE
  is a designed viewer-poll moment (Lore Vote category, B1 poll machinery,
  free chat poll under the no-affiliate rule) - wire it when the storyline
  strategy replays Part 4 on stream. Player parked on Route 4 EAST; stage
  E/F (Cerulean + Center + slot 4) = the remaining acceptance walk.
  Acceptance caveats when it lands: fossil chosen by hand, not the agent;
  the catch_next redeem clause still rides a stream rehearsal.
- [ ] **G12 · Misty (Cascade Badge).** Bad matchup for a Water starter: needs
  the type-coverage catch first (Oddish/Bellsprout on Routes 24/25, or
  Pikachu in Viridian Forest) + levels (rival on Route 24 runs lv25).
  **Acceptance:** FLAG_BADGE02 (0x821) set from RAM in a stream rehearsal.

Parked (revisit after G8): `[[SAVE]]` checkpoint annotation + auto-slot
writes; Bot B5 analytics; legacy-doc `[[Verify]]` content checks; P3
productization; Red/PyBoy stack retirement decision.
Parked on K6 (2026-07-05: NO affiliate — channel has practically no viewers;
revisit only if affiliate happens): polls/predictions (G4 poll clause),
Channel-Point redemptions (G6 payment leg — the free !redeem path is the
operative mechanism). /mod SagaciousWizard: DONE 2026-07-05 (moderation T1
unblocked).

---

## 3. Task backlog by goal

Short stubs; the operator doc holds B-phase details. Check off as done, add
discoveries under the goal they belong to.

### G0
- [x] States/slots git policy: ALL of roms/ + states/ ignored (states is a
      junction to local disk; binaries never in git). Revisit only if Kameron
      wants slot JSONs versioned.
- [x] `git init --separate-git-dir C:\pokeai-git` (git dir OUT of OneDrive,
      same pattern as venv/states) + initial commit c8bfcc1 + tag
      `part1-complete`. 169 files, no binary leaks.
- [x] `GET /api/context` on stream.py: worker-owned snapshot (party w/ names,
      money, badges, map/pos, active/next task, goal, v1 stream_state,
      events). Acceptance script `scripts/check_api_context.py` PASSED live
      (CLAW lv6, $3080, PALLET_TOWN, from slot 2).
      Gotcha logged: bridge `read_range(start, END)` takes an end address,
      not a length.

### G1 (bot B0)
- [ ] Kameron prerequisites K1-K5 (see §5)  <- ONLY remaining G1 blocker
- [x] `bot/` package + SQLite store + `.env.example` + config (T0, 2026-07-03)
- [x] OAuth device flow + refresh (injectable http); sans-io EventSub handler
      + dedupe, fixtures in tests/bot/fixtures (T0)
- [x] Sender queue/cooldown (fake clock); viewer DB + greetings (first-time /
      returning / synthetic exclusion); command router incl. !party etc. from
      /api/context with offline fallback (T0)
- [x] Moderation ladder + kill switch; watchdog scenario runner (assertion
      logic tested; network parts raise NotImplementedError listing K1-K5)
- [x] 58 bot tests + full 305-test suite pass; ruff clean; websockets 16.0
      installed. Live paths (real WS/Helix/OAuth) deliberately raise until
      K1-K5 exist. Dry-run mode works today: `python -m bot.main --dry-run`
      (see bot/README.md)
- [ ] T1 acceptance in real 6genix chat (watchdog) - blocked on K1-K5

### G2
- [x] Route 1 REACHED from slot 2 (2026-07-03, `scripts/route1_probe.py`):
      lab exit via leave_building verified; Pallet north EDGE CONNECTION
      crossing verified (current_map updates on connections, not just warps);
      **Route 1 map id = (3,19)**; slot 3 saved = "Route 1 south edge".
- [x] First WILD battle WON on Route 1 (2026-07-03): lv3 foe, Battle.fight
      A-mash works unchanged on wilds; post-battle text rides out on A taps.
      LESSONS: encounters fire only on steps INSIDE tall grass (pace within a
      patch, hit after 10 steps); Route 1 has a one-way LEDGE across the path
      (~y=39) that blocks a naive north walk. Pattern encoded in
      `scripts/route1_wild_probe.py`.
- [ ] Wild-battle handling in `skills/battle.py` (flee option, XP/level
      tracking; wild-vs-trainer RAM flag for the state classifier)
- [ ] Grind skill (grass seek, fight, level target, retreat on low HP; CLAW
      was 12/22 after ONE fight, so retreat/heal logic matters immediately)
- [ ] `heal()` skill (Center nurse dialogue) for FireRed
- [ ] Route 1 traversal to Viridian (ledge-aware) + Potion man interact;
      Viridian Mart parcel scene

### G3
- [ ] Event-flag region live verification (probe vs known flags):
      `scripts/probe_event_flags.py` written (slot 2 vs slot 6 diff, expects
      dex flag 0x829 to flip), not yet run
- [x] Bag read (security-key XOR) live-verified 2026-07-05: pockets formalized
      in FireRedStateReader (items 0x310/42, key_items 0x3B8/30, balls
      0x430/13); `scripts/probe_bag_pockets.py` PASSED on slot 8 (balls
      [(4,5)], CLAW's moves Tackle/Tail Whip w/ correct base PP = first live
      proof of the Attacks-substruct decode)
- [ ] Parcel delivery run + Pokédex/balls confirmation; Daisy Town Map;
      Teachy TV
- [ ] `part2_full_test.py` acceptance script + slot regeneration (script
      WRITTEN 2026-07-05, stages A-H incl. dex-flag gate, unrun)

### G4 (bot B1)
- [ ] stream_state classifier v1 (detectable subset + safer-ancestor rule)
- [ ] Gating engine from the State Rules matrix; polls/predictions (K6)
- [ ] Naming flow (operator input + viewer poll -> intro runner)
- [ ] Bot tab on operator board

### G5
- [x] Probe FireRed battle-bag menu RAM (old Red 0xCC36 obsolete). LIVE-VERIFIED
      7/3: action-menu cursor 0x02023FF8 (stable-at-rest + moves-on-RIGHT test =
      robust "menu up" signal, rejects intro-animation noise); party count
      0x02024029 (+1 = caught); bag pockets ITEMS->KEY ITEMS->POKe BALLS (RIGHT x2).
- [x] Catch skill v1 (src/pokeai/skills/catch.py): menu detect -> BAG -> Balls
      pocket -> throw -> B-mash (advances text + declines nickname) -> party-count
      confirm -> retry until caught/out. scripts/catch_accept.py = the acceptance test.
- [x] Weaken-first (2026-07-05): Catch.attempt(weaken_to=0.30) fights with move
      slot 1 to <=30% enemy HP with a damage-estimate overkill guard; live
      result 4 catches / 4 balls from slot 8 (v1 was ~7%/ball). Nature-from-PID
      (reader.read_nature) added. Nickname-decline exercised in every catch.
- [x] Catcher STRATEGY v2 (2026-07-05): RAM-honest ball accounting (bag read),
      grass-aware hunting (nav_grid grass set - blind pacing drifted out of the
      patch), lead-faint ride-out. slot 9 = post-catch arbiter test bed.
- [x] NeedsArbiter LIVE (2026-07-05): agents/field_brain.py builds ctx facts
      (fainted_count, half_party_low, ball_count, ...) from RAM; drives
      survive/restock_balls/fill_party added to AGENT_ROOTS; executors heal/
      restock/catch with Route1<->Viridian travel; drive+reason on the viewer
      board (stream.py state['drive'] + /api/context). Heal LIVE-VERIFIED
      (fainted party -> 100% at the discovered Viridian Center).
- [ ] Field-brain economy-loop acceptance (`scripts/field_run.py`): survive->
      heal PASSED live; full heal->restock->catch->party-6 run in progress

### G6 (bot B2)
- [ ] Effect catalog + queue + approvals; `POST /api/directive` whitelist v1
- [ ] Channel Point mapping (K6); `!questlist`/`!quest`

### G7
- [ ] type_chart Gen 1->3 deltas; move scoring; multi-mon + potion logic
- [ ] Blackout respawn detection + recovery routine

### G8 (bot B3)
- [ ] Opportunity detector, seed builder, HF generation + guardrails (K7)
- [ ] Prompt/result tables + lift measurement

### G9
- [ ] CrowdControl session (K8); DisruptionMonitor (expected-vs-actual state
      deltas); chaos meter + Medium effects

### G10
- [ ] Walkthrough parser (PART/step/BATTLE/ITEM/HM tags -> StorySteps)
- [ ] StoryDriver: standing ADVANCE_STORY task + completes_when matching

---

## 4. Validation matrix (entire architecture)

The testing reference for loop step 4. Every layer has a cheap check and a
real-surface check; "done" requires the real surface.

| Layer | Cheap check (T0) | Real-surface check |
|---|---|---|
| State reader / perception / planner | `pytest tests/ --ignore=tests/test_dqn_agent.py` (torch/WMI hang; ~19 FireRed + legacy suites) | probe scripts vs live EmuHawk (`scripts/probe_firered_*.py`) |
| Skills + story | ROM-free suites (`test_firered_skills`, `test_firered_story`, `test_firered_pathing`) | `scripts/part1_full_test.py` (and future `partN_full_test.py`) from title/slot, RAM-gated |
| BizHawk bridge | `tests/test_bizhawk_bridge.py` | `scripts/smoke_bizhawk.py` against live EmuHawk |
| Stream ops | (thin; logic lives in worker) | `run_stream.bat`, operator board manual checklist, `curl /api/context` (after G0) |
| Twitch bot | pytest with recorded EventSub JSON fixtures | watchdog T1/T2 runs per the operator doc Testing section; transcripts to `runs/bot/` |
| Story content | `[[Verify]]` tags stay marked in the walkthrough | confirmed in-game during the relevant part, tag removed |

Environment facts (do not rediscover):

- Python: `C:\pokeai-venv\Scripts\python.exe` (junctioned as `.venv`; NEVER
  create a venv inside OneDrive).
- Scripts need `PYTHONPATH=<repo>\src`; Bash tool cwd resets, use absolute
  paths.
- BizHawk runs: start the Python side FIRST (binds 51055), then EmuHawk with
  `--lua=bizhawk/ai_bridge.lua`.
- Windows lets a second stream.py DOUBLE-BIND 8777/51055 next to a stale one
  (no EADDRINUSE), and the stale server answers requests. Before starting,
  kill leftovers: `Get-CimInstance Win32_Process` filtered on stream.py.
- Save slots are checkpoints (`states/slots`); ask Kameron before any HARD
  RESET vs just closing EmuHawk.
- Windows stdout is cp1252; scripts that print é/✓ must reconfigure UTF-8.

---

## 5. What Claude needs from Kameron (park work, don't mock it)

Accounts (set 2026-07-03): **bot = hexagenix**, **channel/broadcaster = 6genix**.
Testing model simplified: NO separate watchdog account. T1 = Claude sends chat
as 6genix in the browser (claude-in-chrome) and observes the bot (hexagenix).

To CONNECT the bot (remaining K3/K4):
1. **Twitch dev app** at https://dev.twitch.tv/console/apps -> client id +
   secret (Kameron creates, pastes into `bot/.env`; template `bot/.env.example`).
2. **OAuth tokens** for hexagenix (send chat) + 6genix (read chat via EventSub).
   Needs the real OAuth flow implemented in `bot/auth.py` (currently a stub) +
   Kameron authorizing each account once. This is the first G1/B0 build step
   once the app credentials exist.
3. **Mod hexagenix** in 6genix chat (`/mod hexagenix`) for the moderation ladder.

Still parked: affiliate-status confirmation (gates Channel Points/polls/
predictions, B1+), `HF_TOKEN` (exists; for B3), CrowdControl account (B4).

---

## 6. Iteration log (newest first)

- 2026-07-06 ~11:50 - **Rehearsal attempt -> the REAL blocker named.** With
  G11 done, stream.py + slot 4 were brought up for the G8/B3/catch_next
  rehearsal: context API live from Cerulean (balls/heal_items fields
  verified), the lingering-gEnemyParty WILD_BATTLE false positive KILLED
  via gMain.inBattle (0x0303352D bit 1, 0-case live-verified;
  battle_probe.active() kept as fallback). BUT the live "storyline"
  strategy is hardwired to run_part1 (stream.py:819) - started from slot 4
  it walked Part 1's bedroom script inside Cerulean. The G10 StoryDriver
  (fact-based cursor + ADVANCE_STORY adapter, T0-complete) was never wired
  into the live strategy, and the slot JSONs carry stale Part-1 task trees
  copied down the slot_2 lineage all session. NEXT SESSION HEADLINE: wire
  story_driver into stream.py's storyline runner (cursor from live facts +
  slot marks), refresh slot metas, then run the full T2 rehearsal (5+ B3
  asks, !redeem catch_next in a live wild battle, transcripts to runs/bot).
  catch_fill6 no-ops at party 6/6 - a bench-management (box/release) seam
  is also missing for G12 prep. stream.py left up (boards live, Cerulean).
- 2026-07-06 ~11:30 - **G11 JOURNEY DONE + the walker redesign that earned
  it.** Kameron called it live ("the pathfinder is the problem - you are
  not utilizing the map"): a multi-agent audit (37 defects, 2 adversarial
  design reviews) proved the BFS planner fine and the WALKING layer broken -
  go_to blacklisted walkable tiles whenever a battle/menu ate a press,
  restarted whole approaches per interruption, take_warp detoured around
  doors and its blind held-DOWN fallback walked back OUT of cave exits, and
  confirm_real_battle's movement probe jiggled the player between retries.
  NEW: Navigator.walk_to (plan once, per-press expected-tile verify with
  2-tile ledge hops, interrupt_check -> resolve + RESUME the same path,
  call-scoped evidence-gated blacklist) + take_warp2 (plan-length approach
  choice, geometry-guarded final press, landing validated vs the warp
  table, warped/wrong_warp/no_fire/unreachable statuses) + assume_locked
  battle confirmation (no jiggle when the walker proved the freeze). Proven
  live: 7 wild battles resolved IN-PATH within one take attempt. 11 new
  ROM-free walker tests (simulated world), 581 total. Other tonight-lore:
  Repel pipeline (Pewter mart door (28,18)->(6,3), hand-driven purchase
  session, bag-use flow via the RAM-solved START-menu cursor 0x020370F4 -
  FRLG cannot SELECT-register normal items), try_fossil removed from the
  hop loop (NPC-interact sink), visited-map persistence, B2F guard trainers
  beaten. Kameron hand-finished Mt. Moon east (TM46/TM09/Rare Candy/Star
  Piece, DOME fossil - fossil choice flagged as a future viewer POLL
  moment), then the runner finished stage E/F solo: CERULEAN (3,3), Center
  (7,3) door (22,19), healed 167/167, slot 4. Cerulean minimap anchor
  PRECISE (4224,640). EmuHawk lore: the bridge lua only advances frames
  while a client drives it - "frozen game + static counters" between
  clients is by design, and a killed client mid-battle-trigger leaves RAM
  holding a nascent battle that eats the next session's first presses.
- 2026-07-06 ~04:30 - **Bot B3 BUILT (engine complete at T0)** + Mt. Moon
  post-mortem. B3: bot/asks.py = opportunity detector (60s loop; trigger
  table + chat velocity + hard suppression states), seed builder (all doc
  fields, recent-5 anti-repetition), HF 3-candidate generation (K7 token via
  bot/.env) with an HONEST template fallback (each interaction_prompts row
  records generator=hf|template), guardrail filter (blocked/guilt/lurker
  phrases, no-deception interaction-handle rule, 180-char cap, shouting),
  scorer per the doc's factors, 3-minute lift window into
  interaction_prompt_results, per-type cooldown budgets exactly as tabled
  (boss prep once per boss; ledger survives restarts), live.py wiring behind
  the kill switch. 34 new T0 tests -> 220 bot / 570 total. /api/context now
  exposes balls + heal_items for the resource triggers. Open: the T2
  rehearsal clause (5+ asks matching live state, clean transcript).
  **Mt. Moon exit mystery SOLVED**: the ~3h "door won't fire" was a
  MOVE-LEARNING MODAL ("Delete a move to make room for BITE?") freezing all
  movement; B cannot dismiss it (No -> re-prompt). Cleared A+DOWN+A (CLAW:
  Tackle/TailWhip/BITE/Withdraw; Bubble lost, acceptable post-Brock). Door
  fired instantly after. LESSON: screenshot FIRST on any input-eating wedge;
  battle code should detect this modal (operator-doc policy seam, unbuilt).
  G11 stage E in flight: alternating EAST/SOUTH legs on Route 4 east (EAST-
  only pins at flood extremes it cannot enter: (21,10), (77,11)).
- 2026-07-05 ~18:45 - **G6 buildable half VALIDATED LIVE IN REAL CHAT (T2)** +
  G10 live replay PASS. With stream.py running catch_fill6 (Field Brain
  catching on-stream) and the bot live in #6genix: !party answered with the
  LIVE party from RAM (including the Rattata caught seconds earlier on
  stream); !effects listed the B2 catalog; **!redeem show_party queued ->
  EffectConsumer -> POST /api/directive -> executed at a safe point 16s
  later** (GET /api/directives status=executed). The full bot->AI seam works
  on the real surface. G10: story_replay.py PASSED against recorded slots
  (5 fact-steps from RAM, cursor at Part 3, no hand-coded steps). REMAINING
  (all Kameron-gated or large): K6 affiliate -> polls/channel points (G4
  poll clause + G6 payment source), /mod SagaciousWizard -> moderation T1,
  K8 -> G9 CrowdControl, bot B3 (HF engine; buildable next session), G8
  stream-rehearsal clause. Kameron pinged twice (K6 + /mod; badge news).
- 2026-07-05 ~18:35 - **BOULDER BADGE EARNED (G8 game half).** forest_grind
  leveled CLAW 7->10 (serpentine sweep, heal-when-lead-down, flee-on-heal-
  trips; the whole Pewter<->forest nav chain exercised ~6 round trips).
  brock_run: Pewter gym trainer beaten (CLAW ->lv12 mid-gym), then Brock
  swept (Geodude 31->0, Onix 33->0, CLAW barely scratched) - Bubble 4x via
  the gen3 chart's choose_move. FLAG_BADGE01 0x820 + badges==1 + payout all
  RAM-verified; slot 2 = Boulder Badge, slot 3 = leveled pre-Brock.
  Also: StoryDriver (G10 second half) landed at T0 (46 tests: Parts 1-2
  replay from facts snapshots; 10 auto-steps, 16 manual marks enumerated).
  Door lessons hardened: gate mats have DUD tiles (center-first row sweep);
  buildings exit via leave_building, never warp probing; heal trips FLEE.
  Warts logged honestly: Pewter mart discovery hit a house (sold/rebought
  balls, net harmless - needs a shop-menu signature probe before reuse);
  stream-rehearsal clause of G8 + B3 still open; wild/trainer classifier
  split now unblocked (0x02022B4C) but not yet wired into stream_state.
- 2026-07-05 ~15:30 - **G7 DONE (caveats in §2): Pewter reached, battle v2
  live-proven.** gBattleTypeFlags 0x02022B4C verified (rival-vs-wild diff
  probe; bit 3 = trainer). Battle v2: both-side active-slot tracking,
  type-scored moves, send_next_mon (the send-next/forced-party screen after
  our faint CANNOT be B-declined in a trainer fight - the resume probe beat
  Sammy's lv9 Weedle across two of our faints, payout-verified). Forest
  navigation lesson: greedy north-flooding dead-ends in the maze (walled
  pocket (28,5)); exits are deterministic via the WARP TABLE (northmost warp).
  Map ids recorded: Route 2 (3,20), forest gates (15,0)/(15,3), forest (1,0),
  Pewter (3,2), Pewter Center interior (6,5) door (17,25). slot 3 = Pewter
  Center (party 6, healed 96/96). NEXT: G8 grind sweep (level for Brock +
  clear Rick/Doug + exercise blackout recovery), then Brock via fight_smart.
- 2026-07-05 ~14:00 - **G3 DONE: Part 2 fully complete, all stages RAM-gated.**
  part2_full_test.py: heal (Center) -> parcel (Mart scene) -> descend to
  Pallet -> Oak delivery (dex flag 0x829 SET + 5 balls; the working mechanic
  is deliver_oak's walk-to-(6,3)-then-UP approach, scene auto-fires - an
  NPC-sort interact failed first) -> Daisy TOWN MAP (id 361 discovered; rival
  house door (15,7)->(4,2), Daisy (5,4)) -> north to Viridian -> old man
  TEACHY TV (id 366, npc (18,5), demo ridden with A) -> slot 6 = Part 2
  COMPLETE. Event flags verified BY ID beforehand (slot 2 vs 6 diff: exactly
  0x829 + story flags). Lesson: every stage that talks through a counter or
  scene needs the movement-verified ride-out; cross_map got the same
  interior-escape guard as travel. Also landed while it ran: stream.py
  POST /api/directive whitelist v1 + worker consumption at safe points +
  GET /api/directives; bot-side DirectiveClient + EffectConsumer in the pump
  loop + !effects/!redeem/!questlist/!quest (bot tests 136->167). G6's
  buildable half is now code-complete pending T1 chat validation.
- 2026-07-05 ~13:30 - **G5 DONE: the Field Brain economy loop ran END TO END
  live** (field_run.py PASS, 4 arbiter cycles, ~11.5 min): survive->healed
  (fainted CLAW -> 100% at the Viridian Center), restock_balls->restocked
  (+8 balls, -1600, per-round money-verified), fill_party->party_full
  (weaken-first catch, 1 ball), explore-fallback->heal top-up -> complete.
  Then validated ON STREAM: catch_fill6 dispatches through stream.py, drive+
  reason live on the viewer board ("FILL_PARTY - Party at 1/6 - hunt the
  grass and catch"). Party of 6 (CLAW + 4 Pidgey + Rattata) saved slot 9.
  HARD-WON LESSONS (each live-diagnosed, committed separately):
  (1) menu_up must NORMALIZE the cursor to FIGHT before probing - the cursor
  rests on BAG/RUN after throws/flees and the old RIGHT-probe deterministically
  failed (walker wedged against a battle screen for 7 silent minutes).
  (2) Battle.my_stats must track the ACTIVE slot (first non-fainted), not
  slot 0 - a fainted lead misreported 'lose' in every new battle.
  (3) The forced 'Choose a POKeMON' screen after a faint cannot be B-cancelled;
  the faint resolver walks the party cursor and sends a healthy mon, then RUNs.
  (4) advance_dialogue's brightness check false-negatives on bright interiors:
  the nurse's closing box stranded the player at the counter. Movement-verified
  ride-outs everywhere (A-based for dialogue, B-based inside shop menus).
  (5) Shop buying: open-loop qty presses are unverifiable (list-cursor wrap ate
  them); settle-paced SINGLE-UNIT rounds, each verified by the money delta.
  (6) Mart counter geometry corrected: clerk (2,3), customer tile (4,3) face
  LEFT (the recorded (6,2) was never interaction-verified). Center = door
  (26,26) -> interior (5,4), nurse (7,2), stand (7,4) (7/3 mis-ID corrected
  via the FRLG reference map).
  (7) stream.py start-from-slot restored the SLOT's strategy over the
  operator's pick - live selection now wins.
  ALSO LANDED (parallel agents, all T0-green): bot gating engine (28-state
  matrix) + B2 effect catalog/queue + Helix delete/timeout + mod-badge parsing
  (bot tests 58->136); Gen-3 battle knowledge from the pokefirered decomp
  (chart/354 moves/151 species, 22 tests); walkthrough parser (21 parts, 703
  steps, 24 tests); stream_state classifier v2 (pure fn, 11 tests); bag/flags/
  nature/moves reader APIs (bag LIVE-VERIFIED). Suites: 63+136 green.
  NEXT: G3 acceptance (probe_event_flags then part2_full_test end-to-end),
  then G7 (battle v2 has its Gen-3 data), G4/G6 bot halves are pre-built.

> **NEXT SESSION PICKUP:** G5 CATCHING SOLVED + core-gameplay slice proven.
> The action-menu blocker is GONE: menu-up = action cursor `0x02023FF8` responds
> to RIGHT/LEFT (stable-at-rest test rejects intro noise); advance intro/decline
> nickname with B; catch confirm = party count `0x02024029` +1; bag pockets
> ITEMS->KEY ITEMS->POKe BALLS (RIGHT x2). `skills/catch.py` (retry until
> caught/out) PASSED `scripts/catch_accept.py` (party 1->2, wild Pidgey).
> `strategies/catcher.py` (fill-to-6) drives it and is registered as the
> `catch_fill6` selectable strategy in stream.py. slot 8 = Route 1 + balls
> (iterate here). FRLG roots ported (`docs/AGENT_ROOTS.md`, parses clean).
>
> IMMEDIATE NEXT (CORE_GAMEPLAY §10 steps 3-5):
> 1. WEAKEN-FIRST: full-HP catch rate is low (~7%/ball), so 5 balls often catch
>    0-1. Add a weaken phase (damage to <~30% HP, ideally a false-swipe/status)
>    before throwing so the fill-loop actually fills. This is the real gate on a
>    green multi-catch strategy run, not a code bug.
> 2. WIRE NeedsArbiter (needs.py) to dispatch catch/heal/restock over live state.
>    Extend brain_agents.py `_context` with the facts the roots port flagged
>    MISSING: per-mon fainted count, "half party low", ball count (bag qty addr
>    still unverified). Show the winning drive + reason on the viewer board.
> 3. buy_item + heal skills (reuse the menu-state work: 0x02023FF8 + bag pockets).
>
> EARLIER THIS SESSION: G1 BOT B0 LIVE (SagaciousWizard in 6genix chat). G2 PART 2
> COMPLETE (parcel delivered, Pokedex + 5 balls, slot 6). Nav stack (ledge-hop,
> battle-flee, waypoints, minimap). Slots: 5=Viridian+parcel, 7=Oak lab+parcel,
> 6=delivered+balls, 8=Route1+balls.
>
> STORYLINE AFTER: route Pallet->Viridian(old man passable)->Viridian Forest->
> Pewter->Brock (Gym 1); G7 battle v2 (type moves, multi-mon, potions, blackout
> recovery); bot B0 polish (DELETE/TIMEOUT enforcement, mod-badge) + B1 (needs
> 6genix AFFILIATE for Channel Points/polls). Loop per phase, commit each win.


- 2026-07-03 ~19:10 - **G5 CATCHING SOLVED + core-gameplay first slice PROVEN.**
  Cracked the action-menu blocker via RAM: cursor `0x02023FF8` responds to
  RIGHT/LEFT only when the menu is up (stable-at-rest filter kills the intro-
  animation false positive that a naive diff hit at 0x02023BC8); advance intro
  and decline the nickname prompt with B so the detect race can't strand us in
  FIGHT; bag pockets ITEMS->KEY ITEMS->POKe BALLS (RIGHT x2); catch confirmed by
  party count `0x02024029` +1. Built `skills/catch.py` (retry until caught/out) +
  `strategies/catcher.py` (fill-to-6) + `catch_fill6` in stream.py. Acceptance
  `scripts/catch_accept.py` PASSED (party 1->2, wild Pidgey, clean overworld
  return). FRLG roots ported (Sonnet subagent). Finding: full-HP catch rate is
  low, so weaken-first is the next gate for a green multi-catch fill run.
- 2026-07-03 ~16:45 - G5 CATCHING started: slot 8 (Route 1 + balls) checkpoint,
  real-battle triggering works, FRLG wild-battle intro/menu flow fully mapped
  (6 probe runs). Blocker recorded: action-menu reach needs RAM state detection,
  not fixed timing. Teed up for next session.
- 2026-07-03 ~16:25 - **G2 PART 2 CORE DONE:** Oak's Parcel delivered (Pokedex
  + 5 Poke Balls, slot 6). FRLG delivery mechanic learned: walk UP to Oak at the
  lab top-center, scene auto-fires (deliver_oak.py). Bot Discord/YouTube links
  set to real URLs. Next: catching (have balls now) + route to Brock.
- 2026-07-03 ~16:00 - **G1 BOT B0 IS LIVE.** OAuth done (SagaciousWizard=bot,
  6genix=channel; `python -m bot.authorize bot|broadcaster`), live EventSub
  runtime (bot/live.py) connects + subscribes to channel.chat.message and
  routes greeter->moderation->commands, sending via Helix. VALIDATED in real
  6genix chat: first-time + returning greetings, !discord/!party/!rules/!badges,
  game-offline fallback, reply-threading, self-filter. Secrets in gitignored
  bot/.env. Run ONE instance only (dup replies came from a leftover process).
  Remaining B0 polish: real discord/youtube links (placeholder REPLACE_ME),
  DELETE/TIMEOUT enforcement via Helix mod endpoints, mod-badge detection.
- 2026-07-03 ~13:50 - G2 Part 2 delivery 95%: REGENERATED clean slots 0-5 under
  current ROM (old slots' map-loop was a mismatched-ROM artifact; fresh
  geography is linear + verified). part2_deliver navigates slot 5 -> Route 1
  ledge-hop+battle-flee descent -> Pallet -> Oak's lab, all working. Only the
  final Oak parcel hand-off unresolved (event fires but parcel stays in bag;
  need to ID Oak's NPC/trigger). Committed: ledge-hop pathing, descend fixes,
  parcel dialogue-clear, battle helpers.
- 2026-07-03 ~13:30 - G2 Part 2: Oak's Parcel OBTAINED + verified (bag KeyItem
  349), slot 5. Delivery drive reached Oak's-lab-bound multi-map descent; added
  ONE-WAY LEDGE-HOP pathing (bfs jump edges + nav_grid ledge_dir) so the agent
  descends ledge-fenced routes (verified full Route 1 descent). Blocked on
  save-slot map inconsistency after an EmuHawk restart -> regenerating clean
  slots under the current ROM (operator-approved). ROM-restart gotcha recorded.
- 2026-07-03 ~12:30 - MINIMAP shipped (operator-requested durable unblock,
  pulled forward from G4/UI). /api/minimap serves the AI's live walkability
  grid (walls/floor/grass/ledge + player/doors/npcs), cached per map. Vanilla
  canvas panel on both boards (viewer hero + operator nav aid), verified live
  at Viridian. Now nav is observable to both operator and agent, so building
  ID / route debugging stops costing blind emulator round-trips. Front-end
  delegated to a Sonnet subagent (58->116 tokens saved by tiering). Minor
  cleanup owed: an em-dash in the load-slot narration string violates the
  no-em-dash rule.
- 2026-07-03 ~10:30 - G2 traversal: Route 1 -> VIRIDIAN reached (map 3,1, slot
  4) via ledge-aware planner. Fixed the on-stream pathfinder loop (vision now
  decodes metatile behaviors; go_to replans around walls, warp-safe). Building
  IDs corrected with operator help (was mis-IDing houses/gym as the Center and
  forcing the unreachable gym door). Heal deferred; parcel quest is next.
- 2026-07-03 03:20 · G1 code-side DONE at T0 (Sonnet subagent): bot/ package
  (16 files) + tests/bot (58 tests) all passing, ruff clean; full suite 305
  green. G1 now blocked ONLY on K1-K5. Goal stays open until T1 in real chat.
- 2026-07-03 03:00 (approx) · G2 foothold: Route 1 reached (map 3,19), slot 3
  checkpoint, first wild battle won via Battle.fight. Ledge + grass-pacing
  lessons encoded in route1_wild_probe.py. Remaining G2: flee, grind, heal,
  Potion man, Viridian.
- 2026-07-03 02:50 · G0 DONE + acceptance PASS on live RAM (check_api_context:
  CLAW lv6 $3080 PALLET_TOWN from slot 2). Fixes: read_range takes an END
  address; stale stream.py can double-bind 8777 (kill leftovers first). git
  repo live: c8bfcc1 initial commit, tag part1-complete, .git at C:\pokeai-git.
- 2026-07-03 02:40 · Bot B0 T0 scaffold delegated to a Sonnet subagent
  (bot/ package + tests/bot fixtures/tests per operator doc).

- 2026-07-03 · Roadmap created. Docs synced: operator doc got status header,
  live-stack bridge section, PokéCoins rule, state detectability, testing
  tiers + watchdog spec, implementation plan B0-B5. ARCHITECTURE.md gained §0
  (FireRed/BizHawk era). FIRERED_REDESIGN.md status updated (BizHawk pivot,
  F-phase reality). Nothing built yet; next = G0.
