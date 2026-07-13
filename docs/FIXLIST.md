# FIXLIST — 2026-07-06 cleanup & review run

Defects found during the cleanup/review pass (Kameron's directive: review
first, fix later — nothing here gets fixed until the review run completes).
Sources: live fresh-start validation + the doc-vs-code audit workflow.
Severity: blocker > major > minor > polish.

## Manual Findings

### Operator Panel
- [ ] Quest Queue does not update as the storyline runs
- [ ] Quest queue does not have optional quests

#### Viewer Panel
- [ ] minimap does not reflect the real-time in game movement
- [ ] North star is unhelpful for viewers because its too broad of a statement and needs to update based on quests
- [ ] Quests are showing raw data instead of verbose and AI "thoughts"

#### Storyline

- [ ] Storyline froze or appears to freeze in Viridian forest when encountering pokemon

## Live findings (fresh-start validation)

- [x] **FL-1 (blocker) — FIXED + LIVE-VERIFIED 2026-07-06.** lua op 'B'
  (client.reboot_core) + BizHawkBridge.reboot() + from=new power-cycles
  before run_intro. Two live New Game runs rebooted to the title cleanly.

- [x] **FL-2 (blocker) — FIXED + LIVE 2026-07-06.** Continuous fact-gated
  dispatcher in stream.py (run_storyline): parts 1-4 as callable agents
  (agents/story_part2/3/4.py, 43 tests), each internally fact-gated; one
  Start press plays the whole built range from ANY save. Live acceptance in
  progress: dispatch from Route 1 correctly skipped Part 1 and is running
  Part 2 (parcel picked up at the Viridian Mart).

- [x] **FL-3 (major) — RESOLVED BY FL-2's design.** Dispatch now reads live
  FACTS, never slot task trees - the stale JSONs are cosmetic board data
  only. Operator-path saves already write correct trees (verified slot 1,
  13:07). Script save_slot was dropped from the ported agents. Old slot
  JSONs (2/4/5/7) left as historical checkpoints.

- [ ] **FL-4 (major) — catch_fill6 no-ops at party 6/6 with no bench
  management.** "Fill the Party" completes instantly (party full of junk
  Pidgeys); there is no box/release seam, so G12's type-coverage catches
  (Oddish/Bellsprout/Pikachu) cannot be made. Fix: bench-management skill
  (PC box deposit via the Center PC, or catch-replace policy) + a
  "catch_specific" strategy that targets species.

- [x] **FL-5 (minor) — FIXED + LIVE-VERIFIED 2026-07-06.** Intro chains
  straight into Part 1 under the storyline strategy ("Chaining into
  Part 1." seen in both acceptance runs).

- [x] **FL-6 (blocker) — FIXED + LIVE-VERIFIED 2026-07-06.** rival1 +
  route1 ported into the live agent (scripts/rival1.py logic); the rival
  LOSS is handled as the game-legal outcome (white-out home, story intact,
  continue). Acceptance: one Start press ran reboot -> intro -> Part 1 ->
  starter -> rival (lost, rode it out) -> Route 1, fully hands-off.

- [ ] **FL-7 (major) — run_part1 is not resumable.** No fact checks: run
  from mid-part it executes bedroom steps against whatever map it is on
  (takes `nav.map_warps()[0]` of the CURRENT map as "the stairs"). Same
  class as FL-2; fix together (fact-gated steps per the StoryDriver).

- [x] **FL-8 (polish) — FIXED 2026-07-06.** firered_part1.py header
  rewritten during the FL-6 port: describes the real nickname flow, the
  full step list, and names the operator-input/poll seams as FIXLIST refs.

## Validation observations (fresh run, 2026-07-06)

- Intro stage: PASS on a true fresh boot — title -> New Game -> CLAUDE ->
  GROK -> bedroom (4,1), stream_state PALLET_TOWN, no stalls.
- Part 1 (mom -> Oak intercept -> lab -> starter): PASS — Bulbasaur picked,
  nicknamed CLAW, party 1. Run ends there (FL-6).

## Live findings (dispatcher acceptance run, 2026-07-06)

- Dispatcher fact-gating: PASS — started from Route 1, correctly skipped
  Part 1 (starter present) and ran Part 2; heal + parcel pickup RAM-verified
  (KeyItem 349 in bag).
- [x] **FL-9 (major) — FIXED + LIVE-DIAGNOSED 2026-07-06.** Root cause was
  NOT dialogue (both the Viridian Mart and rival's-house exits failed):
  `leave_building` had been routed through `take_warp2`, which approaches a
  door from the nearest neighbour and presses SIDEWAYS into it - but a
  house door fires ONLY when you walk DOWN onto the real door tile from
  directly above (live-proven: stepping onto the rival-house center door
  (4,8) from (4,7) exited; (5,8) was a dud that never fired from any
  direction, and a side step into (4,8) did nothing). Rewrote
  `leave_building` + new `_exit_door_down`: approach from above, step DOWN,
  retry through a frozen press, step off first if standing on the dud mat.
  2 new tests (DoorWorld: dud-mat + on-mat). Part 2 delivery leg verified
  live (parcel -> Oak -> Town Map). Teachy-TV-step exit now uses the fix.

- [ ] **FL-10 (major) — Part 3 forest traversal stops short of Pewter.**
  The ported `run_part3` forest step (story_part3.py `_flood_north` /
  `warp_exit` northmost pick, from forest_run.py) got the player INTO
  Viridian Forest (map (1,0)) but did not reach the north exit warp to
  Pewter within budget (stalled live at (6,23), fleeing wilds). The forest
  is a warp-table maze; the ported northmost-warp logic needs the same
  resume-capable walk_to/take_warp2 + repel treatment the Mt. Moon crawl
  got, and probably the reachability-gated warp pick. Live-debug next: probe
  the forest warp table + player pocket, confirm the exit warp id, apply the
  walker. (Parts 1-2 + fact-gating into Part 3 all verified live this
  session; this is the first Part-3 step.)

## Dispatcher live-validation summary (2026-07-06)
- Full New Game -> Route 1: PASS (hands-off, one Start).
- Part 2 end to end: PASS (parcel pickup skipped-if-held -> deliver to Oak
  -> Town Map -> Teachy TV -> Route 2), across the FL-9 door fix.
- Fact-gated part handoff: PASS (Part 2 complete -> auto Part 3, no restart).
- Part 3: reaches the forest, stalls at the maze exit (FL-10).

## From the doc-vs-code audit workflow (2026-07-06, 80 agents, 70 confirmed / 1 rejected)

### BLOCKER

- [ ] **live-storyline-hardwired-to-part1** (part1) *(= FL-2)*
  - where: Walkthrough ordered Parts 1-4 vs scripts/stream.py:817-827 and src/pokeai/agents/firered_part1.py:35-44 (known-broken, recorded docs/ROADMAP.md:382-387)
  - doc: The walkthrough is an ordered story spec; a resumed run must continue from its actual position (ROADMAP's G10 StoryDriver exists precisely to cursor into it). ROADMAP section 6 (2026-07-06 ~11:50) names this the 'REAL blocker'.
  - code: stream.py's storyline branch runs run_part1 whenever context intro_done is set, regardless of actual story position (stream.py:817-827). run_part1 is not state-aware: it blindly takes warps[0] of whatever map it is on and talks to the nearest NPC (firered_part1.py:37-44). Started from slot 4 it 'walked Part 1's bedroom script inside Cerulean' (ROADMAP.md:383-384). The G10 StoryDriver was never wir
  - fix: Wire story_driver into stream.py's storyline runner: derive the story cursor from live facts (map id, party, badges, event flags) plus slot marks, and dispatch the matching part runner instead of unconditionally calling run_part1; refresh the stale Part-1 task trees carried in slot JSONs.

### MAJOR

- [x] **available-rewards-never-checked** (op-asks) — FIXED 2026-07-06: resolve_reward() gates asks on fulfillable effects
  - where: Native-Stream-Operator.md 'Minimal implementation logic' ('check available rewards') + 'No deception' guardrail; bot/asks.py:662-728 (tick), asks.py:331-352, bot/effects.py:74-121
  - doc: The 60-second loop must 'check available rewards' before creating a seed, and the seed's reward_name is 'a specific CrowdControl action'; the 'No deception' guardrail requires it be clear how interaction affects the game.
  - code: AskEngine.tick never consults the effect catalog or any reward list. Opportunities hard-code reward_key='pokecoin_support' (asks.py:334, 344) and 'challenge_effect' (asks.py:351), neither of which exists in the only live catalog (bot/effects.py default_catalog: show_party, explain_plan, nickname_next_catch, catch_next_encounter, enqueue_quest_route22). Resource/emergency/chaos templates tell viewe
  - fix: Pass the EffectQueue catalog into AskEngine; in the tick, resolve each opportunity's reward_key against enabled catalog entries (skip or downgrade the ask if absent), and use the real key/name in templates and scoring.

- [x] **recovery-trigger-unreachable-live** (op-asks) — FIXED 2026-07-06: _note_facts derives blackout from hp transitions
  - where: Native-Stream-Operator.md 'Request trigger table' (AI loses battle -> Recovery support) + 'Cooldown rules' Recovery row; bot/asks.py:644 (note_blackout), bot/live.py:206
  - doc: Trigger table: 'AI loses battle -> Recovery support: ask chat to stabilize the run', with a budgeted Recovery request row (20 min / 40 min / 3 per stream). ROADMAP section 6 records the trigger table as built and 'wired into bot/live.py'.
  - code: AskEngine.note_blackout (asks.py:644) has zero callers anywhere in the repo: live.py wires only note_chat_message (live.py:206), and facts_from_context (asks.py:209-227) carries no loss/blackout signal, so recent_blackout is always False in production and the 'recovery' ask type (asks.py:169-175, 321-325) can never fire outside unit tests. The game side does expose signals a caller could use (part
  - fix: Detect blackout/loss in the live loop (e.g. badge-safe heuristics off /api/context: all-party-faint transition, or a blackout event surfaced in ctx['events'] / a dedicated flag from stream.py) and call ask_engine.note_blackout(); the ai side already has blackout recovery (G7), so stream.py can emit the event.

- [x] **analytics-unwired-in-live** (op-b0b1) — FIXED 2026-07-06: analytics counters + end-of-session summary
  - where: Native-Stream-Operator.md B0 build item 8 + P0 'Analytics summary' vs bot/live.py route_chat:198-247 and shutdown:292-294
  - doc: B0 includes analytics counters (messages, chatters, commands) plus an end-of-session summary.
  - code: Analytics is constructed (main.py:44) but the live runtime never calls record_message/record_command/record_greeting/record_moderation_action (grep in live.py: no matches), and shutdown only cancels the pump and closes the store - summary() is never produced. The only place a summary prints is the dry-run demo (main.py:88). In real runs every counter is zero and no post-stream report exists.
  - fix: Call the four analytics record_* hooks from route_chat and log/print app.analytics.summary() in run_live's finally block (and on stream.offline).

- [ ] **b1-naming-flow-missing** (op-b0b1)
  - where: Native-Stream-Operator.md B1 item 4 vs bot/ and scripts/stream.py (no naming code)
  - doc: Naming flow: operator panel text input with Ash/Gary defaults (per the walkthrough feature notes) + viewer poll when live; the winner lands in the operator field the intro naming runner reads.
  - code: No naming code exists anywhere (grep naming/player_name/rival_name in bot/ and scripts/stream.py: nothing). Only the poll half is K6-parked (and ROADMAP 2026-07-06 explicitly adopts free chat polls as the no-affiliate mechanism for the fossil vote, so even that is buildable); the operator-input half was never owner-gated. ROADMAP G4 lists 'naming operator input' as still open. The in-progress fres
  - fix: Add player/rival name fields (defaults Ash/Gary) to the operator panel + expose via the control API; have the intro naming step read them; later feed a free chat-poll winner into the same field.

- [x] **clip-marker-stores-nothing** (op-b0b1) — FIXED 2026-07-06: clip_markers table + context snapshot
  - where: Native-Stream-Operator.md P1 '!clip stores timestamp and context' + clip_markers table (line 284) + B1 item 5 'clip marker wired to the Create Clip API' vs bot/commands.py:236-239, bot/main.py:51-55, bot/store.py SCHEMA_SQL
  - doc: !clip creates a persistent clip marker (timestamp + context; B0 = marker only, B1 = Create Clip API; B1 acceptance: '!clip produces a real clip').
  - code: _cmd_clip replies 'Clip moment marked.' and calls an optional on_clip_marker callback, but neither main.py nor live.py wires one, store.py has no clip_markers table, and no Helix Create Clip call exists anywhere in bot/. The bot tells chat a moment was marked while nothing is recorded anywhere.
  - fix: Add a clip_markers table + store method, wire on_clip_marker in live.py to insert (source=COMMAND, timestamp, stream_state context); B1: call Helix Create Clip (clips:edit scope; not affiliate-gated per K6 note).

- [x] **durable-dedupe-and-message-log-unwired** (op-b0b1) — FIXED 2026-07-06: record_event/record_message in ChatPipeline
  - where: Native-Stream-Operator.md line 194 ('store Twitch message/event IDs and dedupe them before executing actions') + schema twitch_events/chat_messages/moderation_actions vs bot/live.py (no store writes)
  - doc: Event/message IDs are stored and deduped; chat messages and moderation actions are logged (Flow B ends with 'log action').
  - code: store.record_event (store.py:359-393), record_message (store.py:399-453) and record_moderation_action (store.py:459-493) exist but live.py never calls any of them (grep: zero matches). Dedupe is only the in-memory set in eventsub.py:169-173, lost on restart. chat_messages stays permanently empty, which also silently zeroes the B3 lift metrics: asks.py:732-741 fills interaction_prompt_results from 
  - fix: In route_chat: record_event(metadata.message_id) as the dedupe backstop, record_message per chat line (feeding presence counts), record_moderation_action after each enforce.

- [x] **eventsub-reconnect-fragile** (op-b0b1) — FIXED 2026-07-06: keepalive window + welcome-driven resubscribe
  - where: Native-Stream-Operator.md P0 'EventSub connection: Connects, subscribes, reconnects, dedupes' vs bot/eventsub.py:142-143, 201-226 and bot/live.py:288-291
  - doc: The EventSub client reconnects (a P0 acceptance criterion).
  - code: Only the graceful in-protocol session_reconnect message is handled. run_eventsub_client's async-for propagates any abnormal close/network exception, and live.py's `while True` loop has no try/except around it, so one dropped socket unwinds run_live and the bot process dies. session_keepalive is discarded with no keepalive-timeout watchdog, so a half-open dead connection is never detected at all.
  - fix: Wrap the connect loop in try/except with backoff, fall back to EVENTSUB_WSS (not a stale reconnect_url) after errors, and track last-message time against the welcome's keepalive_timeout_seconds to force reconnect.

- [ ] **greeting-state-gating-unwired** (op-b0b1)
  - where: Native-Stream-Operator.md '### State Rules' Greetings column + B1 item 2 vs bot/live.py:208-213 and bot/gating.py GREETINGS (no production consumer)
  - doc: Greetings are state-gated: No during RIVAL_BATTLE/GYM_BATTLE/LOW_HP_DANGER/SAVE_CRITICAL/OFFLINE, Limited during battles; the B1 gating engine is the single source of truth for who may do what per state.
  - code: gating.py encodes the Greetings column faithfully, but the only production consumer of the gating module is effects.py (grep: directives.py/effects.py only). live.py's greeting path never fetches stream_state and never consults gating.allowed(state, GREETINGS) - first-time greetings will fire mid-gym-battle. The Promos and Polls categories likewise have zero runtime consumers.
  - fix: In route_chat, fetch (or cache) stream_state and skip/defer the greeting when gating.verdict(state, GREETINGS) is NO (queue it for the next allowed state rather than dropping the once-ever flag).

- [x] **killswitch-scope-hole** (op-b0b1) — FIXED 2026-07-06: pause reaches sender/commands/greeter/helix/effects/asks
  - where: Native-Stream-Operator.md 'Standing rules' (kill switches built in B0, re-verified every phase) + '## The watchdog' (asserts the bot obeys !bot pause) vs bot/live.py:222-232, 263-284
  - doc: !bot pause is THE kill switch: the paused bot stops acting; the watchdog exercises it every single run.
  - code: KillSwitch only gates the Sender (sender.py:113-120), public command replies (commands.py:211-212), and the B3 ask engine (live.py:278). While paused, route_chat still executes Helix moderation enforcement (deletes/timeouts, live.py:226), still mutates the greeter/viewer DB (live.py:208-213), and pump_forever still runs effect_consumer.tick() (live.py:266-270), POSTing approved game directives to 
  - fix: In route_chat and pump_forever, check app.killswitch.paused before moderator.enforce, greeter.on_active_message, and effect_consumer.tick (mod-only commands stay live).

- [ ] **operator-pause-toggle-and-bot-tab-missing** (op-b0b1)
  - where: Native-Stream-Operator.md 'Standing rules' ('kill switches (!bot pause, operator Pause toggle) are built in B0') + Feature note lines 170-175 + B1 item 6 vs scripts/stream.py (no bot tab) and bot/ (no panel integration)
  - doc: B0 already includes the operator Pause toggle; B1 adds the full operator-panel bot tab (editable name/greeting, pause/strict/promo toggles, connection + EventSub health, last error).
  - code: No bot tab or bot-related toggle exists in scripts/stream.py's operator board (grep 'bot tab|bot_tab': nothing), and the bot exposes no HTTP surface the panel could drive. The only kill switch is the chat command; if chat/EventSub is the broken thing, there is no out-of-band pause.
  - fix: Minimal B0 slice: a tiny local HTTP endpoint on the bot (or a shared flag file) that stream.py's operator board can toggle to pause/resume; B1: full tab with status fields.

- [x] **stream-status-events-ignored** (op-b0b1) — FIXED 2026-07-06: StreamStatusTracker session rollover on online/offline
  - where: Native-Stream-Operator.md B0 build item 3 (subscribe stream.online/offline) + P0 'Returning chatter recognition: once per stream' vs bot/live.py:249-261
  - doc: The bot subscribes to stream.online/offline and greeting recognition resets per stream session; !uptime reports stream duration.
  - code: eventsub.py:104-109 subscribes and eventsub.py:191-194 emits StreamStatusChanged, but on_actions in live.py has no branch for it - the events are silently dropped. Consequences: CommandRouter.stream_started_at is never set (main.py:51-55 omits it), so !uptime always answers 'The stream isn't live right now' (commands.py:224-228) even when live; the stream session is minted once per process start (
  - fix: Handle StreamStatusChanged in on_actions: on online, set commands.stream_started_at and start a new store stream session; on offline, end_stream_session and clear uptime.

- [x] **strict-mode-noop** (op-b0b1) — FIXED 2026-07-06: strict flag wired through main/router/moderation
  - where: Native-Stream-Operator.md 'Mod override controls' + STRICT_MODE state row (line 112) + moderation matrix ('Caps spam -> Strict mode', 'Raid spam -> Enable strict mode') vs bot/commands.py:159, 356-364
  - doc: !strict on tightens moderation, disables promos, and caps redemptions/effects (STRICT_MODE rules).
  - code: _cmd_strict flips CommandRouter.strict_mode and replies 'Strict moderation enabled.', but nothing anywhere reads that flag (grep: only commands.py touches it). gating.py can only reach STRICT_MODE via the raid_spam_detected LiveFact (gating.py:327), which nothing chat-side ever sets. The mod override is a placebo.
  - fix: Share a strict-mode flag (like KillSwitch) consumed by ModerationEngine (lower thresholds/start rungs), the ask engine, and effects gating (force STRICT_MODE state into gate_effect).

- [x] **token-refresh-startup-only** (op-b0b1) — FIXED 2026-07-06: TokenRefresher on the pump cadence
  - where: Native-Stream-Operator.md P0 'Twitch OAuth setup ... token refresh works' vs bot/live.py:98-117
  - doc: Token refresh works (P0 acceptance).
  - code: auth.ensure_fresh_token runs exactly once at startup; the access token string is then baked into the Sender (live.py:116-117), HelixModerator (live.py:123-129), and the subscribe closure (live.py:193). Twitch user access tokens expire in roughly 4 hours, so any longer session silently starts failing every send/moderation/subscription call with 401s and never re-authenticates.
  - fix: Periodic refresh in pump_forever (or on 401): re-run ensure_fresh_token and push the new token into sender/moderator via a shared token provider instead of copied strings.

- [x] **watchdog-t1-harness-missing** (op-b0b1) — FIXED 2026-07-06: Watchdog T1 scenario runner + transcripts
  - where: Native-Stream-Operator.md '## The watchdog' + prerequisites row C1 ('watchdog runner' = Claude-side) vs bot/watchdog.py:120-130, bot/config.py:92-95, bot/greeter.py:50-51, bot/moderation.py:149-151
  - doc: T1 = a second modded Twitch account driven by a pytest scenario runner; first-time chatter simulated by resetting the watchdog's viewer-DB row (test-only flag); every T1/T2 run writes a transcript to runs/bot/; the runner exercises greetings, moderation ladder, mod overrides and the kill switch.
  - code: Only the pure scenario engine exists (run_scenario, fake transport). connect_watchdog raises NotImplementedError with a stale message claiming K1-K5 are all missing (K1/K3/K4/K5 are recorded DONE in ROADMAP.md §2/§6). No transcript writer exists anywhere (grep 'runs/bot' hits docs only; ROADMAP 2026-07-06 log still lists 'transcripts to runs/bot' as future). No viewer-DB reset flag exists in store
  - fix: Build the C1 runner: real transport over the TWITCH_WATCHDOG_REFRESH_TOKEN (config slot already exists), synthetic allowlist for the watchdog id, store method to reset a viewer row behind a test flag, transcript writer to runs/bot/, and a scenario that includes !bot pause every run. Update connect_watchdog's prerequisite message to only what is actually missing (K2, if anything).

- [x] **clip-marker-not-stored** (op-commands) — FIXED 2026-07-06: clip_markers table + context snapshot
  - where: Native-Stream-Operator.md command set line 433 ('!clip Mark current moment'), B0 item 6 line 838 ('!clip (marker only)'), P1 line 204 ('!clip stores timestamp and context'), Flow E line 333 vs bot/commands.py:236-239 + bot/main.py:51-55 + bot/store.py:8
  - doc: !clip creates/stores a clip marker (timestamp + context) even in B0's marker-only form; Flow E scores stored markers into a post-stream top-10 report.
  - code: _cmd_clip calls the optional on_clip_marker hook and always replies 'Clip moment marked.', but the live wiring never passes on_clip_marker (main.py:51-55 CommandRouter gets only context_api/killswitch/effects) and Store has no clip_markers table (store.py:8 defers clips to later phases). In production !clip persists nothing while telling the viewer it did.
  - fix: Add a clip_markers table to Store (session_id, viewer, source, timestamp, context) and wire on_clip_marker in build_app to insert a row (timestamp from clock, context from /api/context snapshot); only reply 'marked' when the insert succeeds.

- [x] **quest-not-mod-approval-gated** (op-commands) — FIXED 2026-07-06: !quest + enqueue_quest redeem mod-gated
  - where: Native-Stream-Operator.md 'Pokemon-specific commands' line 454 vs bot/commands.py:180,298-301 + bot/main.py:47-50 + bot/effects.py:213-229
  - doc: '!quest [quest name]  Enqueue an optional quest (mod/approval-gated)'.
  - code: 'quest' is not in _mod_only (commands.py:180 = {'bot','strict'}), so any viewer can invoke it; and main.py:50 builds EffectQueue(auto_approve=True), so when the state gate allows (enqueue_quest_route22 is LOW risk, allowed up to MEDIUM in ROUTE_TRAVEL/BETWEEN_OBJECTIVES per gating.py:100,120) the entry is written directly as APPROVED with resolved_by='auto' (effects.py:215-228) and later executed 
  - fix: Either add 'quest' to _mod_only, or exempt QUEST_EFFECT_PREFIX keys from auto_approve (leave them QUEUED for the operator, e.g. an Effect.requires_approval flag checked in EffectQueue.submit before the auto_approve promotion).

- [x] **strict-mode-is-a-noop** (op-commands) — FIXED 2026-07-06: strict flag tightens moderation ladder
  - where: Native-Stream-Operator.md 'Mod override controls' (line 357), STRICT_MODE state row (line 112), watchdog spec (lines 731-732 'asserts the bot obeys') vs bot/commands.py:356-364
  - doc: !strict on/off is a mod override that enables strict moderation: STRICT_MODE tightens moderation, disables promos, restricts channel points/effects ('Raid spam -> Enable strict mode and pause redemptions'), and the T1 watchdog must assert the bot OBEYS the override.
  - code: _cmd_strict only flips self.strict_mode (bot/commands.py:159, 359, 362) and replies 'Strict moderation enabled.' Grep across bot/ shows no other reader of strict_mode: ModerationEngine scoring, the gating module, the ask engine, and the effect queue never consult it. The flag changes zero behavior; the confirmation message is false.
  - fix: Wire router.strict_mode into the things the doc says it controls: pass it (or a shared flag object like KillSwitch) into ModerationEngine.score (lower thresholds), the AskEngine/promo path (suppress), and EffectQueue.submit (treat state as STRICT_MODE, i.e. cap at RiskTier.SAFE per gating.py:122/152).

- [x] **uptime-never-sees-stream-online** (op-commands) — FIXED 2026-07-06: StreamStatusTracker stamps stream_started_at
  - where: Native-Stream-Operator.md command set line 433 ('!uptime Stream duration') + B0 items 3/6 (lines 833-840) vs bot/commands.py:224-228 + bot/live.py:249-261 + bot/eventsub.py:191-194
  - doc: !uptime reports stream duration; B0 subscribes stream.online/offline precisely so the bot knows live status.
  - code: eventsub.py does subscribe and emits StreamStatusChanged(online=True/False) (eventsub.py:105-109, 191-194), but live.py's on_actions handles only Subscribe/ChatMessageReceived/Reconnect/Log (live.py:249-261) and silently drops StreamStatusChanged. Nothing ever sets CommandRouter.stream_started_at (constructor default None, main.py:51-55 does not pass it; grep finds no other writer), so !uptime rep
  - fix: Add an elif isinstance(a, eventsub.StreamStatusChanged) branch in live.py on_actions: set app.commands.stream_started_at = time.time() on online=True, clear on offline; optionally seed from Helix Get Streams at startup so a bot restarted mid-stream still knows.

- [ ] **catch-next-armed-flag-never-consumed** (op-effects)
  - where: Native-Stream-Operator.md B2 T2 acceptance (line 823: "'attempt catch next encounter' redemption ... executes in a real wild battle") — vs scripts/stream.py:730-733, src/pokeai/skills/journey.py:118-123 and 141, scripts/part4_run.py:140
  - doc: An armed catch_next_encounter directive is executed by the agent in the next real wild battle.
  - code: serve_directives arms the order with c.set(catch_next=True) (stream.py:731) and reports 'armed', but nothing in the repo ever reads state['catch_next']: WildPolicy.should_catch defaults to lambda: False (journey.py:123) and every WildPolicy construction site (part4_run.py:140, probes) omits should_catch. The flag is also never cleared, so single-shot semantics are unimplemented too. The armed orde
  - fix: Pass should_catch=lambda: CTRL.state.get('catch_next') into the WildPolicy used by the stream.py-hosted runs, and clear the flag (plus report the real outcome) after the attempt.

- [ ] **directive-consumption-starves-during-storyline-runs** (op-effects)
  - where: Native-Stream-Operator.md B2 item 3 / P2 Game directive API (line 218: 'the agent consumes them at safe points') — vs scripts/stream.py:691-693, 755-767, 817-827
  - doc: The agent consumes queued directives at safe points while it plays; the bot gates effects on the live stream_state from /api/context.
  - code: serve_directives runs only from the pre-Start idle loop (stream.py:763) and inside stats_tick (stream.py:693). stats_tick is threaded into the intro (intro.tick, line 804) and catch_fill6 (narrate -> tick, lines 513-521/816), but the storyline dispatch calls run_part1(ow, nav, skill, Hooks(c)) with no tick (lines 820-827; Hooks has no pump, lines 477-490). During a run of the DEFAULT strategy, POS
  - fix: Thread stats_tick (or a narrate-style pump) through run_part1 the same way the intro and catch_fill6 paths do, so ctx refresh + serve_directives ride every storyline step.

- [ ] **executed-on-accept-async-failure-never-refunds** (op-effects)
  - where: Native-Stream-Operator.md Flow C (line 315: 'game bridge executes effect -> mark EXECUTED or FAILED -> if failed: mark REFUND_REQUESTED') and B2 T2 (line 823: 'executes in a real wild battle, marks EXECUTED') — vs bot/directives.py:244-255 and 265-287, bot/effects.py:331-346
  - doc: EXECUTED is marked when the effect actually executes in-game; a failed effect is marked FAILED and refund-marked.
  - code: EffectConsumer.tick marks the entry EXECUTED the moment stream.py merely queues the directive (directives.py:247, docstring: 'accepted-by-the-AI-queue == EXECUTED, armed included'). When the AI later reports the directive failed (e.g. note=unsupported_v1), _relay_outcomes (directives.py:265-287) only sends a chat message; the entry stays EXECUTED, is never flipped to FAILED, and the refund mark is
  - fix: Track entry_id alongside the awaited directive id; on an async 'failed' outcome call a new EXECUTED->FAILED transition that sets refund_marked for paid entries (and consider not starting the cooldown until a real 'executed'/'armed' outcome).

- [ ] **no-operator-approve-reject-surface** (op-effects)
  - where: Native-Stream-Operator.md B2 item 2 (line 866-867 'operator approve/reject in the bot tab'), operator-panel layout (line 805 'Center panel - redemption/effect queue - approve/reject'), mod commands '!effect approve/reject <id>' (line 439) — vs stream/operator.html (entire file), bot/main.py:47-50, bot/effects.py:255-287, bot/commands.py:335
  - doc: The effect queue has an operator approve/reject step surfaced in the operator panel's bot tab (and mod commands !effect approve <id> / !effect reject <id>).
  - code: No bot tab exists anywhere: stream/operator.html has only status/minimap/run-controls/strategy/quest-queue/slots/log cards, with no effect-queue view or approve/reject buttons; no !effect approve/reject command exists in bot/commands.py. EffectQueue.approve()/reject() (bot/effects.py:255-287) have zero production callers. The live bot compensates with auto_approve=True (bot/main.py:50, comment adm
  - fix: Add a bot tab to stream/operator.html (or a bot-owned panel) listing effect_queue rows with Approve/Reject buttons wired to EffectQueue.approve/reject (needs a small HTTP seam into the bot process), plus !effect approve/reject <id> mod commands; drop auto_approve=True once the surface exists.

- [ ] **two-whitelist-verbs-always-unsupported** (op-effects)
  - where: Native-Stream-Operator.md B2 item 3 (lines 868-870: whitelist v1 = show_party, catch_next_encounter, nickname_next_catch, enqueue_quest(route22), explain_plan; 'the agent consumes directives at safe points') and item 5 (line 872: '!quest backed by the optional-quest queue') — vs scripts/stream.py:206-207, 704-735, 86
  - doc: All five whitelist-v1 directives are consumable by the agent; enqueue_quest(route22) feeds the game-side optional-quest queue.
  - code: DIRECTIVE_WHITELIST (stream.py:206-207) accepts nickname_next_catch and enqueue_quest, but serve_directives handles only show_party, explain_plan and catch_next_encounter; the other two always hit the else branch and finish as failed/'unsupported_v1' (stream.py:734-735). enqueue_quest is never wired to Control.queue_add, and QUEST_CATALOG is empty anyway (stream.py:86), so the bot's !quest route22
  - fix: Implement the two handlers in serve_directives: enqueue_quest -> add the route22 entry to QUEST_CATALOG and call c.queue_add; nickname_next_catch -> arm a nickname flag consumed by the catch flow (like catch_next).

- [x] **cutscene-detectable-now-not-emitted** (op-states) — FIXED 2026-07-06 (classifier v3, tests/test_stream_state.py)
  - where: Native-Stream-Operator.md lines 105 + 122-123 ("Detectable now: ... CUTSCENE (control lock)"); src/pokeai/ui/stream_state.py:26-58; scripts/stream.py:666-671
  - doc: CUTSCENE is detectable now via the control lock, and its row forbids all game effects ("No").
  - code: classify() has no control-lock input and never returns CUTSCENE; stream.py's stats tick does not pass one. A control-locked cutscene in the overworld classifies as PALLET_TOWN/ROUTE_TRAVEL, whose rows allow Low or Low/medium effects. The control-lock read the doc references exists (frozen bit, src/pokeai/skills/overworld.py:22,71 and scripts/probes/probe_control.py) but is unwired.
  - fix: Pass the frozen/script-lock bit into classify() and return CUTSCENE when it is set outside battle/saving.

- [x] **gym-battle-boss-transition-never-emitted** (op-states) — FIXED 2026-07-06 (classifier v3, tests/test_stream_state.py)
  - where: Native-Stream-Operator.md lines 94, 107, 131-132 ("lands with the Brock arc") and B3 phase row line 824; src/pokeai/ui/stream_state.py:38-58 (no GYM_BATTLE/BOSS_TRANSITION branch)
  - doc: GYM_BATTLE = No promos/greetings/polls, Safe-only channel points and effects, "Disable chaos effects"; BOSS_TRANSITION = predictions/hype window. Detectability blocker was story-step tagging that "lands with the Brock arc"; B3 (in build now) is pinned to "Brock arc (BOSS_TRANSITION)".
  - code: The Brock arc landed game-side (ROADMAP.md lines 120-125 and 455-461: Boulder Badge earned live 2026-07-05) but classify() still has no path to either state, so the actual Brock fight ran as TRAINER_BATTLE (Limited greetings/polls, Restricted channel points, Low-tier effects allowed). The boss-prep ask is allowed only in BOSS_TRANSITION (bot/asks.py:165) so it can never fire. Signals exist: Pewter
  - fix: Tag gym fights the way rival1/Center/Mart are tagged: in_battle + gym map id (or active gym story task) -> GYM_BATTLE; pre-gym story step -> BOSS_TRANSITION.

- [x] **low-hp-danger-scope-inverted** (op-states) — FIXED 2026-07-06 (classifier v3, tests/test_stream_state.py)
  - where: Native-Stream-Operator.md "State Rules" line 95 + "Detectable now" line 124; src/pokeai/ui/stream_state.py:42-51 (pinned by tests/test_stream_state.py:65-67)
  - doc: LOW_HP_DANGER = "Any battle where active Pokemon is at risky HP": No promos/greetings/polls, Safe-only channel points, No effects, "suppress distractions and prevent forced bad actions"; listed as detectable now (party HP reads exist).
  - code: classify() returns the battle state before the HP check (stream_state.py:42-47), so a battle at <30% HP reports WILD_BATTLE/TRAINER_BATTLE (Limited greetings/polls, channel points Yes/Restricted) and never LOW_HP_DANGER; gate_effect's HP<30% rule (bot/gating.py:341-348, fed by bot/directives.py:112-125) covers only the effects column, not the other four. Conversely the HP check fires OUT of battle
  - fix: Move the active_hp_frac check inside the in_battle branch of classify() (return LOW_HP_DANGER there); drop or de-prioritize the overworld firing so map states win outside battle.

- [ ] **no-manual-state-switching** (op-states)
  - where: Native-Stream-Operator.md line 192 (P0 "Stream state: Manual state switching via mod command/dashboard") + mod command list line 439 (!state route_travel / !state between_objectives); bot/commands.py:161-180
  - doc: P0 MVP requires manual stream-state switching via mod command/dashboard, and QUEUE_OPEN / ENDING_SOON "come from the operator panel or bot logic" (lines 133-134).
  - code: The command registry (bot/commands.py:161-179) has no "state" handler and no other override mechanism exists; repo-wide, QUEUE_OPEN and ENDING_SOON appear only in the gating table and its tests (bot/gating.py:121,123), so those two matrix rows (and manual STRICT_MODE) are unreachable. This P0 item is not K1-K8-parked and is absent from ROADMAP G4's still-open list.
  - fix: Add mod-only !state <name> (validated against gating.KNOWN_STATES) that pins/overrides the state the bot feeds to gating, plus a bot-tab toggle later.

- [x] **post-battle-safe-between-objectives-never-emitted** (op-states) — FIXED 2026-07-06 (classifier v3, tests/test_stream_state.py)
  - where: Native-Stream-Operator.md lines 109-110 + "Arrives with the Part 2 build" lines 126-128; src/pokeai/ui/stream_state.py:26-58
  - doc: POST_BATTLE_SAFE ("Best state for promos, polls, clip prompts, viewer rewards, recap") and BETWEEN_OBJECTIVES ("task-queue idle", best state for chat voting) arrive with the Part 2 build.
  - code: Part 2 is long done (ROADMAP G3 [x]; classifier v2 gained the other Part-2 states: POKEMON_CENTER, SHOPPING, wild/trainer split) but classify() cannot emit either state: active_task_id is already an input yet idle (None) falls through to ROUTE_TRAVEL, and no input tracks battle-just-ended. Ask categories keyed exclusively to these states can never trigger live: challenge_effect (bot/asks.py:157-15
  - fix: Emit BETWEEN_OBJECTIVES when active_task_id is None (task queue idle) in the overworld; have stats_tick pass a last-battle-ended-at timestamp and emit POST_BATTLE_SAFE for a short grace window.

- [x] **strict-mode-has-no-live-producer** (op-states) — FIXED 2026-07-06: strict flag + raid detector fed to gating
  - where: Native-Stream-Operator.md lines 112, 133-134, 160 (raid-spam blocking rule), 357 (!strict mod override); bot/commands.py:159,356-364; bot/gating.py:327; bot/directives.py:112-125
  - doc: STRICT_MODE (a bot/operator state "from the operator panel or bot logic") must kill promos/greetings/polls and restrict redemptions/effects; "Raid spam detected -> enable strict mode and pause redemptions"; !strict on is the mod override.
  - code: !strict on only sets CommandRouter.strict_mode (bot/commands.py:359); repo-wide grep finds no reader of that flag outside tests. gating's only STRICT_MODE entry point is facts.raid_spam_detected (bot/gating.py:327), and the sole LiveFacts producer, facts_from_context() (bot/directives.py:112-125), fills HP only, never raid_spam_detected (or ai_stuck_or_recovering). So the STRICT_MODE row is unreac
  - fix: Feed router.strict_mode (and a chat-velocity raid detector) into the state/LiveFacts the live loop passes to gating, forcing STRICT_MODE rules while set.

- [ ] **live-part1-ends-at-starter-no-rival1-no-route1** (part1) *(= FL-6)*
  - where: Walkthrough Part 1 'Oak's Lab' battle + steps 2-3 (docs/Walkthrough-notes-to-fix.md:38-41) vs src/pokeai/agents/firered_part1.py:59-70 and scripts/stream.py:827-831
  - doc: Part 1 includes, after the nickname: 'BATTLE: Rival | starter (lv5) | $80', '2. Gain enough XP to reach lv6', '3. Exit lab → head north to Route 1'.
  - code: run_part1 returns True immediately after the starter is confirmed (firered_part1.py:59-70; its own docstring line 12 says 'the rival battle is the next step'), and stream.py then sets status='done' (stream.py:831) while its own task list still carries rival1 pending (stream.py:65). The rival battle and the lab-exit/Route-1 traversal exist only in standalone scripts unreachable from the live runner
  - fix: Promote trigger_battle + the win/retry loop and the lab-exit/Route-1 leg from the scripts into run_part1 (or into the StoryDriver-dispatched storyline runner), so the live path covers all of Part 1's numbered steps, with the $80 money gate as the win check.

- [ ] **pc-potion-step-skipped** (part1)
  - where: Walkthrough Part 1 'Pallet Town — Home' step 1 (docs/Walkthrough-notes-to-fix.md:29) vs src/pokeai/agents/firered_part1.py:35-46
  - doc: Step 1 of Pallet Town — Home: 'Withdraw Potion from PC (2F bedroom)' before going downstairs to Mom.
  - code: run_part1's first action is taking the bedroom stairs warp (nav.take_warp(warps[0]) at firered_part1.py:37-39) then talking to Mom. No code anywhere interacts with the bedroom PC or withdraws the Potion: a repo-wide search for PC/withdraw logic only hits the module docstring (firered_part1.py:3), which lists 'Potion from the PC' as part of the walkthrough it claims to implement. part1_full_test.py
  - fix: Add a step before the stairs: ow.interact() on the PC tile (it is a facing-A object like NPCs), drive the WITHDRAW ITEM menu (Potion is the only stored item on a fresh game), verify with a bag read (the item/bag readers already exist per ROADMAP G3), then proceed to Mom. Add a bag gate for 1x Potion to part1_full_test stage 2.

- [ ] **player-rival-naming-feature-missing** (part1)
  - where: Walkthrough Part 1 'Game Start' steps 2.1 and 3.1 (docs/Walkthrough-notes-to-fix.md:24,26) vs src/pokeai/agents/firered_intro.py:154-167 and scripts/stream.py:805
  - doc: [[Feature]] on player naming: 'Allow operator via dashboard/viewers via poll to enter a name. Default to selecting Ash.' [[Feature]] on rival naming: same, 'Default to selecting Gary'. Native-Stream-Operator.md:856-858 confirms the buildable half: 'Naming flow: operator panel text input (defaults Ash/Gary per the walkthrough feature notes) + viewer poll when live; the winner lands in the intro key
  - code: run_intro hardcodes intro.type_name("CLAUDE") (firered_intro.py:155) and intro.type_name("GROK") (firered_intro.py:164) with no parameters, no operator-panel input path, and no poll hook; stream.py:805 calls run_intro(intro, Hooks(c)) with no name source. No naming-flow code exists in bot/ or scripts/stream.py (grep for naming/name-entry: only nickname_next_catch, which is for catches). The viewer
  - fix: Thread name parameters through run_intro(intro, hooks, player_name=..., rival_name=...); default them to the doc's Ash/Gary (or pick the ASH preset via the preset menu, which brain_agents._handle_naming already proves readable); add an operator-panel text input in stream.py that fills these before a fresh run; extend GRID with the lowercase keyboard page (or clamp/upper-case + length-7 validate su

- [ ] **starter-nickname-feature-missing** (part1)
  - where: Walkthrough Part 1 'Oak's Lab' step 1.1 (docs/Walkthrough-notes-to-fix.md:36-37) vs src/pokeai/agents/firered_part1.py:61 and src/pokeai/skills/overworld.py:214
  - doc: 'Nickname starter' with [[Feature]]: 'Allow operator via dashboard/viewers via poll to enter a name. Default to selecting Gary' (the doc's stated default for the nickname).
  - code: The nickname is hardcoded: run_part1 calls ow.pick_starter(nickname="CLAW") (firered_part1.py:61) and pick_starter's signature default is also "CLAW" (overworld.py:214); it force-uppercases whatever it gets (overworld.py:253). There is no operator/dashboard input and no poll hook for the starter nickname anywhere (bot/effects.py only has nickname_next_catch for wild catches). part1_full_test.py:17
  - fix: Accept the nickname from the same operator-input/poll seam as the intro names, defaulting per the doc; make part1_full_test read the expected nickname from that source instead of the literal 'CLAW'. (Flag to the owner that the doc's 'Gary' default for the starter nickname reads like a copy-paste from the rival step and should be corrected in the doc if unintended.)

- [ ] **route22-feature-quest-queue-dead-end** (part2)
  - where: Part 2 / Route 22 [[Feature]] tag (Walkthrough-notes-to-fix.md:67) vs scripts/stream.py:86,294-297,734-735 and stream/operator.html:59-106
  - doc: [[Feature]]: Route 22 is 'an optional quest that can be added via quest queue in the operator panel but should not be defaulted to go'.
  - code: Neither enqueue path can actually queue Route 22. (1) Operator panel: the Quest queue UI exists (operator.html:59-63, addQuest() line 96) but stream.py:86 has QUEST_CATALOG = [] ('EMPTY until Part 1+ quests are built'), so the dropdown shows 'No quests available yet' (operator.html:106) and queue_add() silently returns for any id (stream.py:295-297). (2) Bot: 'enqueue_quest' is whitelisted at subm
  - fix: Add a route22 entry to QUEST_CATALOG (name + task children), and make serve_directives() handle d == 'enqueue_quest' by mapping args['quest'] to a catalog id and calling c.queue_add(), finishing the directive 'executed'.

- [ ] **bug-catcher-rick-doug-never-verified** (part3)
  - where: Part 3 / Viridian Forest steps 3-4 (Walkthrough-notes-to-fix.md:87-88) vs scripts/forest_run.py:71-99, scripts/forest_grind.py:176-260, docs/ROADMAP.md:116-119 and 455-458
  - doc: Step 3: Battle Bug Catcher Rick (east side). Step 4: Pass Bug Catcher Doug. (Sammy, step 7, was beaten live per ROADMAP:113.)
  - code: forest_run's warp-directed pathing dodged Rick's and Doug's sight lines (ROADMAP G7 caveat, lines 116-119, which says 'The G8 grind sweep clears the remaining trainers'). But forest_grind.py exits purely on lead level (TARGET_LEVEL=11, lines 35 and 176-181), counts trainer wins only generically (wins['trainer'], line 201), and has no per-trainer identity or completion check; the G8 live record (RO
  - fix: Route the grind sweep through the two known sight-line columns explicitly, or read the per-trainer beaten flags from RAM (trainer flag block) and require both set before forest_grind declares PASS.

- [x] **forest-item-steps-missing** (part3) — FIXED 2026-07-06: Pickup skill built (wiring into forest route = remaining)
  - where: Part 3 / Viridian Forest steps 1, 2, 4, 6 (Walkthrough-notes-to-fix.md:85-90) vs C:/Users/Sagac/OneDrive/KameronOS/PROJECTS/Pokemon-Red-AI/pokeai/scripts/forest_run.py:71-99 and scripts/forest_grind.py:254-260
  - doc: The forest trail collects four ground items: Poke Ball (NW tall grass), Potion (SE grass patch), Antidote (near Bug Catcher Doug), Potion (dead-end SE path).
  - code: forest_run.py deliberately exits every warp-connected map, including the forest, via the northmost warp (warp_navigate_north, lines 71-99; docstring says greedy flooding dead-ends so warps are used) and never routes to any item ball. forest_grind.py's serpentine sweep (lines 254-260) only walks rows for encounters/sight lines. No ground-item pickup routine exists anywhere in src (grep for pickup/i
  - fix: Add a forest item-ball waypoint pass: locate item objects via nav.vision.object_tiles(), Overworld.interact each, verify with read_bag_pocket deltas (same pattern part4_run uses for the fossil), either inside forest_run's route or as a forest_grind sub-pass.

- [ ] **pewter-mart-discovery-known-broken** (part3)
  - where: Part 3 / Pewter potion prep for Brock: scripts/brock_run.py:90-124 vs docs/ROADMAP.md:466-467 (2026-07-05 ~18:35 wart) and src/pokeai/skills/services.py:36-41
  - doc: ROADMAP section 6 records the live brock_run mart discovery hit a HOUSE (sold/rebought balls) and 'needs a shop-menu signature probe before reuse'; services.py:40 has since recorded the warp-table-verified Pewter mart row (map (6,3), door (28,18), verified 2026-07-06).
  - code: brock_run.py still ships the identical known-broken heuristic: it iterates warps skipping only (6,0)/(6,2)/(6,5) (line 95) and accepts any interior matching 'any(t[0] <= 3 for t in npcs) and g["w"] <= 16' (line 109) as the mart, then blind-drives buy_at_mart there. It never consults the now-verified MARTS[(3,2)] row; it only overwrites MARTS[PEWTER] with its own guess (line 113). A re-run (fresh-s
  - fix: In brock_run, use MARTS.get(PEWTER) when present and skip discovery entirely; when discovering, accept only dest (6,3) or gate the purchase on a shop-menu signature (money-delta probe before committing qty).

- [x] **fossil-grab-blind-and-one-shot** (part4) — FIXED 2026-07-06: ChoicePoint + Pickup built (Miguel wiring = remaining)
  - where: Walkthrough Part 4, Mt. Moon step 6 (docs/Walkthrough-notes-to-fix.md:131-134) vs scripts/part4_run.py:99-119 and 372-374
  - doc: Fossil is claimed after beating Super Nerd Miguel (B2F Outer); choose ONE fossil (Dome=Kabuto, Helix=Omanyte).
  - code: try_fossil fires on the FIRST trainer:win anywhere in Mt. Moon (any Rocket/Youngster, not Miguel), sweeps the 3 nearest interactables within 6 tiles, and records ANY item-bag increase as the fossil - no fossil item-id verification, no Miguel/B2F gating. Once it returns any item id, `fossil is None` is false forever, so an early stray pickup permanently suppresses the real fossil attempt. ROADMAP s
  - fix: Gate the pickup sweep on the Miguel battle or on reaching the B2F fossil objects; verify the bag delta is specifically the Dome/Helix fossil item id and retry until one of the two is in the bag; feed the choice from the poll/default-random seam.

- [x] **fossil-poll-not-implemented** (part4) — FIXED 2026-07-06: ChoicePoint seam built (stream.py/part4 wiring = remaining)
  - where: Walkthrough Part 4, Mt. Moon step 6 [[Feature]] (docs/Walkthrough-notes-to-fix.md:132) vs scripts/part4_run.py:99-119,372-374; bot/gating.py:38-41,351; bot/commands.py; bot/effects.py:64-65; scripts/stream.py (no poll references)
  - doc: "Allow viewers choose in a timed poll. If no responses then default to random." for the Dome vs Helix fossil choice after Super Nerd Miguel.
  - code: No poll machinery exists anywhere to host it: bot/ has only a POLLS permission-verdict table in gating.py (may polls run in a state), no poll manager, no !poll command, no fossil/choice effect in the B2 catalog, and stream.py has zero poll/vote/fossil code. part4_run's try_fossil neither consults viewers nor makes a random Dome/Helix choice - it interacts with the 3 nearest objects and keeps whate
  - fix: Add a game-side choice-point seam (mirror the B1 naming flow: operator field + optional viewer vote, timed window, default random between DOME/HELIX on zero responses) exposed via stream.py's API; have the Part 4 runner block on it at the Miguel fossil moment. Keep only the Twitch-native Polls API call behind K6.

- [x] **mt-moon-items-never-picked-up** (part4) — FIXED 2026-07-06: Pickup skill built (per-floor wiring = remaining)
  - where: Walkthrough Part 4, Mt. Moon steps 1-5 (docs/Walkthrough-notes-to-fix.md:125-134) vs scripts/part4_run.py stage_moon (212-494, esp. comment 405-408) and src/pokeai/skills/ (battle, catch, journey, navigate_to, overworld, services only)
  - doc: Grab TM09 Bullet Seed, Parlyz Heal (1F), Star Piece (B2F S), Potion + Rare Candy + Escape Rope (1F), TM46 Thief + hidden Ether via inspecting the large rock (B2F NE), Moon Stone (1F NW), Antidote (B2F Outer).
  - code: No item-ball pickup skill exists anywhere in src/pokeai/skills; stage_moon explores by warps and fights only, and the per-iteration object sweep was deliberately removed ('NO per-iteration try_fossil ... The fossil is a later pass; only a trainer win warrants a pickup sweep'). None of the 10 listed items are ever targeted; ROADMAP section 6 records the owner hand-collecting TM46/TM09/Rare Candy/St
  - fix: Build an item-ball pickup skill (item balls appear in vision.object_tiles: walk_to an adjacent tile, interact, verify bag delta) and drive it from the doc's per-floor item lists before taking the exit; add a scripted inspect for the hidden Ether rock.

- [ ] **storyline-strategy-cannot-reach-part4** (part4)
  - where: Walkthrough Parts 2-4 as the built story (STOP at docs/Walkthrough-notes-to-fix.md:142) vs scripts/stream.py:818-827 and scripts/part4_run.py:14
  - doc: The walkthrough through Part 4 is what the system is built to play, hosted by the stream system's 'storyline' strategy (DEFAULT_STRATEGY = storyline, stream.py:81).
  - code: The live storyline branch hardwires run_part1 whenever context has intro_done, regardless of actual story progress; part4_run.py is a standalone acceptance script whose own docstring requires 'stream.py STOPPED'. Known-broken live: ROADMAP section 6 (2026-07-06 ~11:50) records that started from slot 4 (Cerulean) the storyline strategy walked Part 1's bedroom script inside Cerulean; the G10 StoryDr
  - fix: Wire the StoryDriver cursor (facts + slot marks -> current part) into stream.py's storyline runner and dispatch the matching part runner (part1 intro ... part4 journey) instead of unconditional run_part1.

### MINOR

- [x] **direct-explanation-cooldown-not-enforced** (op-asks) — FIXED 2026-07-06: direct_explanation budgets enforced
  - where: Native-Stream-Operator.md 'Cooldown rules' row 'Direct explanation | 5 min | 10 min | Unlimited when user asks'; bot/asks.py:185-186, bot/commands.py:202-213
  - doc: Direct explanation asks have a 5-minute global cooldown and 10-minute per-type cooldown (unlimited count when the user asks), and B3 item 5 requires the per-type cooldown budgets 'enforced exactly as tabled'.
  - code: asks.py:185-186 delegates this table row to '!effects' in bot/commands.py, but CommandRouter has no cooldown logic at all: dispatch (commands.py:202-213) gates only on mod-only and the kill switch; the only 'cooldown' string in the file formats an EffectQueue refusal (commands.py:112-113). Anyone can invoke !effects back to back with no 5/10-minute budget, rate-limited only by the chat sender queu
  - fix: Add a small clock-based cooldown to CommandRouter (global + per-command), seeded with 300s/600s for !effects; the commands DB table already has global_cooldown_seconds/user_cooldown_seconds columns (store.py:116-117) that nothing reads.

- [x] **lift-window-pending-in-memory-only** (op-asks) — FIXED 2026-07-06: pending windows persisted, rebuilt on construct
  - where: Native-Stream-Operator.md 'Minimal implementation logic' ('After 3 minutes: count redemptions ... chat lift') + core loop 'Track Interaction Result'; bot/asks.py:634, 722, 732-747; bot/live.py:278
  - doc: Every sent ask gets a tracked result after the 3-minute window (interaction_prompt_results row with redemptions/chat lift).
  - code: Pending lift windows live only in self._pending (asks.py:634, 722); a bot restart or crash inside the 3-minute window permanently drops the result row for that prompt, even though CooldownLedger deliberately re-seeds cooldowns from the store for exactly this restart case (asks.py:245-247). Additionally, resolution counts everything from sent_at to 'now' with no upper bound (asks.py:738-744), so wh
  - fix: On engine construction, re-queue prompts younger than 180s that lack a results row (a store query joining interaction_prompts to missing interaction_prompt_results); bound the count queries with 'created_at < sent_at + window_seconds' (store already timestamps everything).

- [x] **persona-selection-static** (op-asks) — FIXED 2026-07-06: personas rotate through the doc-table tuple
  - where: Native-Stream-Operator.md 'Persona table' (8 personas) + B3 build item 5 ('Personas ... enforced exactly as tabled'); bot/asks.py:374, asks.py:696
  - doc: Eight personas (AI Bot, Professor Oak, Rival, Team Rocket, Narrator, Coach, Gremlin, Announcer) give the asks varied voices matched to the moment.
  - code: AskEngine.tick calls build_seed without a persona (asks.py:696), and build_seed defaults to ask.personas[0] (asks.py:374), so every ask of a type always records the same persona: gremlin, professor_oak, and rival are declared in ASK_TYPES tuples but unreachable (only ever at index >= 1). The template banks also do not match the recorded persona: e.g. a boss_prep ask always records tone='coach' whi
  - fix: Rotate or randomize persona choice across ask.personas in tick (seeded per prompt), and either tag templates with their persona or make banks persona-keyed so the recorded tone matches the sent text.

- [x] **tone-match-score-factor-missing** (op-asks) — FIXED 2026-07-06: tone-match added to candidate scoring
  - where: Native-Stream-Operator.md 'Candidate scoring' table (Tone match: 'Matches selected persona'); bot/asks.py:566-584 (score_candidate)
  - doc: Candidate scoring rewards eight factors including 'Tone match - matches selected persona'.
  - code: score_candidate implements context match, freshness, brevity, and clarity only. Non-desperation/compliance are covered by the guardrail hard filter and timing by state gating (defensible relocations), but nothing anywhere compares a candidate to the selected persona: an HF candidate in a completely wrong voice scores identically to an on-persona one.
  - fix: Add a persona-keyword score term (per-persona vocabulary lists, or penalize candidates that name a different persona's character) to score_candidate.

- [x] **trigger-table-rows-unimplemented** (op-asks) — FIXED 2026-07-06: catch->lore + clutch->clip rows implemented
  - where: Native-Stream-Operator.md 'Request trigger table' (12 rows); bot/asks.py:300-358 (OpportunityDetector.detect)
  - doc: Twelve tabled triggers, including 'AI catches Pokemon -> name/lore interaction', 'AI wins clutch battle -> clip/chaos follow-up', 'After Gym Badge -> celebration interaction', 'Stream ending soon -> next-stream setup', and 'Raid received -> safe intro interaction'.
  - code: The detector implements 6 of 12 rows: before_gym (BOSS_TRANSITION), after_loss (dead per the recovery defect), low money, low balls/heal items, new route, chat slow; 'viewer asks how to interact' is reactive via !effects. Catch, clutch-win, post-badge celebration, ending-soon, and raid triggers have no code path even though the inputs for at least post-badge exist (facts.badges, asks.py:206, mirro
  - fix: Add a badge-delta trigger (celebration) the same way _note_map detects map changes; arm catch/raid triggers from the events the bot already sees (EventSub raid, directive completion for catch_next_encounter); ending-soon from the operator panel state.

- [ ] **b1-chat-spike-detector-partial** (op-b0b1)
  - where: Native-Stream-Operator.md P1 'Chat spike detection' + Flow E (spike = clip signal) + B1 item 5 vs bot/asks.py:638 (note_chat_message) as the only velocity code
  - doc: A chat-spike detector detects unusual message velocity and feeds clip markers (Flow E: 'chat velocity spike' -> clip_marker, score +2) and raid-spam strict mode.
  - code: The only velocity tracking is asks.py's note_chat_message, consumed solely as a B3 slow-chat/ask-trigger input. Nothing detects spikes, nothing emits a clip marker or strict-mode escalation from velocity. Partial build repurposed for a different feature.
  - fix: Add a rolling-window spike detector (baseline vs current msgs/min) that emits a clip marker record and can set the raid_spam/strict signal.

- [ ] **b1-qa-queue-missing** (op-b0b1)
  - where: Native-Stream-Operator.md B1 item 5 + P1 'Q&A queue: Viewers ask, mods approve, bot surfaces' vs bot/ (absent)
  - doc: B1 delivers a Q&A queue (viewer submits, mod approves, bot surfaces).
  - code: No Q&A code, command, or table exists anywhere in bot/ (grep: the only 'queue' hits are the effect queue and sender queue). Not gated on any K prerequisite.
  - fix: !ask <question> -> qa_queue table (PENDING/APPROVED/ANSWERED), mod command or operator-tab approve, bot surfaces approved questions at safe states.

- [x] **command-cooldowns-dead-config** (op-b0b1) — FIXED 2026-07-06: dispatch enforces global + per-user cooldowns
  - where: Native-Stream-Operator.md commands schema (global/user cooldown columns) vs bot/config.py:100-101, bot/commands.py (no throttling), bot/store.py:499-568 (no production callers)
  - doc: Commands carry global (30s) and per-user (60s) cooldowns; invocations are recorded.
  - code: config.command_global_cooldown_seconds / command_user_cooldown_seconds are read by nothing; CommandRouter enforces no per-command or per-user cooldown (only the sender's global 1.2s pace), and store.upsert_command / record_command_invocation have zero callers outside tests. A viewer can spam !party into repeated /api/context fetches and chat replies.
  - fix: Wire the two config values into CommandRouter (last-invocation maps keyed by command and by user:command) and record invocations via the store.

- [ ] **moderation-ladder-below-doc-matrix** (op-b0b1)
  - where: Native-Stream-Operator.md '## Moderation policy' rule matrix vs bot/moderation.py:46-70 (acknowledged in docstring lines 14-19)
  - doc: Hate/slurs: 'Delete + timeout/ban' first, then Ban; unknown link severe action 'Ban if malicious'; timeout tiers 60s then 10m; caps escalates to strict mode; Flow B scores also include raid-spam velocity and suspicious-user events.
  - code: The shared 4-rung ladder tops out at FLAG_MOD - Action.BAN is never emitted by scoring (moderation.py:46 comment), every TIMEOUT is a flat 60s (moderation.py:70), caps never triggers strict mode, and there is no raid-spam-velocity or suspicious-user rule at all. Deliberate, documented B0 simplification, but the doc's severe actions are unreachable by the bot (P0's five rule families ARE covered).
  - fix: Moderation v2: per-rule ladders with duration tiers and terminal BAN for blocked_term repeats; velocity rule feeding strict mode.

- [x] **missing-rival-catch-mistakes-commands** (op-commands) — FIXED 2026-07-06: !rival/!catch/!mistakes from context
  - where: Native-Stream-Operator.md 'Pokemon-specific commands' lines 448-451 vs bot/commands.py:161-179 (handler table)
  - doc: The Pokemon-specific command set includes '!rival  Rival fight status', '!catch  Catching rules', and '!mistakes  Recent AI mistakes'.
  - code: The router's _handlers dict implements only rules/lurk/uptime/discord/youtube/clip/party/badges/route/ai/next/effects/redeem/questlist/quest/bot/strict. !rival, !catch, and !mistakes have no handler anywhere in bot/ (grep confirms), so the bot is silent when viewers use them. They are not K1-K8-parked, and the doc's B0-B5 implementation plan never schedules them, so they are spec'd but unbuilt and
  - fix: !catch can be a static text handler (the catching rules). !rival needs a story-step/rival field in /api/context (StoryDriver knows the next rival fight) plus a formatter. !mistakes needs a mistakes feed (e.g. recent blackout/failed-catch events already in the context 'events' list) or should be explicitly rescheduled/de-scoped in the doc.

- [x] **no-loyalty-ranking-on-effect-requests** (op-commands) — FIXED 2026-07-06: loyalty_priority() feeds effect priority
  - where: Native-Stream-Operator.md line 374 ('Interactions are ranked by user's loyalty rating') vs bot/commands.py:319-326 + bot/effects.py:176
  - doc: Viewer interactions entering the validated queue are ranked by the user's loyalty rating (follower, subscriber, tipper, donator, manual additions).
  - code: _submit_effect submits every !redeem/!quest with the default priority (effects.py:176, priority=100 for all callers) and records the redeemer only as a user_input string (commands.py:323-325). No loyalty lookup or ranking exists anywhere in bot/. (The channel-points funding side is K6-parked, but priority ranking is pure bot-side code and is absent.)
  - fix: Derive a priority from the viewer row (sub/vip/mod flags already in the viewers schema and chat badges) in _submit_effect, and have EffectQueue.poll_next order APPROVED entries by priority.

- [x] **catch-decision-blocker-cleared-state-missing** (op-states) — FIXED 2026-07-06 (classifier v3, tests/test_stream_state.py)
  - where: Native-Stream-Operator.md lines 100 + 129-131 (CATCH_DECISION blocked on the "catch system"); src/pokeai/ui/stream_state.py:26-58
  - doc: CATCH_DECISION (chat votes catch-or-skip, nickname, strategy; polls Yes vs WILD_BATTLE's Limited) was blocked only on the catch system.
  - code: The catch system is done (ROADMAP G5 [x] 2026-07-05: weaken-first catch, NeedsArbiter, catch_next_encounter arming exists in B2) but classify() has no input or branch for CATCH_DECISION, so catch moments still gate under WILD_BATTLE.
  - fix: Expose the agent's catch intent (drive/task already surfaced in stream.py ctx) to stats_tick and emit CATCH_DECISION while a catch attempt is being decided/armed.

- [x] **rival-battle-keyed-to-rival1-only** (op-states) — FIXED 2026-07-06 (classifier v3, tests/test_stream_state.py)
  - where: Native-Stream-Operator.md lines 93 + 122-123 (RIVAL_BATTLE detectable via "battle detect + story step"); src/pokeai/ui/stream_state.py:43; Walkthrough-notes-to-fix.md lines 66-72 (Part 2 Route 22 optional-quest rival battle, [[Feature]] tagged, within [[STOP]] scope)
  - doc: RIVAL_BATTLE (No greetings/polls, Restricted channel points, Safe-only effects) applies to rival fights, detected by battle detect + story step; Parts 1-4 contain a second rival battle in the required Route 22 optional quest.
  - code: classify() tags RIVAL_BATTLE only when active_task_id == "rival1" (a Part 1 literal). A Route 22 rival fight (quest id "route22", the enqueue_quest(route22) effect in bot/effects.py:112-117) would classify as TRAINER_BATTLE, which is looser than the RIVAL_BATTLE row (Limited vs No greetings/polls, Low vs Safe-only effects). Currently latent because enqueue_quest is "unsupported_v1", but the quest 
  - fix: Match a rival task-id set/prefix (e.g. ids starting "rival" or a story-step is_rival tag) instead of the single literal.

- [ ] **route1-battle-for-xp-flees-by-default** (part2)
  - where: Part 2 / Route 1 step 2 (Walkthrough-notes-to-fix.md:49) vs scripts/route1_to_viridian.py:6,60-80,129-132
  - doc: Battle wild Pokemon for XP (can't catch yet, no Poke Balls) - don't worry about reaching any level or XP amount yet.
  - code: The Route 1 script's policy is the opposite: flee_or_fight() (route1_to_viridian.py:60-80) attempts to FLEE up to 4 times and only fights if fleeing fails; the docstring states 'a wild battle interrupts the walk -> FLEE (fight if fleeing fails)' (line 6). No XP/level tracking exists in the script (grep for grind/xp/level: no matches), and the ROADMAP G2 checklist item 'Grind skill' remains uncheck
  - fix: On the Route 1 northbound leg, use a fight-first policy (Battle.fight / fight_smart with retreat-on-low-HP), or a small bounded grind loop, instead of flee-first.

- [ ] **route1-free-potion-best-effort-unverified** (part2)
  - where: Part 2 / Route 1 step 1 (Walkthrough-notes-to-fix.md:48) vs scripts/route1_to_viridian.py:135-158,183-200
  - doc: Talk to man near signpost (south side) -> free Potion.
  - code: The step is an opportunistic side effect, not a gated step: the script talks only to NPCs within Manhattan distance 4 of wherever its BFS-north path happens to go (route1_to_viridian.py:137-141) and merely LOGS bag deltas (lines 148-157); the run returns success purely on reaching Viridian (lines 188-198) with no assertion that the Potion man was reached or that ITEM_POTION entered the bag. The Po
  - fix: Record the Potion man's tile from the probe run and target it explicitly on the Route 1 leg, then gate on a bag delta for item id 13 (POTION) before crossing into Viridian.

- [ ] **route2-west-step-outside-part2-chain** (part2)
  - where: Part 2 / Route 2 (West) step 1 (Walkthrough-notes-to-fix.md:77-78) vs scripts/part2_full_test.py:366-371 and scripts/forest_run.py:1-13
  - doc: Part 2's final section: 'Route 2 (West): 1. Head north through gate into Viridian Forest'.
  - code: part2_full_test.py stage H saves slot 6 = 'Part 2 COMPLETE' (lines 366-367) immediately after the Teachy TV, still standing in Viridian City; the gate crossing onto Route 2 (3,20) and into the forest exists only in the Part 3/G7 script forest_run.py, which starts from slot 9 (the G5 field_run output), not from the Part 2 completion slot. So the Part 2 chain as coded ends one numbered step short of
  - fix: Either extend stage H to push north through the Route 2 gate (map id gate on (3,20) or the gate interior) before saving 'Part 2 COMPLETE', or move the doc's Route 2 (West) line into Part 3 so the boundaries agree.

- [ ] **viridian-academy-step-missing** (part2)
  - where: Part 2 / Viridian City step 3 (Walkthrough-notes-to-fix.md:54) vs scripts/part2_full_test.py:183-217 and src/pokeai/skills/services.py:18
  - doc: Visit Pokemon Academy (center building) - status ailment tutorial (numbered step 3 of the Viridian City section).
  - code: No code performs this step anywhere. part2_full_test.py jumps from stage A (heal, line 183) straight to stage B (Mart parcel, line 194). services.py:18 identifies the building (door (25,18) -> map (5,2) 'the Trainer School') but only discovery probes (scripts/probes/center_mart_probe.py, viridian_buildings.py) ever entered it; the Part 2 chain never visits it, yet stage H saves slot 6 = 'Part 2 CO
  - fix: Add a stage between A and B: route to door (25,18), warp into (5,2), ride the tutor dialogue with advance_dialogue + wait_control, then leave_building. Or, if intentionally skipped, annotate the doc step so the audit/StoryDriver treats it as optional.

- [ ] **route3-wilds-fled-not-fought** (part4)
  - where: Walkthrough Part 4, Route 3 step 2 (docs/Walkthrough-notes-to-fix.md:117-118) vs scripts/part4_run.py:140 + src/pokeai/skills/journey.py:114-152 + src/pokeai/agents/field_brain.py:162-181
  - doc: Route 3: '2. Battle wild Pokémon for XP' (alongside '1. Battle trainers heading east').
  - code: WildPolicy's documented default is 'Flee wilds by default' - flee_or_fight RUNs from every wild encounter and only fights if fleeing fails 4 times; part4_run constructs WildPolicy with no should_catch/fight override, so Route 3 (and all Part 4) wild encounters are fled and yield no XP. Trainers are fought (fight_smart), matching step 1, but step 2 is inverted.
  - fix: Give WildPolicy a fight-for-XP mode (fight when healthy/level-advantaged, flee otherwise) and enable it for the Route 3 legs or until a pre-Mt.Moon level target is met.

- [ ] **route4-east-move-tutors-skipped** (part4)
  - where: Walkthrough Part 4, Route 4 (East) step 1 (docs/Walkthrough-notes-to-fix.md:136-139) vs scripts/part4_run.py stages_east (497-519)
  - doc: Two Move Tutors (Black Belts) on the west hill: left teaches Mega Punch, right teaches Mega Kick (both one-time), before heading east downhill to Cerulean.
  - code: stages_east only alternates EAST/SOUTH cross_edge legs until a new city map is hit; it never locates or talks to the Black Belts, so both one-time tutors are permanently skipped for the run. No other code references Mega Punch/Mega Kick or these NPCs.
  - fix: Add a scripted stop (or optional-quest queue entry) on Route 4 east: walk_to each Black Belt, interact, accept the tutor flow for a chosen party mon before the Cerulean leg.

### POLISH

- [x] **boss-prep-global-cooldown-invented** (op-asks) — FIXED 2026-07-06: boss_prep budget aligned to doc (once per boss)
  - where: Native-Stream-Operator.md 'Cooldown rules' row 'Boss prep request | Per boss only | Per boss only | 1 per boss'; bot/asks.py:162-167
  - doc: Boss prep has no time-based budget: both cooldown columns and the cap are 'per boss only / 1 per boss'.
  - code: The once-per-boss cap is enforced (boss_key set, asks.py:276-277, 284-285, seeded from reward_key on restart at asks.py:265-266), but the row also carries global_cooldown=600.0 (asks.py:164), a 10-minute engine-wide gap after a boss ask that appears nowhere in the table. Conservative direction, but it deviates from 'budgets enforced exactly as tabled'.
  - fix: Either set global_cooldown=0.0 for boss_prep or note the deliberate 10-minute spacing in the doc's cooldown table.

- [x] **no-destructive-action-filter** (op-asks) — FIXED 2026-07-06: DESTRUCTIVE_PHRASES hard reject
  - where: Native-Stream-Operator.md 'Safety/style guardrails' row 'No irreversible effects - never promote destructive game actions'; bot/asks.py:538-557 (guardrail_refusal)
  - doc: Generated asks must never promote destructive game actions (release Pokemon, delete save, etc.).
  - code: guardrail_refusal checks length, blocked/guilt/lurker phrases, an interaction-handle requirement, and shouting; there is no check for destructive-action language, so an HF-generated candidate like 'redeem an effect to release a Pokemon' would pass every filter. Templates are safe, but the HF path (asks.py:497-530) is unfiltered for this rule.
  - fix: Add a destructive-phrase list ('release', 'delete save', 'waste', 'corrupt', ...) to guardrail_refusal as a hard reject, mirroring the doc's Banned tier vocabulary.

- [ ] **stale-pause-queue-flush** (op-b0b1)
  - where: Native-Stream-Operator.md kill-switch behavior vs bot/sender.py:113-120 + bot/commands.py:339-343
  - doc: Pause stops the bot; resume brings it back (watchdog asserts obedience).
  - code: Pausing does not clear or annotate the sender queue: the 'Bot paused.' acknowledgment enqueued right after killswitch.pause() is itself stuck (a mod gets no confirmation), and any greetings/warnings queued during the pause flush stale and out-of-order the moment !bot resume lands.
  - fix: Send the pause ack before pausing the sender (or exempt mod-command replies), and drop or expire queued non-mod messages older than N seconds on resume.

- [ ] **effect-cell-readings-diverge-from-doc** (op-states)
  - where: Native-Stream-Operator.md lines 111 (QUEUE_OPEN Game Effects "Yes") and 112 (STRICT_MODE Game Effects "Restricted"); bot/gating.py:140-153 (_EFFECT_TIER_BY_CELL)
  - doc: QUEUE_OPEN allows game effects "Yes" (approved redemptions and queued viewer challenges, which per the tier table and FireRed examples includes High-risk effects); STRICT_MODE allows "Restricted" effects. gating.py's own docstring (lines 3-7) declares the doc matrix the single source of truth, mirrored cell for cell.
  - code: _EFFECT_TIER_BY_CELL deliberately reads "Yes" as a MEDIUM cap (High-tier effects are never viewer-triggerable in any state until B4) and "Restricted" as a SAFE cap (bot/gating.py:145-153, pinned by tests/bot/test_gating.py:122-128). Safe-side and commented, but the doc cells were never annotated, so doc and code disagree on two cells despite the declared cell-for-cell discipline.
  - fix: Annotate the two doc cells (e.g. "Yes (Medium cap until B4)" / "Restricted = Safe-only") or lift the code caps when B4 lands, so the declared mirror holds.

- [ ] **lv6-step-has-no-gate** (part1)
  - where: Walkthrough Part 1 'Oak's Lab' step 2 (docs/Walkthrough-notes-to-fix.md:39) vs scripts/part1_full_test.py:199,222-234
  - doc: '2. Gain enough XP to reach lv6' after the rival battle.
  - code: No code grinds toward or verifies level 6. part1_full_test verifies the win solely by the +$80 money delta (part1_full_test.py:199,222-224) and prints the final level in the banner unchecked (part1_full_test.py:233). In practice the rival win's XP delivers lv6 (ROADMAP.md:219 records 'CLAW lv6' at slot 2), so the step occurs naturally, but the spec step has no corresponding action or acceptance ga
  - fix: Add 'battle.my_stats()[0] >= 6' to stage 5's gates in part1_full_test (cheap regression insurance), or an explicit grind-if-below-6 step before saving slot 2.

- [ ] **part1-docstring-denies-nickname-prompt** (part1)
  - where: Walkthrough Part 1 'Oak's Lab' step 'Nickname starter' (docs/Walkthrough-notes-to-fix.md:36) vs src/pokeai/agents/firered_part1.py:6-8
  - doc: Part 1 includes a 'Nickname starter' step, and the code actually performs it (overworld.py:250-255 answers FireRed's nickname prompt; verified by scripts/probes/starter_nickname.py).
  - code: The module docstring states the opposite of both the spec and the module's own behavior: 'FireRed does NOT prompt to nickname the starter at selection, so there's no name step here; renaming would need the Name Rater much later' (firered_part1.py:6-8), three lines above run_part1 passing nickname="CLAW" into pick_starter (firered_part1.py:61). Misleading for anyone auditing or extending the naming
  - fix: Rewrite the stale docstring paragraph: FireRed does prompt, pick_starter answers YES and types the nickname via the intro keyboard.

- [ ] **part2-deliver-docstring-claims-unperformed-verification** (part2)
  - where: Part 2 / Pallet Town step 1 (Walkthrough-notes-to-fix.md:58) vs scripts/part2_deliver.py:5,236-248
  - doc: Deliver Oak's Parcel -> Oak gives Pokedex + 5 Poke Balls each; the script's own docstring says 'Pokedex + 5 Poke Balls. Verified via event-flag delta' (part2_deliver.py:5).
  - code: part2_deliver.py never verifies the Pokedex or the 5 balls: ev0/ev1 flag counts are only printed (line 237), FLAG_SYS_POKEDEX_GET is never checked, ball_count is never read; success (return 0, save slot 6) is gated solely on the parcel leaving the bag (lines 238-246). The superseding part2_full_test.py stage D does gate both (lines 285-288), but this retained non-legacy script's claim contradicts 
  - fix: Either move part2_deliver.py to scripts/legacy/ now that part2_full_test.py is the acceptance, or add the 0x829 flag + ball_count >= 5 gates and fix the docstring.

- [ ] **town-map-teachy-tv-identity-not-asserted** (part2)
  - where: Part 2 / Viridian step 4 + Back-to-Viridian step 3 (Walkthrough-notes-to-fix.md:55,63) vs scripts/part2_full_test.py:311-317,350-355
  - doc: ITEM: Town Map (from Daisy) and ITEM: Teachy TV (from the old man) - specific named items.
  - code: Stages E and G accept ANY new key-item id as success: 'new = {k: v for k, v in ki1.items() if k not in ki0}' then take next(iter(new)) as the Town Map (lines 312-314) / Teachy TV (lines 351-354). The real ids are already known from the live run (Town Map = 361, Teachy TV = 366, ROADMAP.md:66-67) but are not pinned, so a rerun would 'PASS' if any NPC handed over any other key item.
  - fix: Assert the discovered ids: stage E gates on key item 361, stage G on 366 (keep the discovery print as a fallback diagnostic).

- [ ] **tm39-reward-unverified** (part3)
  - where: Part 3 / Pewter Gym reward line (Walkthrough-notes-to-fix.md:106) vs scripts/brock_run.py:197-209 and src/pokeai/skills/battle.py:250-257, 292-295
  - doc: Beating Brock also grants TM39 Rock Tomb (listed alongside the Boulder Badge as the section's HM/TM reward).
  - code: brock_run's PASS gate checks only FLAG_BADGE01 and logs badge_count/money (lines 197-202); the post-battle dialogue that hands over TM39 is ridden out with generic B/A mashing (battle.ride_out_end), and no code reads the TM/HM bag pocket to confirm receipt, so a swallowed TM39 would pass silently. Every other Part 3 reward in this chain is RAM-verified; this one is not.
  - fix: After the badge flag sets, read the TM/HM pocket via reader.read_bag_pocket and log/assert a +1 TM39 delta alongside the badge check.

### Rejected by verification (for the record)

- no-per-user-cooldown: The code facts are accurate (cooldowns are per-effect global only: bot/effects.py:249-251, docstring 138-141; commands.py:319-326 passes no viewer_id) but the requirement is K6-parked, which the audit rules exclude. "check user cooldown" appears only
