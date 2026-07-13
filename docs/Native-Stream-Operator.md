# Twitch bot - real-time chat bot

> **Status (2026-07-03):** spec + implementation plan. Nothing built yet.
> **Live stack this bot plugs into:** BizHawk (EmuHawk) runs FireRed with
> `bizhawk/ai_bridge.lua`; `scripts/stream.py` is the control process that owns
> the bridge (single-owner rule) and serves the operator/viewer boards on
> `http://127.0.0.1:8777`. The bot is a SEPARATE process that talks to the game
> only through the control process's HTTP API, never to the emulator directly.
> Storyline progress: Part 1 complete (starter chosen, first rival battle won
> 2026-07-02); Part 2 (Route 1 / Viridian) is the next game-side build.
> **Pairs with:** `docs/ROADMAP.md` (goal ladder + loop-engineering runbook),
> `docs/Walkthrough-notes-to-fix.md` (story source), `ARCHITECTURE.md` §0.

- **Build Twitch as the live interaction control layer, then repurpose output to YouTube and TikTok.** Twitch should be the primary runtime because EventSub supports real-time platform events such as chat messages, Channel Point redemptions, polls, predictions, raids, stream online/offline, suspicious users, and moderation-related events.
- YouTube should be treated as the **archive, search, replay, Shorts, and long-form monetization layer**. Its Live Streaming API exposes live chat message resources and polling-based retrieval, but the interaction stack is less naturally built around Channel Points-style chaos.
- TikTok should be treated as the **discovery and clips surface**, not the core bot runtime. TikTok’s official developer surface emphasizes login, display, embeds, webhooks, content posting, and related products; its official docs are not as Twitch-native for programmable live chat/game-effect control.

Example build: C:\Users\Sagac\OneDrive\GPTs\Live AI Chat  (verified present 2026-07-03)
- Reusable pieces to mine: `Conversation-Bot/`, `TTV-Sentiment-Bot/`, `chatbot.py`,
  `points.json` (a points ledger that can inform the PokéCoin design), `emotes_list.txt`
- do NOT use wandb or weave (the `wandb/`, `weave-run/` dirs there are dead weight)
- we will use similar features like basic huggingface AI inference (HF router; the
  same isolated-HTTP pattern as `knowledge/llm_advisor.py`; needs `HF_TOKEN`)
- we can capture a form of sentiment features
- already has information ready to use for connecting to channel

## High-level priority list
1. Engage Viewers
2. Protect Chat
3. Trigger stream events
4. Trigger game events
5. Drive revenue without feeling spammy
6. Provide analytics for real-time & post stream

## Core Twitch Integration Model

Twitch’s current direction favors **EventSub for reading events** and the Twitch API for sending/managing actions. Twitch’s IRC docs state IRC is limited and that full chatbot functionality requires API calls; Twitch’s migration docs recommend EventSub for reading chat messages and Twitch API for sending chat messages.

### Minimum EventSub subscriptions

|Need|EventSub type|
|---|---|
|Chat messages|`channel.chat.message`|
|Message deleted|`channel.chat.message_delete`|
|Chat cleared|`channel.chat.clear`|
|Chat settings changed|`channel.chat_settings.update`|
|Channel Points custom reward|`channel.channel_points_custom_reward_redemption.add`|
|Reward status update|`channel.channel_points_custom_reward_redemption.update`|
|Poll begin/progress/end|`channel.poll.begin`, `channel.poll.progress`, `channel.poll.end`|
|Prediction begin/progress/lock/end|`channel.prediction.begin`, `channel.prediction.progress`, `channel.prediction.lock`, `channel.prediction.end`|
|Raid received|`channel.raid`|
|Sub/resub/gift/cheer|sub and cheer events|
|Suspicious users|`channel.suspicious_user.message`, `channel.suspicious_user.update`|
|Stream status|`stream.online`, `stream.offline`|

### API actions needed
|Bot action|Twitch API capability|
|---|---|
|Send chat message|Chat Send Chat Message|
|Send announcement|Chat Send Chat Announcement|
|Shoutout creator|Chat Send a Shoutout|
|Create/end polls|Polls API|
|Create/manage predictions|Predictions API|
|Delete message|Moderation Delete Chat Messages|
|Timeout/ban|Moderation Ban User|
|Create clips|Clips Create Clip|
|Create/manage rewards|Channel Points Custom Rewards|
## Design principle: event loops, not commands

### Primary event loops

| Loop              | Trigger                               | Bot decision                         | Output                             |
| ----------------- | ------------------------------------- | ------------------------------------ | ---------------------------------- |
| Viewer onboarding | First chat/redeem/sub                 | New vs returning viewer              | Greeting or recognition            |
| Moderation        | Every chat message                    | Risk score + policy                  | Allow, warn, delete, timeout, flag |
| Interaction       | Poll/redeem/chat vote                 | Is stream state safe?                | Poll, queue action, game effect    |
| Game-effect       | Channel Point redemption              | Cooldowns + chaos meter + game state | Execute, delay, reject, refund     |
| Promo             | Stream moment                         | Context + cooldown                   | Promo message or no-op             |
| Clip              | Chat spike, `!clip`, win, major event | Candidate score                      | Timestamp marker / clip            |
| Analytics         | Every event                           | Aggregate after stream               | Summary report                     |
This is the main product distinction: **the bot is a stream operating system.**

### State Rules

|Game State|Meaning|Promos|Greetings|Polls/Votes|Channel Points|Game Effects|Bot Behavior|
|---|---|--:|--:|--:|--:|--:|---|
|`STARTING_SOON`|Stream is live but game/AI has not started|Low|Yes|Yes|Low-risk only|No|Explain the run, show rules, invite viewers to vote on early goals|
|`INTRO`|Oak intro, naming player/rival, startup flow|No|Yes|Yes|Low-risk only|No|Let chat vote on names or starter if you want controlled interaction|
|`PALLET_TOWN`|Early setup before Route 1|Low|Yes|Yes|Low-risk|Low|Allow simple choices like checking menu, talking to NPCs, naming rules|
|`ROUTE_TRAVEL`|Walking through routes, non-critical navigation|Contextual|Yes|Yes|Yes|Low/medium|Good state for chat-driven movement challenges, route choices, or encounter goals|
|`WILD_BATTLE`|Normal wild Pokémon encounter|No|Limited|Limited|Yes|Low/medium|Allow catch/defeat votes, move restrictions, or “try to catch next encounter”|
|`TRAINER_BATTLE`|Regular trainer battle|No|Limited|Limited|Restricted|Low only|Avoid disruptive effects unless battle is easy and AI is stable|
|`RIVAL_BATTLE`|Rival fight|No|No|No|Restricted|Safe only|Treat as high-focus; allow only cosmetic or commentary effects|
|`GYM_BATTLE`|Gym trainer or leader battle|No|No|No|Safe only|Safe only|Disable chaos effects; allow only explanation, clip marks, or chat reactions|
|`LOW_HP_DANGER`|Any battle where active Pokémon is at risky HP|No|No|No|Safe only|No|Bot should suppress distractions and prevent forced bad actions|
|`STATUS_DANGER`|Poison, burn, sleep, confusion, etc. in important battle|No|No|No|Safe only|No|Same as danger mode; prioritize survival|
|`MENUING`|Bag, party, Pokémon status, save screen, options|No|Limited|Yes|Low-risk|Low|Allow “show party,” “check stats,” “explain AI plan,” but block random inputs|
|`SHOPPING`|Poké Mart buying/selling|Contextual|Yes|Yes|Low-risk|Low|Let chat vote on shopping priorities, but block wasteful purchases|
|`POKEMON_CENTER`|Healing or PC access|Low|Yes|Yes|Low-risk|Low|Safe for Q&A, promos, polls, and queue management|
|`CATCH_DECISION`|AI is deciding whether to catch a Pokémon|No|No|Yes|Yes|Low/medium|Let chat vote “catch or skip,” nickname, or catch strategy|
|`PARTY_MANAGEMENT`|Switching party members, moves, PC box decisions|No|Limited|Yes|Low-risk|Low|Allow viewer votes, but require mod approval for irreversible actions|
|`MOVE_LEARNING`|Pokémon is learning a new move|No|No|Yes|Low-risk|No|Poll or mod approval required; never auto-delete important moves blindly|
|`EVOLUTION`|Pokémon is evolving|No|Yes|Yes|Low-risk|No|Allow celebration, clip marker, nickname/lore prompts|
|`ITEM_USE_DECISION`|AI may use potion, antidote, Poké Ball, escape rope, etc.|No|No|Limited|Safe only|No|Block viewer-forced item wasting unless explicitly part of challenge mode|
|`CUTSCENE`|Scripted sequence or dialogue-heavy moment|Low|Yes|Yes|Low-risk|No|Good time for explanation, lore, Q&A, and light promos|
|`SAVE_CRITICAL`|Saving, loading, emulator state handling|No|No|No|No|No|Lock all interaction effects; only owner/mod/admin can act|
|`BOSS_TRANSITION`|Before rival, Gym Leader, Giovanni, Elite Four, major fight|No|Limited|Yes|Safe only|No|Allow predictions, hype polls, and clip preparation; block disruptive effects|
|`ELITE_FOUR`|Elite Four / Champion sequence|No|No|Limited|Safe only|Safe only|Highest protection state; effects should be cosmetic or commentary only|
|`POST_BATTLE_SAFE`|Immediately after battle ends|Yes|Yes|Yes|Yes|Low/medium|Best state for promos, polls, clip prompts, viewer rewards, and recap|
|`BETWEEN_OBJECTIVES`|AI is deciding the next macro objective|Yes|Yes|Yes|Yes|Low/medium|Best state for chat voting: train, catch, route, shop, gym, explore|
|`QUEUE_OPEN`|Viewer queue/challenge mode is open|Contextual|Yes|Yes|Yes|Yes|Allow approved redemptions and queued viewer challenges|
|`STRICT_MODE`|Raid spam, bot attack, or moderation pressure|No|No|No|Restricted|Restricted|Tighten moderation, disable promos, slow interactions, alert human mods|
|`ENDING_SOON`|Stream is wrapping up|Yes|Yes|Yes|Low-risk|No|Promote YouTube/Discord, summarize progress, show next-stream objective|
|`OFFLINE`|Stream is not active|No|No|No|No|No|Store nothing except system/admin actions|

### State detectability (game-side reality check, 2026-07)

The bot consumes `stream_state` from the control process; it never derives it
from pixels. What the game plane can emit today vs what is blocked on
game-side work:

- **Detectable now:** `STARTING_SOON`, `INTRO`, `PALLET_TOWN`, `RIVAL_BATTLE`
  (battle detect + story step), `CUTSCENE` (control lock), `SAVE_CRITICAL`
  (slot save/load in progress), `LOW_HP_DANGER` (party HP reads exist),
  `OFFLINE`.
- **Arrives with the Part 2 build:** `ROUTE_TRAVEL`, `WILD_BATTLE` vs
  `TRAINER_BATTLE` split (one more RAM flag), `POKEMON_CENTER`, `SHOPPING`,
  `POST_BATTLE_SAFE`, `BETWEEN_OBJECTIVES` (task-queue idle).
- **Blocked on unbuilt perception:** `STATUS_DANGER` (status-condition read),
  `MENUING` / `MOVE_LEARNING` / `EVOLUTION` (screen-context machine),
  `CATCH_DECISION` (catch system), `GYM_BATTLE` / `BOSS_TRANSITION`
  (story-step tagging, lands with the Brock arc), `ELITE_FOUR` (far).
- `QUEUE_OPEN`, `STRICT_MODE`, `ENDING_SOON` are bot/operator states, not game
  states; they come from the operator panel or bot logic.

Rule: a state the classifier cannot emit yet resolves to its nearest safer
ancestor (unknown battle context means `TRAINER_BATTLE` restrictions; unknown
overworld context means `ROUTE_TRAVEL` with effects held to Low).

### Practical rule tiers

| Rule Tier       | Allowed Effects                                  | Example                                                         |
| --------------- | ------------------------------------------------ | --------------------------------------------------------------- |
| **Safe**        | No gameplay harm                                 | `!party`, explain AI plan, mark clip, show badges               |
| **Low-risk**    | Minor delay or information display               | Open menu, check stats, show Pokédex                            |
| **Medium-risk** | Can affect gameplay but not ruin run             | Use first move next wild battle, random direction for 5 seconds |
| **High-risk**   | Can cause loss, waste resources, or derail route | Forced item use, forced switch, no healing                      |
| **Banned**      | Irreversible or destructive                      | Release Pokémon, delete save, corrupt state, waste rare items   |

### Default blocking rules

|Condition|Bot Rule|
|---|---|
|Active Pokémon HP below 30%|Disable all disruptive effects|
|Rival/Gym/Elite Four battle|Safe effects only|
|Save/load screen active|Disable all viewer effects|
|Learning a move|Require poll or mod approval|
|Using rare item/TM/evolution stone|Require mod approval|
|PC box management|Require mod approval|
|Raid spam detected|Enable strict mode and pause redemptions|
|AI is stuck/recovering|Pause effects until stable|
## Feature backlog
### Bot Features Specific to Pokeai
> Feature: The bot is its own process, launched alongside the control process
> (a second launcher or a flag on `run_stream.bat`). It enters 6Genix Twitch
> chat (https://www.twitch.tv/6genix) whenever it runs, live or not (Twitch
> chat works while offline, which is also how we test). It reaches the game
> ONLY via the control process HTTP API on 127.0.0.1:8777, keeping the
> two-control-planes rule intact even at process level.
> Feature: Operator panel has a bot tab
> 	- Settings:
> 		- Bot name (editable)
> 		- Bot greeting (editable)
> 		- Pause bot / strict mode / promo mode toggles (mirrors of the ! commands)
> 	- Status: connected/disconnected, EventSub subscription health, last error

### P0: MVP foundation

| Priority | Feature                       | Acceptance criteria                                                 |
| -------- | ----------------------------- | ------------------------------------------------------------------- |
| P0       | Twitch OAuth setup            | Broadcaster + bot auth, scopes documented, token refresh works.     |
| P0       | EventSub connection           | Connects, subscribes, reconnects, dedupes event IDs.                |
| P0       | Chat listener                 | Receives chat messages reliably.                                    |
| P0       | Chat sender                   | Sends messages with cooldown and queue.                             |
| P0       | Viewer DB                     | Creates viewer record only after chat/redeem/sub, not lurker entry. |
| P0       | First-time chatter greeting   | Greets once after first message.                                    |
| P0       | Returning chatter recognition | Recognizes once per stream after user speaks.                       |
| P0       | Moderation v1                 | Spam, caps, repeated messages, links, blocked terms.                |
| P0       | Command system                | Public + mod-only commands.                                         |
| P0       | Channel Point listener        | Captures custom reward redemptions.                                 |
| P0       | Promo cooldown engine         | Global + per-command + contextual cooldowns.                        |
| P0       | Stream state                  | Manual state switching via mod command/dashboard.                   |
| P0       | Analytics summary             | Post-stream message counts, unique chatters, redemptions, clips.    |
EventSub WebSocket messages can be delivered more than once, so store Twitch message/event IDs and dedupe them before executing actions.

### P1: Interaction system

|Priority|Feature|Acceptance criteria|
|---|---|---|
|P1|Poll manager|Mod creates/ends polls from dashboard or command.|
|P1|Prediction manager|Start, lock, resolve prediction.|
|P1|Q&A queue|Viewers ask, mods approve, bot surfaces.|
|P1|Challenge queue|Redemptions create challenge candidates.|
|P1|Clip marker|`!clip` stores timestamp and context.|
|P1|Chat spike detection|Detects unusual message velocity.|
|P1|Mod dashboard v1|Toggle strict mode, promo mode, pause bot, approve queue.|
|P1|OBS overlay|Shows poll, chaos meter, active effect, queue.|
Twitch Poll creation requires the `channel:manage:polls` scope, while poll read-only use can use `channel:read:polls`; Twitch documents creating, ending, and retrieving polls via the Polls API.

### P2: Game-effect system

|Priority|Feature|Acceptance criteria|
|---|---|---|
|P2|Effect catalog|Every effect has risk, cooldown, duration, cost, allowed states.|
|P2|Chaos meter|Global chaos budget increases/decreases over time.|
|P2|Effect queue|Queue, priority, approval, cancellation.|
|P2|Refund failed redemption|Failed effects marked for manual refund workflow or API update.|
|P2|Game directive API|Bot posts whitelisted directives to the stream.py control API; the agent consumes them at safe points. No direct emulator access.|
|P2|Safe mode|Disables high-risk effects during key game states.|
|P2|Crowd Control integration|Use Crowd Control where supported; custom bridge where not.|
Crowd Control advertises Twitch integration through follows, subscriptions, raids, Channel Points, and Twitch Extensions, and its developer docs describe SDK/game-pack/modding paths for custom integrations.

### P3: Productization

| Priority | Feature               | Acceptance criteria                                     |
| -------- | --------------------- | ------------------------------------------------------- |
| P3       | Multi-channel support | Multiple streamers/channels configured.                 |
| P3       | Extension/panel       | Viewer-facing queue, chaos meter, profile-lite display. |
| P3       | Admin billing         | Stripe or license management.                           |
| P3       | Template packs        | Pokémon pack, FPS pack, variety pack.                   |
| P3       | Analytics dashboard   | Trend reports across streams.                           |
| P3       | Creator CRM           | Viewer cohorts, retention, redemptions, conversion.     |
Twitch Extensions are webpages embedded into Twitch as panels, overlays, or other interactive surfaces, and Twitch provides extension-specific reference/guidelines.

## Database schema

**Storage decision (2026-07):** start on **SQLite** (single file beside the bot; JSON1 for JSONB fields, TEXT for UUIDs, arrays as JSON). The schema below stays Postgres-shaped so a later P3 migration is mechanical; Postgres only earns its keep at multi-channel productization.

### Core tables

```
CREATE TABLE stream_sessions (    id UUID PRIMARY KEY,    twitch_channel_id TEXT NOT NULL,    title TEXT,    game_name TEXT,    started_at TIMESTAMPTZ NOT NULL,    ended_at TIMESTAMPTZ,    current_state TEXT NOT NULL DEFAULT 'OFFLINE',    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE viewers (    id UUID PRIMARY KEY,    twitch_user_id TEXT UNIQUE NOT NULL,    twitch_login TEXT NOT NULL,    display_name TEXT,    first_seen_at TIMESTAMPTZ NOT NULL,    last_seen_at TIMESTAMPTZ,    first_chat_at TIMESTAMPTZ,    last_chat_at TIMESTAMPTZ,    message_count INTEGER NOT NULL DEFAULT 0,    stream_count INTEGER NOT NULL DEFAULT 0,    watch_streak INTEGER NOT NULL DEFAULT 0,    favorite_game TEXT,    favorite_mode TEXT,    vip_status BOOLEAN NOT NULL DEFAULT false,    sub_status BOOLEAN NOT NULL DEFAULT false,    mod_status BOOLEAN NOT NULL DEFAULT false,    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE viewer_stream_presence (    id UUID PRIMARY KEY,    viewer_id UUID REFERENCES viewers(id),    stream_session_id UUID REFERENCES stream_sessions(id),    first_event_at TIMESTAMPTZ NOT NULL,    last_event_at TIMESTAMPTZ NOT NULL,    first_message_sent BOOLEAN NOT NULL DEFAULT false,    greeted_this_stream BOOLEAN NOT NULL DEFAULT false,    returning_recognized BOOLEAN NOT NULL DEFAULT false,    message_count INTEGER NOT NULL DEFAULT 0,    redemption_count INTEGER NOT NULL DEFAULT 0,    UNIQUE(viewer_id, stream_session_id));
```

### Event log

```
CREATE TABLE twitch_events (    id UUID PRIMARY KEY,    twitch_event_id TEXT UNIQUE,    event_type TEXT NOT NULL,    stream_session_id UUID REFERENCES stream_sessions(id),    viewer_id UUID REFERENCES viewers(id),    raw_payload JSONB NOT NULL,    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),    processed_at TIMESTAMPTZ,    processing_status TEXT NOT NULL DEFAULT 'PENDING',    error_message TEXT);
```

### Chat messages

```
CREATE TABLE chat_messages (    id UUID PRIMARY KEY,    twitch_message_id TEXT UNIQUE,    stream_session_id UUID REFERENCES stream_sessions(id),    viewer_id UUID REFERENCES viewers(id),    message_text TEXT NOT NULL,    message_type TEXT DEFAULT 'chat',    is_command BOOLEAN NOT NULL DEFAULT false,    moderation_score NUMERIC(5,2),    moderation_action TEXT,    deleted BOOLEAN NOT NULL DEFAULT false,    created_at TIMESTAMPTZ NOT NULL);
```

### Moderation

```
CREATE TABLE moderation_actions (    id UUID PRIMARY KEY,    stream_session_id UUID REFERENCES stream_sessions(id),    viewer_id UUID REFERENCES viewers(id),    moderator_user_id TEXT,    action_type TEXT NOT NULL, -- WARN, DELETE, TIMEOUT, BAN, FLAG    reason TEXT,    duration_seconds INTEGER,    source TEXT NOT NULL, -- BOT, HUMAN_MOD, TWITCH_AUTOMOD    related_message_id UUID REFERENCES chat_messages(id),    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE mod_notes (    id UUID PRIMARY KEY,    viewer_id UUID REFERENCES viewers(id),    note TEXT NOT NULL,    created_by TEXT NOT NULL,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
```

### Commands

```
CREATE TABLE commands (    id UUID PRIMARY KEY,    command_name TEXT UNIQUE NOT NULL,    response_template TEXT,    permission_level TEXT NOT NULL DEFAULT 'PUBLIC',    enabled BOOLEAN NOT NULL DEFAULT true,    global_cooldown_seconds INTEGER NOT NULL DEFAULT 30,    user_cooldown_seconds INTEGER NOT NULL DEFAULT 60,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE command_invocations (    id UUID PRIMARY KEY,    command_id UUID REFERENCES commands(id),    viewer_id UUID REFERENCES viewers(id),    stream_session_id UUID REFERENCES stream_sessions(id),    args TEXT,    response_sent BOOLEAN NOT NULL DEFAULT false,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
```

### Promos

```
CREATE TABLE promos (    id UUID PRIMARY KEY,    promo_key TEXT UNIQUE NOT NULL,    message_template TEXT NOT NULL,    link_url TEXT,    utm_campaign TEXT,    trigger_context TEXT, -- WIN, SUB, QUESTION, BETWEEN_OBJECTIVES, ENDING    enabled BOOLEAN NOT NULL DEFAULT true,    global_cooldown_minutes INTEGER NOT NULL DEFAULT 30,    stream_max_count INTEGER NOT NULL DEFAULT 3,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE promo_impressions (    id UUID PRIMARY KEY,    promo_id UUID REFERENCES promos(id),    stream_session_id UUID REFERENCES stream_sessions(id),    trigger_event_id UUID REFERENCES twitch_events(id),    message_sent TEXT,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
```

### Channel Points and effects

```
CREATE TABLE channel_point_rewards (    id UUID PRIMARY KEY,    twitch_reward_id TEXT UNIQUE NOT NULL,    reward_name TEXT NOT NULL,    reward_type TEXT NOT NULL, -- HYDRATE, CHALLENGE, GAME_EFFECT, QNA, CLIP    enabled BOOLEAN NOT NULL DEFAULT true,    requires_mod_approval BOOLEAN NOT NULL DEFAULT false,    cooldown_seconds INTEGER NOT NULL DEFAULT 60,    per_user_cooldown_seconds INTEGER NOT NULL DEFAULT 300,    allowed_states TEXT[] NOT NULL DEFAULT '{}',    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE redemptions (    id UUID PRIMARY KEY,    twitch_redemption_id TEXT UNIQUE NOT NULL,    reward_id UUID REFERENCES channel_point_rewards(id),    viewer_id UUID REFERENCES viewers(id),    stream_session_id UUID REFERENCES stream_sessions(id),    user_input TEXT,    status TEXT NOT NULL DEFAULT 'QUEUED', -- QUEUED, APPROVED, EXECUTED, FAILED, REJECTED, REFUND_REQUESTED    failure_reason TEXT,    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),    executed_at TIMESTAMPTZ);CREATE TABLE game_effects (    id UUID PRIMARY KEY,    effect_key TEXT UNIQUE NOT NULL,    display_name TEXT NOT NULL,    description TEXT,    risk_level TEXT NOT NULL, -- LOW, MEDIUM, HIGH, RUN_ENDING    default_duration_seconds INTEGER,    global_cooldown_seconds INTEGER NOT NULL DEFAULT 60,    per_user_cooldown_seconds INTEGER NOT NULL DEFAULT 300,    chaos_cost INTEGER NOT NULL DEFAULT 1,    allowed_states TEXT[] NOT NULL DEFAULT '{}',    disabled_states TEXT[] NOT NULL DEFAULT '{}',    enabled BOOLEAN NOT NULL DEFAULT true);CREATE TABLE effect_queue (    id UUID PRIMARY KEY,    redemption_id UUID REFERENCES redemptions(id),    effect_id UUID REFERENCES game_effects(id),    stream_session_id UUID REFERENCES stream_sessions(id),    viewer_id UUID REFERENCES viewers(id),    priority INTEGER NOT NULL DEFAULT 100,    status TEXT NOT NULL DEFAULT 'QUEUED',    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),    executed_at TIMESTAMPTZ,    expires_at TIMESTAMPTZ);
```

### Clips and analytics

```
CREATE TABLE clip_markers (    id UUID PRIMARY KEY,    stream_session_id UUID REFERENCES stream_sessions(id),    viewer_id UUID REFERENCES viewers(id),    source TEXT NOT NULL, -- COMMAND, CHAT_SPIKE, REDEMPTION, MANUAL, GAME_EVENT    label TEXT,    timestamp_seconds INTEGER,    context JSONB,    score NUMERIC(5,2) DEFAULT 0,    twitch_clip_id TEXT,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE stream_metrics (    id UUID PRIMARY KEY,    stream_session_id UUID REFERENCES stream_sessions(id),    metric_key TEXT NOT NULL,    metric_value NUMERIC,    dimensions JSONB,    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
```


## Event flows

### Flow A: first-time chatter greeting

```
EventSub: channel.chat.message  ↓dedupe twitch event/message ID  ↓upsert viewer by twitch_user_id  ↓find viewer_stream_presence  ↓if first_chat_at is null:    set first_chat_at    send first-time greetingelse if not returning_recognized this stream:    send returning recognitionelse:    no greeting  ↓increment message counts  ↓route command/moderation/analytics
```

**Important:** do not greet based on passive presence. Only greet after a user sends a message, redeems, subscribes, cheers, or otherwise actively interacts.

Example response templates:

```
First-time:"Welcome in, {display_name}. You caught the AI mid-run."Returning:"Good to see you again, {display_name}. The AI is still making questionable decisions."Lurk:"Enjoy the lurk, {display_name}. No callouts from here."
```

### Flow B: moderation

```
chat message  ↓normalize text  ↓check allowlist: broadcaster, mods, VIP exceptions  ↓score rules:    repeated message    link/domain risk    caps ratio    symbol spam    hate/harassment terms    raid spam velocity    suspicious user event  ↓decision:    ALLOW    WARN    DELETE    TIMEOUT    BAN    FLAG_MOD  ↓execute through Twitch API where needed  ↓log action
```

Twitch’s API supports banning users or placing them in timeouts, and supports removing single chat messages or clearing chat messages through moderation endpoints.

### Flow C: Channel Point game effect

```
channel.channel_points_custom_reward_redemption.add  ↓dedupe redemption ID  ↓map twitch_reward_id → internal reward  ↓check stream_state  ↓check user cooldown  ↓check global cooldown  ↓check chaos meter  ↓if approval required:    queue for mod approvalelse:    queue for execution  ↓game bridge executes effect  ↓mark EXECUTED or FAILED  ↓if failed:    mark REFUND_REQUESTED
```

### Flow D: contextual promo

```
event occurs:    win / sub / clutch / viewer asks setup / between match  ↓promo engine checks:    stream_state allows promos?    global promo cooldown passed?    specific promo cooldown passed?    max stream count not exceeded?    chat velocity not too high?  ↓send promo or no-op  ↓log impression
```

Promo rule:

```
Never send sales promos during clutch/high-focus states.Never send more than one promo inside a short window.Always give viewers command-based access when they ask.
```

### Flow E: clip assistant

```
signals:    !clip    chat velocity spike    major redemption    win/boss fight    high emotion phrase    manual mod marker  ↓create clip_marker  ↓score marker:    chat spike +2    redemption +1    win/clutch +3    multiple viewers reacting +2    streamer manually marks +5  ↓post-stream report:    top 10 candidates    timestamp    reason    suggested title
```

Twitch supports creating clips from a broadcaster’s live stream through the Create Clip API with the `clips:edit` scope.

## Moderation policy

### Rule matrix

|Behavior|First action|Repeat action|Severe action|
|---|---|---|---|
|Mild spam|Warn|Timeout 60s|Timeout 10m|
|Repeated message|Delete + warn|Timeout|Flag mod|
|Unknown link|Delete/hold|Timeout|Ban if malicious|
|Caps spam|Warn|Timeout|Strict mode|
|Harassment|Delete + timeout|Longer timeout|Ban|
|Hate/slurs|Delete + timeout/ban|Ban|Ban|
|Raid spam|Enable strict mode|Slow mode/sub mode if needed|Human mod alert|
|Suspicious user|Flag mod|Restrict interactions|Human decision|
### Mod override controls

Commands:

```
!bot pause!bot resume!strict on!strict off!promo on!promo off!allowlink domain.com!blocklink domain.com!warn username reason!timeout username 60 reason!ban username reason!effect pause!effect resume!chaos reset
```

Dashboard toggles:

```
Pause botStrict moderationPromo modeSafe modeQueue openGiveaway activeSponsor segmentEffect queue pausedManual approval required
```

# Pokémon FireRed AI bot integration

## Separate the bot into two control planes

```
Twitch Bot Control Plane- viewers- chat- redemptions- moderation- promos- analyticsGame Agent Control Plane- emulator state- game memory/state- AI policy- input actions- save/load discipline- route/task objectives
```

Do not let Twitch chat directly mutate the emulator. Chat should request effects through a **validated queue**. Interactions are ranked by user's loyalty rating (follower, subscriber, tipper, donator, Kameron's manual additions, etc.).

## Pokémon-specific interaction loops

|Interaction|Safe?|Example|
|---|---|---|
|Name next caught Pokémon|High|Channel Points or poll|
|Vote next route objective|High|Route 22 vs Route 2|
|Choose training focus|High|Level Mankey, train starter, catch backup|
|Force menu check|High|AI opens party/status|
|Force Pokédex check|High|Low-disruption|
|Force random move in battle|Medium|Disable during gyms/rival fights|
|Force item use|Medium|Only allowed in wild battles|
|Disable Pokémon Center|High risk|Challenge mode only|
|Release Pokémon|No|Never allow|
|Save/load state|No|Bot-only/admin-only|

## Emulator bridge (updated 2026-07-03 to the live stack)

The earlier mGBA recommendation is retired. Production runs **BizHawk
(EmuHawk)** with `bizhawk/ai_bridge.lua`, and `scripts/stream.py` already owns
that socket under a single-owner rule (only the control process worker thread
touches the bridge). The bot therefore never opens its own emulator connection:

```
Bot process (Twitch control plane)
  | localhost HTTP (127.0.0.1:8777)
  v
stream.py control process (game control plane; owns BizHawkBridge)
  | TCP socket 51055
  v
ai_bridge.lua inside EmuHawk
  | read EWRAM / inject inputs
  v
Pokemon FireRed
```

What stream.py must grow for the bot (game-side work, tracked in ROADMAP.md):
- `GET /api/context` - read-only snapshot: stream_state, map/route name, party
  (species/level/HP), badges, money, active task + progress, recent events, and
  the active Nuzlocke ruleset (`nuzlocke`: rules + tracker, null when inactive).
- `GET /api/nuzlocke` - the Nuzlocke rule catalog (SSOT projection) + the active
  rules + tracker; the bot's `!nuzlockerules` reads this.
- `POST /api/directive` - whitelisted, queue-based directives the agent
  consumes at safe points (never raw buttons from viewers). Whitelist v1:
  `show_party`, `explain_plan`, `catch_next_encounter`, `nickname_next_catch`,
  `enqueue_quest`, `set_nuzlocke` (args `{"rule": "<rulekey>|random|clear"}`).
- `POST /api/announce` - banners on the operator/viewer boards for big bot
  moments (poll results, badge predictions).

CrowdControl integrates with BizHawk directly (its own Lua pack, its own memory
writes); that path stays separate from our bridge on purpose (see PokéCoins).

## Game-effect examples for FireRed

```
LOW RISK- show party status- open trainer card- name next Pokémon- vote next destination- force one Pokédex check- force AI explanation of current planMEDIUM RISK- next battle must use first move slot- next wild encounter must attempt catch- no healing for 3 minutes- switch lead Pokémon after battle- walk in random direction for 5 secondsHIGH RISK- disable running- force item use- force switch during battle- invert controls brieflyDISABLED BY DEFAULT- release Pokémon- delete save- waste rare items- force loss- corrupt memory
```

# Command set

## Public commands

```
!rank       Current rank/SR or current Pokémon run status!loadout    Current weapon/loadout or Pokémon party!settings   Controller/sensitivity/FOV or emulator/settings!discord    Community funnel!youtube    YouTube/clips funnel!merch      Merch link!coaching   Paid offer!challenge  Current challenge or submit challenge!queue      Viewer game/request queue!clip       Mark current moment!rules      Chat rules!lurk       Lurk without callout!uptime     Stream duration!so         Shoutout another creator
```

## Mod-only commands

```
!poll create "question" "option1" "option2"!poll end!predict create "Will the AI win this battle?" "Yes" "No"!predict lock!predict resolve yes!state route_travel!state between_objectives!promo on/off!strict on/off!bot pause/resume!effect approve <id>!effect reject <id>!giveaway start/end
```

## Pokémon-specific commands

```
!party        Current party
!badges       Current badges
!route        Current objective
!rival        Rival fight status
!catch        Catching rules
!ai           Current AI plan
!mistakes     Recent AI mistakes
!next         Next planned
!questlist    Provides upcoming quests, required vs optional
!quest [quest name]  Enqueue an optional quest (mod/approval-gated)
!nuzlockerules       List the Nuzlocke rules viewers can choose from (read-only)
!nuzlocke            Show the active Nuzlocke ruleset + tracker (deaths/encounters/areas)
!nuzlocke add <rule> Add one Nuzlocke rule (public, state-gated)
!nuzlocke random [n] Roll a random Nuzlocke ruleset (public, state-gated)
!nuzlocke clear      Clear the Nuzlocke ruleset (mod/broadcaster-gated)
```

**Nuzlocke (viewer-driven, randomizable).** The rule catalog is the SSOT in
`src/pokeai/rules/nuzlocke.py` (core: `permadeath`, `first_encounter`,
`nickname_all`; optional/difficulty clauses like `dupes_clause`, `species_clause`,
`no_battle_items`, `no_pokemon_centers`, `level_cap`, `set_mode`; display-only:
`shiny_clause`, `no_legendaries`, `mono_type`). Each rule declares `enforced`:
enforced rules ride a real AI decision seam; display-only rules are tracked/shown
with `enforced=false` and dimmed on the boards so viewers are not misled. Requests
ride the existing `EffectQueue -> EffectConsumer -> /api/directive` seam via the
`set_nuzlocke` directive; `nuzlocke_clear` is mod-gated in `_submit_effect` so
`!redeem nuzlocke_clear` cannot sidestep it.

### Interaction requests

**Interaction Request Engine**, not a normal promo engine.

A promo engine says: “Join Discord,” “Buy merch,” “Use CrowdControl.”

An interaction request engine says, in-character: **“The AI is low on options. Someone can stabilize the run by sending PokéCoins, items, chaos, mercy, or pain.”**

Crowd Control supports Twitch integrations where viewers can use follows, subs, raids, Channel Points, or the Twitch Extension to trigger in-game effects, and its docs describe viewers acquiring coins through Bits, Channel Points, donations, free session coins, and subscriber benefits.

Twitch also exposes Channel Point redemption events through EventSub, including `channel.channel_points_custom_reward_redemption.add`, which lets your bot react when viewers redeem a custom reward.
#### PokéCoins, defined (and the memory-write rule)

"PokéCoins" is the viewer-facing name for **support credit**, not a new wallet:
a redemption bucket funded by Channel Points and (later) CrowdControl coins.
Two hard rules keep it honest:

1. **Our bridge never writes game RAM.** Bot-originated effects are inputs and
   AI directives only ("do a funded shopping trip", "attempt catch next
   encounter"). In-game money/items change only through legitimate play by the
   agent.
2. **RAM-level chaos belongs to CrowdControl** (its BizHawk packs do their own
   memory writes). That keeps a clean line: CrowdControl = external chaos the
   AI must detect and react to (the DisruptionMonitor feature); our bot =
   sanctioned requests through the validated directive queue.

Consequence for the risk tables: "add money/resources" as a direct RAM write is
**Banned** from our bridge; "PokéCoin Support" as a funded-errand directive is
Low risk. That is what the categories below mean.

#### Integration description

##### Core concept

```
Stream context  ↓Seed request selected  ↓Bot adds viewer/game/state context  ↓Small AI model rewrites request  ↓Safety/brand filter  ↓Cooldown + stream-state check  ↓Bot posts tailored interaction request  ↓Viewer redeems CrowdControl / Channel Points / PokéCoins  ↓Effect enters game-effect queue
```

The goal is to make the bot feel like a **living stream companion** that reacts to the run instead of repeating static sales copy.

The bot should not fake real financial desperation. Keep it framed as **game pressure, AI distress, tactical need, comedy, or narrative urgency**.

##### Core loop:

Seed Request
→ Context Builder
→ Hugging Face LLM Rewrite
→ Safety/Style Filter
→ Cooldown + Stream-State Check
→ Twitch Chat / Overlay / TTS Output
→ Track Interaction Result

The goal is not “begging” in a desperate way. The better framing is:

> The bot roleplays the game state and makes interaction feel like viewers are part of the run.
##### Request style table

|Request Style|Description|Best Used When|Example Seed|Example AI-Tailored Output|
|---|---|---|---|---|
|**Emergency Plea**|Bot acts like the AI/player is in trouble and needs viewer help.|Low HP, poisoned, bad battle, low money|`Need PokéCoins for healing items.`|“The AI is staring at 11 HP and pretending this is fine. Someone send a PokéCoin boost before this becomes a documentary about failure.”|
|**Coach Request**|Bot asks chat to help improve the AI’s decision-making.|Between battles, after mistake|`Ask viewers to guide next action.`|“The AI just made a questionable route decision. Chat, use a control effect if you want to steer it back toward competence.”|
|**Challenge Invitation**|Bot invites viewers to make the run harder or funnier.|Safe route travel, wild battles|`Ask viewers to trigger a challenge.`|“Route 22 is too calm. Someone can make this interesting with a challenge effect before the AI gets comfortable.”|
|**Resource Shortage**|Bot frames interaction as helping with in-game scarcity.|Low money, low Poké Balls, low potions|`Need resources for next objective.`|“Inventory report: optimism high, supplies low. PokéCoin help would keep this run from becoming a walking simulator.”|
|**Narrator Prompt**|Bot narrates the moment like a game announcer.|General engagement|`Ask viewers to affect the run.`|“The AI advances into danger. Viewers may now intervene, sabotage, rescue, or simply watch the machine learn the hard way.”|
|**Rival Taunt**|Bot uses the rival/enemy voice to provoke viewers.|Rival battle, boss transition|`Rival mocks chat for not helping.`|“The rival says chat is too scared to interfere. That sounds like a challenge.”|
|**Professor Oak Style**|Bot asks in a Pokémon-world tone.|Intro, learning, route choice|`Professor asks viewers to assist.`|“Oak’s research note: viewer interventions may improve AI adaptation. Or cause chaos. Both are scientifically useful.”|
|**Team Rocket Style**|Bot frames CrowdControl as mischief.|Chaos mode, challenge mode|`Ask viewers to cause chaos.`|“Team Rocket would like to remind chat that responsible sabotage is still sabotage.”|
|**AI Self-Awareness**|Bot speaks as the Pokémon AI noticing its own weakness.|Mistakes, retries, bad choices|`AI admits it needs help.`|“Confidence estimate: unstable. Chat intervention recommended before I convert this run into a cautionary tale.”|
|**Mission Support**|Bot frames viewers as mission support.|Gym prep, route planning, catching|`Ask viewers to support current mission.`|“Current mission: survive, train, and avoid embarrassing decisions. Support effects are open.”|
|**Disaster Insurance**|Bot suggests viewers can protect against disaster.|Before hard battle|`Ask viewers to prepare for risk.`|“Gym battle risk is rising. Disaster insurance is available in the form of viewer effects.”|
|**Chaos Meter Push**|Bot prompts viewers to fill or use a chaos meter.|Slow moments|`Ask viewers to raise chaos meter.`|“Chaos meter is suspiciously low. Chat has been granted permission to become a problem.”|
|**Community Vote Push**|Bot nudges viewers to collectively choose an action.|Polls, route choices|`Ask viewers to vote or redeem.`|“The next decision should not be trusted to the AI alone. Chat can vote, redeem, or watch science go wrong.”|
|**Clip-Bait Moment**|Bot tells viewers a redemption could create a clip.|Funny, tense, weird situations|`Ask viewers to trigger clip-worthy effect.`|“This is one bad decision away from a clip. Chat, you know what to do.”|
|**Subtle Hint**|Bot barely nudges interaction without sounding promotional.|Frequent use, cooldown-safe|`Lightly mention CrowdControl.`|“Viewer effects are available. The AI is pretending not to be nervous.”|
|**Direct Utility Request**|Bot explains exactly what interaction helps with.|When clarity matters|`Ask for PokéCoin effect to buy items.`|“A PokéCoin boost would let the AI stock up before the next route. Practical chaos is still chaos.”|
|**Milestone Push**|Bot ties interaction to progress milestones.|Before gym, after badge, new city|`Ask viewers to support next milestone.`|“One badge down, more bad decisions ahead. Viewer effects can shape the next leg of the run.”|
|**Failure Recovery**|Bot asks for help after a setback.|Faint, lost battle, bad catch|`Ask viewers to help recover.`|“Recovery mode active. The AI has suffered enough to become educational. Viewer support effects are open.”|
|**Gremlin Mode**|Bot uses mischievous humor.|Casual safe moments|`Ask viewers to mess with the AI.`|“The AI is getting comfortable. This is traditionally when chat becomes unbearable.”|
|**Lore-Based Request**|Bot frames interaction as part of the story.|Long-form stream identity|`Ask viewers as if they are unseen forces.`|“The unseen council may now alter the journey. Bless the AI, curse it, or fund its questionable shopping list.”|


##### Seed request structure

Each generated request should come from structured context, not a random prompt.

|Field|Purpose|Example|
|---|---|---|
|`stream_state`|Prevent bad timing|`ROUTE_TRAVEL`, `WILD_BATTLE`, `LOW_HP_DANGER`|
|`game_context`|Gives the AI situational material|`AI is near Viridian Forest with low Poké Balls`|
|`viewer_goal`|What you want viewers to do|`Trigger PokéCoin reward`|
|`tone`|Controls personality|`funny`, `dramatic`, `professor`, `rival`, `panic`, `subtle`|
|`urgency`|Controls pressure level|`low`, `medium`, `high`|
|`allowed_directness`|Prevents awkward begging|`subtle`, `clear`, `hype`, `utility`|
|`reward_name`|Specific CrowdControl action|`Add PokéCoins`, `Force Challenge`, `Heal Assist`|
|`cooldown_class`|Prevents spam|`soft_prompt`, `hard_prompt`, `emergency_prompt`|
|`recent_prompts`|Prevents repetition|Last 5 generated messages|
|`blocked_phrases`|Prevents cringe/manipulation|`please donate`, `I need money`, `pay me`|
|`max_length`|Keeps chat readable|`180 characters`|

##### Request categories for FireRed

|Category|Viewer Action|Bot Framing|Risk Level|Best Game States|
|---|---|---|---|---|
|**PokéCoin Support**|Add money/resources|“The AI needs supplies.”|Low|`SHOPPING`, `BETWEEN_OBJECTIVES`, `POST_BATTLE_SAFE`|
|**Catch Support**|Help catch Pokémon|“Chat can influence the next catch.”|Low/Medium|`WILD_BATTLE`, `CATCH_DECISION`|
|**Training Boost**|Force grinding/training goal|“Chat can push the AI to train.”|Low|`ROUTE_TRAVEL`, `BETWEEN_OBJECTIVES`|
|**Challenge Effect**|Make run harder|“Make this route less boring.”|Medium|`ROUTE_TRAVEL`, `POST_BATTLE_SAFE`|
|**Movement Chaos**|Random movement/inverted controls|“Chat can interfere with navigation.”|Medium|`ROUTE_TRAVEL` only|
|**Battle Restriction**|Limit moves/items|“Chat can impose battle rules.”|Medium/High|`WILD_BATTLE`, easy `TRAINER_BATTLE`|
|**Gym Support**|Non-disruptive assist before gym|“Prepare the AI before the test.”|Low|`BOSS_TRANSITION`, not during battle|
|**Clip Trigger**|Mark or trigger funny moment|“Make this clip-worthy.”|Low|Most safe states|
|**Lore Vote**|Name Pokémon, choose route, choose objective|“Chat shapes the story.”|Low|`INTRO`, `CATCH_DECISION`, `BETWEEN_OBJECTIVES`|
|**Recovery Help**|Help after loss/faint|“Chat can stabilize the run.”|Low|`POST_BATTLE_SAFE`, `POKEMON_CENTER`|

##### Promo-like engine design

Treat this as a sibling to the promo system.

```
Promo Engine = promotes external offersInteractive Ask Engine = promotes stream interactions
```

|Component|Promo Engine|Interactive Ask Engine|
|---|---|---|
|Goal|Drive clicks/sales/community joins|Drive CrowdControl/Channel Point interaction|
|Trigger|Win, sub, question, ending soon|Low supplies, slow chat, boss prep, safe travel|
|Output|Merch/Discord/YouTube/coaching message|AI-generated interaction request|
|Guardrail|Don’t spam offers|Don’t pressure or manipulate viewers|
|Tracking|Impressions, clicks, conversions|Impressions, redemptions, effect use, chat lift|
|Cooldowns|Global + promo-specific|Global + request-type + reward-specific|
|Personalization|Contextual offer|Game-state/persona/context-tailored ask|
|Suppression|Clutch/ranked moments|Gym battle, low HP danger, save-critical|

##### Request trigger table

|Trigger|Bot Should Ask For|Example Bot Intent|
|---|---|---|
|AI has low money|PokéCoin support|“Ask chat to help fund supplies.”|
|AI has few Poké Balls|Catch/resource support|“Ask chat to help before next route.”|
|AI reaches new route|Chaos/challenge effect|“Invite viewers to shape the route.”|
|AI catches Pokémon|Name/lore interaction|“Ask chat to participate in naming/story.”|
|AI loses battle|Recovery support|“Ask chat to stabilize the run.”|
|AI wins clutch battle|Clip/chaos/follow-up support|“Ask chat to mark or escalate moment.”|
|Chat slows down|Light interaction nudge|“Invite low-pressure participation.”|
|Before Gym|Prediction/support|“Ask chat to prepare for the boss.”|
|After Gym Badge|Celebration interaction|“Ask chat to trigger reward or next goal.”|
|Viewer asks how to interact|Direct CrowdControl explanation|“Explain available effects clearly.”|
|Stream ending soon|Next-stream setup|“Ask chat to vote next objective or join Discord.”|
|Raid received|Safe intro interaction|“Explain the AI run and safe effects.”|

##### Cooldown rules

|Prompt Type|Global Cooldown|Per-Type Cooldown|Max Per Stream|Notes|
|---|---|---|---|---|
|Subtle interaction hint|8–12 min|15 min|8|Safe as background nudge|
|Resource request|15–20 min|30 min|4|Use only when relevant|
|Emergency plea|20–30 min|45 min|3|Only when game state justifies it|
|Chaos invitation|12–15 min|25 min|5|Best in low-stakes states|
|Boss prep request|Per boss only|Per boss only|1 per boss|Don’t repeat|
|Recovery request|20 min|40 min|3|After losses or fainting|
|Direct explanation|5 min|10 min|Unlimited when user asks|Reactive, not spammy|
|Sponsor-style hard ask|30–45 min|60 min|2|Use sparingly|

##### AI generation pipeline

## Flow

```
1. Bot detects opportunity2. Build seed request3. Send seed to Hugging Face model4. Model generates 3 candidate messages5. Filter candidates6. Score candidates7. Choose best8. Send to Twitch chat or overlay9. Track whether viewers interact afterward
```

## Candidate scoring

|Score Factor|What It Rewards|
|---|---|
|Context match|Mentions current game state naturally|
|Freshness|Does not resemble recent prompts|
|Brevity|Fits Twitch chat|
|Tone match|Matches selected persona|
|Clarity|Viewers understand what they can do|
|Non-desperation|Avoids awkward begging|
|Compliance|Avoids misleading pressure|
|Timing|Matches stream state|

##### Safety/style guardrails

|Guardrail|Rule|
|---|---|
|No fake emergency|Don’t imply real-world financial need.|
|No guilt|Avoid “if you cared,” “don’t let me down,” etc.|
|No targeting vulnerable viewers|Don’t personalize based on warnings, age, health, money, or private notes.|
|No lurker callout|Don’t pressure silent viewers directly.|
|No repeated hard asks|Use hard asks rarely.|
|No deception|Make it clear interaction affects the stream/game.|
|No irreversible effects|Never promote destructive game actions.|
|No clutch distraction|Suppress during Gym/Rival/Elite/low-HP danger.|
|No creepy personalization|Use lightweight viewer history only.|
|Mod override|Mods can pause asks instantly.|

Better wording:

```
Bad:"Help, I need money. Send PokéCoins."Better:"The AI’s wallet is looking tragic. PokéCoin effects are open if chat wants to fund the next questionable shopping trip."
```


##### Persona table

|Persona|Voice|Good For|Example|
|---|---|---|---|
|**AI Bot**|Analytical, awkward, self-aware|General stream identity|“Supply forecast: poor. Viewer intervention may improve survival odds.”|
|**Professor Oak**|Researcher, observational|Pokémon theme|“For science, chat may now influence the AI’s next decision.”|
|**Rival**|Taunting, competitive|Boss prep, hype|“The rival thinks chat won’t interfere. Bold claim.”|
|**Team Rocket**|Mischievous|Chaos prompts|“A little chaos never hurt anyone. Except maybe the AI.”|
|**Narrator**|Dramatic|Clip-worthy moments|“The journey pauses. The viewers may now alter fate.”|
|**Coach**|Practical|Strategy moments|“The AI needs supplies before the next route. Smart support beats panic.”|
|**Gremlin**|Chaotic, funny|Safe downtime|“The machine is comfortable. This is unacceptable.”|
|**Announcer**|Hype, energetic|Wins, badges, milestones|“Badge secured. Chat can now decide whether the next chapter is strategy or chaos.”|


#####  Example seed-to-output table

|Seed Request|Generated Output|
|---|---|
|`Need PokéCoins. Tone: AI self-aware. State: SHOPPING.`|“The AI has reached the shop with confidence and almost no budget. PokéCoin support may prevent terrible purchasing decisions.”|
|`Ask for chaos. Tone: Team Rocket. State: ROUTE_TRAVEL.`|“Route travel detected. Team Rocket recommends making this less efficient.”|
|`Ask for help after faint. Tone: narrator. State: POST_BATTLE_SAFE.`|“The battle is over, dignity is damaged, and recovery options are open.”|
|`Ask viewers to fund Poké Balls. Tone: Professor Oak. State: BETWEEN_OBJECTIVES.`|“Research note: catching Pokémon requires Poké Balls, and the AI appears financially unserious.”|
|`Ask for challenge. Tone: rival. State: WILD_BATTLE.`|“Even the rival thinks this encounter is too easy. Chat can fix that.”|
|`Ask for clip trigger. Tone: announcer. State: POST_BATTLE_SAFE.`|“That moment had clip energy. Chat can mark it before the AI pretends it was planned.”|
|`Ask for boss prep. Tone: coach. State: BOSS_TRANSITION.`|“Gym prep window is open. Support effects now are smarter than panic later.”|
|`Ask for interaction. Tone: subtle. State: STARTING_SOON.`|“Viewer effects are open. The AI has not yet learned to fear them.”|

##### Data model addition

Add this beside your promo tables.

```
CREATE TABLE interaction_prompts (    id UUID PRIMARY KEY,    stream_session_id UUID REFERENCES stream_sessions(id),    prompt_type TEXT NOT NULL,    reward_key TEXT,    stream_state TEXT NOT NULL,    seed_payload JSONB NOT NULL,    generated_message TEXT NOT NULL,    persona TEXT,    urgency TEXT,    sent_to TEXT NOT NULL, -- CHAT, OVERLAY, TTS    created_at TIMESTAMPTZ NOT NULL DEFAULT now());CREATE TABLE interaction_prompt_results (    id UUID PRIMARY KEY,    interaction_prompt_id UUID REFERENCES interaction_prompts(id),    window_seconds INTEGER NOT NULL DEFAULT 180,    redemptions_after INTEGER NOT NULL DEFAULT 0,    chat_messages_after INTEGER NOT NULL DEFAULT 0,    unique_chatters_after INTEGER NOT NULL DEFAULT 0,    revenue_estimate NUMERIC(10,2),    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
```

##### Minimal implementation logic

```
Every 60 seconds:  check stream_state  check recent chat activity  check game context  check available rewards  check cooldownsIf opportunity exists:  create seed request  generate message with HF model  validate message  send message  log promptAfter 3 minutes:  count redemptions after prompt  count chat lift  score prompt effectiveness
```

---
# Testing (Claude's validation reference)

The prime rule, learned the hard way on the game side: **a build step is done
only when it passes on the real surface** (real Twitch chat, real game RAM),
never on mocks alone. Mocks exist to make failures cheap, not to declare
victory.

## Test tiers

| Tier | Surface | What runs | When |
|---|---|---|---|
| T0 unit | none (pytest) | parsers, cooldown math, state gating, moderation scoring, dedupe, DB upserts, all against recorded EventSub JSON fixtures | every build step |
| T1 integration | real Twitch, 6genix chat while NOT live | bot + watchdog in real chat: greetings, commands, moderation ladder, reconnect/dedupe | end of every build step that touches Twitch |
| T2 rehearsal | real Twitch + real game | stream.py + EmuHawk running a story part, bot answering from live RAM; unannounced/offline session | phase acceptance |
| T3 production | live stream | real viewers; watchdog observes only | after T2 passes |

Twitch chat works while the channel is offline, so T1 costs nothing and needs
no audience.

## The watchdog (Claude's own validator)

A second Twitch account, modded in 6genix, driven by a pytest scenario runner:

- Joins/leaves chat, sends scripted human-shaped messages (normal chatter,
  question, spam burst, caps, link post, command usage) and asserts on the
  bot's responses within a timeout.
- Exercises mod overrides (`!bot pause`, `!strict on`) and asserts the bot
  obeys, including the kill switch every single run.
- "First-time chatter" is simulated by resetting the watchdog's row in the
  viewer DB (test-only flag), not by creating new Twitch accounts.
- All watchdog traffic is tagged **synthetic** (twitch_user_id allowlist) and
  excluded from analytics, greeting stats, and viewer memory.
- Every T1/T2 run writes a transcript to `runs/bot/` for review; guardrail
  violations (blocked phrases, wrong-state asks, double-greeting) fail the run.

## Prerequisites and who obtains them

| # | Prerequisite | Owner | Notes |
|---|---|---|---|
| K1 | Bot Twitch account (name set later via the bot tab) | **Kameron** | needs an email + login |
| K2 | Watchdog Twitch account | **Kameron** | any name; will be modded |
| K3 | Twitch dev-console app (client id/secret) | **Kameron logs in, Claude drives** | dev.twitch.tv, one app covers all |
| K4 | OAuth consent for broadcaster (6genix), bot, watchdog | **Kameron clicks, Claude runs the flow** | device-code flow; refresh is code-side |
| K5 | Mod status for bot + watchdog in 6genix | **Kameron** | `/mod <botname>`, `/mod <watchdog>` |
| K6 | Affiliate status confirmation on 6genix | **Kameron** | GATES Channel Points, polls, predictions (B1/B2 features); chat, commands, and clips do not need it |
| K7 | `HF_TOKEN` env var (Interaction Request Engine, B3) | **Kameron** | never stored in the repo |
| K8 | CrowdControl account + BizHawk pack (B4 only) | **Kameron** | manual Lua load workflow already known |
| C1 | Secrets file (`bot/.env`, gitignored), token refresh, EventSub fixtures, watchdog runner, SQLite store | **Claude** | everything code-side |

Until K1-K5 exist, work proceeds at T0 only. That is fine for scaffolding, but
no phase may be declared done at T0.

---
# Promo system

## Promo types

|Promo|Trigger|
|---|---|
|Discord|After community interaction, raid, returning chatter cluster|
|YouTube|After clip-worthy moment, ending soon, post-win|
|Merch|After hype moment, sub milestone, viewer asks|
|Coaching|After skill question, clutch, loadout/settings discussion|
|Sponsor|During sponsor segment only|
|Setup|When viewer asks about gear/settings|
## Cooldown defaults

```
Global promo cooldown: 20 to 30 minutesSame promo cooldown: 45 to 60 minutesPer-stream max per promo: 2 to 3No promo during ranked/clutch/battle statesNo promo if chat velocity is already high
```

## UTM format

```
https://example.com/offer?utm_source=twitch&utm_medium=chatbot&utm_campaign={stream_session_id}&utm_content={promo_key}
```

Store every promo impression. Later, compare:

```
promo impressionschat reactionclickssubs/membershipsDiscord joinsmerch/coaching conversions
```

---

# Analytics summary

Post-stream report should include:

```
Stream basics- duration- game/category- peak chat velocity- active chatters- first-time chatters- returning chattersEngagement- total messages- messages per minute- command usage- poll participation- prediction participation- Channel Point redemptionsModeration- warnings- deletes- timeouts- bans- flagged users- raid strict-mode eventsRevenue/promos- promo impressions- promo types used- link clicks if tracked- subs/cheers if available- conversion notesContent- top clip candidates- timestamp- reason- suggested title- suggested YouTube Short/TikTok captionViewer memory- top engaged viewers- returning streaks- frequent redeemers- users needing mod review
```

---

# Mod dashboard layout

## Dashboard sections

```
Top bar- stream state- bot status- strict mode- promo mode- chaos meter- queue statusLeft panel- live chat flags- suspicious users- recent moderation actionsCenter panel- redemption/effect queue- approve/reject- priority- refund-needed markerRight panel- polls/predictions- Q&A queue- giveaway controls- promo triggersBottom panel- clip markers- analytics counters- event log
```

# Implementation plan

Bot-side only; the storyline/AI build runs in parallel and each bot phase is
pinned to the story part that makes it meaningful. Game-side prerequisites are
named per phase and tracked in `docs/ROADMAP.md` (the loop-engineering runbook:
check goal, check tasks, build, validate through testing, update tasks, update
goal, repeat). One real-surface acceptance test gates each phase; no phase is
"done" from T0/mocks.

## Phase map (bot <-> storyline sync)

| Phase | Bot deliverable | Storyline sync point | Acceptance (real surface) |
|---|---|---|---|
| B0 | Read-only companion | Part 1 is streamable today; B0 needs no new game features beyond `/api/context` | T1: watchdog session in offline 6genix chat passes the greeting/commands/moderation/dedupe script. T2: `!party` answers with the live RAM party during a Part 1 run |
| B1 | State-aware interaction: polls, naming, Q&A, clips, bot tab | Part 2 lands ROUTE_TRAVEL / CENTER / SHOPPING states; naming ties to the intro naming screens | T2: during a Part 2 rehearsal, state flips (grass to WILD_BATTLE) gate behavior correctly; chat poll names the rival before the naming screen; `!clip` produces a real clip |
| B2 | Game-effect queue, Low tier first | Catching + optional-quest system exist game-side (Viridian Forest era) | T2: "attempt catch next encounter" redemption queues, executes in a real wild battle, marks EXECUTED; the same redemption during RIVAL_BATTLE is refused and refund-marked |
| B3 | Interaction Request Engine | Brock arc (BOSS_TRANSITION; predictions get stakes) | T2: a full rehearsal yields 5+ asks, every ask matches the actual game state at send time, zero guardrail violations in the transcript review |
| B4 | Chaos: CrowdControl, chaos meter, Medium tier | Post-Brock route play; pairs with the game-side DisruptionMonitor | T2: a CrowdControl test effect fires in ROUTE_TRAVEL, is blocked in GYM_BATTLE, and the AI visibly reacts (thought line on the viewer board) |
| B5 | Analytics, promo engine, clip ranking | Any time after B1 | T3: post-stream report generated from a real stream with correct counts |

## B0 - Read-only companion (start immediately)

Build order:
1. `bot/` package skeleton, SQLite store, `.env` secrets, config loader.
2. OAuth device flow + token refresh (broadcaster + bot accounts). [needs K1-K4]
3. EventSub WebSocket client: subscribe `channel.chat.message`,
   `stream.online/offline`; reconnect; event-id dedupe. (T0 fixtures first.)
4. Chat sender: queue + rate cooldown.
5. Viewer DB + first-time/returning greeting (active interaction only, never
   passive presence).
6. Command system: `!rules !lurk !uptime !discord !youtube !clip` (marker only)
   plus the Pokémon read-onlys `!party !badges !route !ai !next`, served from
   `GET /api/context` (small game-side task: expose the snapshot stream.py
   already holds).
7. Moderation v1 ladder + `!bot pause/resume`, `!strict on/off` (the kill
   switch lives here and is re-verified in every later phase).
8. Analytics counters (messages, chatters, commands) + end-of-session summary.

Explicitly deferred from B0: polls/predictions (affiliate + B1), anything that
changes gameplay (B2), HF generation (B3).

## B1 - State-aware interaction

1. Game-side: stream_state classifier v1 in stream.py (emit the detectable
   subset; nearest-safer-ancestor rule for unknowns) + state in `/api/context`.
2. State-gating engine generated from this doc's State Rules matrix (single
   source of truth, one table in code).
3. Poll + prediction managers (needs K6 affiliate) + `!poll` / `!predict`.
4. Naming flow: operator panel text input (defaults Ash/Gary per the
   walkthrough feature notes) + viewer poll when live; the winner lands in the
   operator field the intro runner reads.
5. Q&A queue, chat-spike detector, clip marker wired to the Create Clip API.
6. Operator panel bot tab (name/greeting/toggles/health).

## B2 - Game-effect queue (Low tier)

1. Effect catalog (risk/cooldown/cost/allowed_states) seeded from this doc;
   chaos_cost present but the chaos meter stays dormant until B4.
2. Effect queue: QUEUED > APPROVED > EXECUTED / FAILED / REJECTED (+ refund
   mark); operator approve/reject in the bot tab.
3. Game-side: `POST /api/directive` whitelist v1: `show_party`,
   `catch_next_encounter`, `nickname_next_catch`, `enqueue_quest(route22)`,
   `explain_plan`, `set_nuzlocke(<rule>|random|clear)`. The agent consumes
   directives at safe points only.
4. Channel Point rewards mapped to catalog entries. [needs K6]
5. `!questlist` / `!quest` backed by the optional-quest queue.
6. `!nuzlocke*` backed by the viewer-driven Nuzlocke ruleset (SSOT
   `src/pokeai/rules/nuzlocke.py`, catalog served at `GET /api/nuzlocke`,
   `set_nuzlocke` directive, tracker on the NUZLOCKE board section).

## B3 - Interaction Request Engine

1. Opportunity detector (the 60-second loop over context, chat velocity, and
   the cooldown ledger).
2. Seed builder (state, game_context, tone, urgency, directness, blocked
   phrases, recent-5 history).
3. HF generation (3 candidates) > guardrail filter > scorer > send. [needs K7]
4. `interaction_prompts` + `interaction_prompt_results` with the 3-minute lift
   window.
5. Personas and per-type cooldown budgets enforced exactly as tabled above.

## B4 - Chaos and CrowdControl

1. CrowdControl session with the BizHawk pack (manual Lua load workflow).
   [needs K8]
2. Chaos meter (budget, decay, per-effect cost) + Medium-tier effects.
3. Safe-mode auto-gating from stream_state (STATUS_DANGER etc. exist by then).
4. PokéCoin economy live: CrowdControl coins + Channel Points feeding the
   support-credit ledger.

## B5 - Analytics and polish

Post-stream report, clip-candidate ranking, promo engine with UTM tracking,
viewer-memory surfaces. Then re-evaluate the P3 productization list; it stays
parked until the single-channel bot has run real streams.

## Standing rules for every phase

- The kill switches (`!bot pause`, operator Pause toggle) are built in B0 and
  re-verified in every phase's acceptance run.
- Every phase adds its EventSub types behind the same dedupe layer.
- Any feature blocked on a Kameron prerequisite (K1-K8) is parked visibly in
  ROADMAP.md, never mocked into a fake "done".
- The bot never talks to the emulator; only to stream.py. If a feature seems
  to need direct emulator access, the design is wrong or it belongs to
  CrowdControl.