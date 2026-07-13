"""The three game-playing brains, built on the shared GameSense foundation.

Unlike a from-scratch learner, each of these is born already knowing how to be
*in* the game — it reads the screen, knows A accepts and B backs out, knows a
wall must be walked around and a person can be talked to, remembers a map of
where it has been, and pathfinds toward a goal. They differ in temperament:

  - Planner   — methodical explorer/navigator: maps the world and routes toward
                the way onward. Best at *getting somewhere*.
  - Tactician — fighter: seeks out battles and wins them on type matchups.
  - Learner   — adapts: starts with the same instincts but tunes them from what
                actually works this run, and tells you what it figured out.

Each exposes a small capability profile (plain skills, e.g. Navigation /
Planning / Battling) that the dashboard renders as bars, plus a live Goal and
Plan, so viewers can see what it is trying to do and why.
"""
from __future__ import annotations

import numpy as np

from pokeai.agents.base import Agent
from pokeai.agents.battle_brain import BattleBrain
from pokeai.agents.brain.gamesense import GameSense
from pokeai.agents.brain.needs import Decision, NeedsArbiter
from pokeai.emulator.screen_reader import ScreenContext, TileClass
from pokeai.env.action_controller import Action
from pokeai.knowledge.game_data import MAP_NAMES, map_name
from pokeai.knowledge.llm_advisor import LLMAdvisor
from pokeai.knowledge.roots import load_roots

# Reverse of the map-name table, so a roots town name ("Viridian City") can be
# turned into the live map id the agent navigates by.
_NAME_TO_MAP: dict[str, int] = {name.lower(): mid for mid, name in MAP_NAMES.items()}


def _is_center_map(map_id: int) -> bool:
    return "center" in map_name(map_id).lower()  # e.g. "Viridian Pokecenter"


def _is_mart_map(map_id: int) -> bool:
    return "mart" in map_name(map_id).lower()

# Screen cells one step ahead in each direction (player is the centre block).
_FACING = {
    Action.UP: [(7, 8), (7, 9)],
    Action.DOWN: [(10, 8), (10, 9)],
    Action.LEFT: [(8, 7), (9, 7)],
    Action.RIGHT: [(8, 10), (9, 10)],
}


class BrainAgent(Agent):
    """Shared body: perception -> intro/dialogue/battle/navigation, with a Goal,
    a Plan, and a capability profile for the dashboard. Subclasses set their
    name + capabilities and tweak a couple of behaviour hooks."""

    name = "brain"
    display_name = "Brain"
    # Plain-language capability profile (0..1). No external taxonomy branding.
    capabilities: dict[str, float] = {
        "Navigation": 0.7,
        "Planning": 0.7,
        "Battling": 0.6,
        "Curiosity": 0.7,
        "Memory": 0.7,
        "Adaptation": 0.5,
    }
    # Weaken a wild target to about this HP fraction before throwing a ball
    # (lower HP = much better catch odds); a status condition also qualifies.
    CATCH_HP_FRAC = 0.35

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.env = None
        self.brain: BattleBrain | None = None
        self.sense = GameSense(seed=seed)
        # A short queued interaction (face a person/object, then press A) so the
        # agent can talk to people and grab the starter from Oak's table. Which
        # tiles we've already handled lives in GameSense (single source of truth,
        # shared with the explorer's NPC routing).
        self._interact_queue: list[int] = []
        # Catching. Any brain can opportunistically catch a *new* wild species
        # once it's weak enough — the dashboard flips auto_catch on so catching
        # happens by itself in battle, whatever strategy is playing. The Catcher
        # sets _always_catch so it catches regardless of the dashboard toggle.
        self.auto_catch = False
        self._always_catch = False
        self._caught: set[int] = set()   # enemy species we already added to the team
        self._last_party = 0
        self._target_species = 0
        # Dashboard-facing state.
        self.goal_text = "Get my bearings"
        self.plan_text = ""
        self.active_capability = "Navigation"

    # --- wiring ---

    def attach_env(self, env) -> None:
        self.env = env
        self.brain = BattleBrain(env.state_reader)

    def reset(self) -> None:
        # Per-episode: keep the remembered world (sense.reset() preserves it) so
        # we don't re-explore from scratch every episode.
        self.sense.reset()
        self._interact_queue.clear()
        self._last_party = 0
        self._target_species = 0
        self.goal_text = "Get my bearings"
        self.plan_text = ""
        if self.brain is not None:
            self.brain.reset()

    def full_reset(self) -> None:
        """Forget everything (periodic full reset / new playthrough)."""
        self.sense.full_reset()
        self._interact_queue.clear()
        self._caught.clear()
        self._last_party = 0
        self._target_species = 0
        self.goal_text = "Get my bearings"
        self.plan_text = ""
        if self.brain is not None:
            self.brain.reset()

    # --- decision ---

    def act(self, observation: np.ndarray) -> int:
        if self.env is None or self.brain is None:
            return self._act_blind(observation)

        state = self.env.state_reader.read()
        view = self.env.screen_reader.view(in_battle=state.battle_type != 0)
        self._note_catches(state)
        self._update_goal(state)

        # Battle: hand off to the type-aware BattleBrain.
        if view.context == ScreenContext.BATTLE or state.battle_type != 0:
            self.active_capability = "Battling"
            self._configure_battle(state)
            action = self.brain.decide()
            self.plan_text = "winning this battle"
            self.thought = self._battle_thought(self.brain.thought)
            self.sense.note_action(state, action)
            return action

        # Opening sequence (no Pokemon yet): advance any text/menu with A; only
        # navigate on a clean free-roam screen (where we truly have control).
        if state.party_count == 0:
            naming = self._handle_naming(state, view)
            if naming is not None:
                return naming
            if self._is_intro(state) or view.has_text or view.context != ScreenContext.FREE_ROAM:
                self.active_capability = "Reading"
                self.plan_text = "playing through the intro"
                self.thought = "Starting a new game — pressing A through the intro"
                self.sense.note_action(state, int(Action.A))
                return int(Action.A)
            return self._navigate(state)

        # A message / dialogue is up — read it and continue.
        if view.context == ScreenContext.DIALOGUE:
            self.active_capability = "Reading"
            self.plan_text = "reading what's on screen"
            self.thought = f'Reading: "{view.dialogue[:38]}" — pressing A'
            self.sense.note_action(state, int(Action.A))
            return int(Action.A)

        # A menu is open in the overworld — back out to keep moving.
        if view.context == ScreenContext.MENU:
            self.active_capability = "Reading"
            self.plan_text = "closing this menu"
            opt = view.cursor_option or "menu"
            self.thought = f'Menu open (on "{opt}") — backing out with B'
            self.sense.note_action(state, int(Action.B))
            return int(Action.B)

        # Free roam: navigate with the world model.
        return self._navigate(state)

    def _navigate(self, state) -> int:
        sem = self.env.screen_reader.semantic_tiles()
        self.sense.perceive(state, sem)

        # Affordance: a person/object right next to us can be interacted with.
        # Walk up to face it and press A — this reads NPCs and, in Oak's lab,
        # grabs the starter Pokemon. We do this (a) before we have a Pokémon, and
        # (b) when the explorer has run out of ground and is hunting for the
        # event that unblocks progress — but not during ordinary exploration, so
        # we don't pester every NPC we pass.
        want_interact = state.party_count == 0 or self.sense.seeking_event
        if not self._interact_queue and want_interact:
            npc_dir = self._adjacent_npc(state, sem)
            if npc_dir is not None:
                self._interact_queue = [int(npc_dir), int(Action.A), int(Action.A)]
        if self._interact_queue:
            a = self._interact_queue.pop(0)
            self.active_capability = "Reading"
            self.thought = "Walking up to see what this is — pressing A"
            self.sense.note_action(state, a)
            return a

        action = self._overworld_action(state, sem)
        a = int(action) if action is not None else int(Action.A)
        self.sense.note_action(state, a)
        self.plan_text = self.sense.last_intent
        return a

    # --- hooks subclasses can override ---

    def _overworld_action(self, state, sem) -> Action | None:
        """Default overworld policy: systematic GameSense exploration."""
        self.active_capability = "Curiosity" if "map" in self.sense.last_intent else "Planning"
        action = self.sense.explore_action(state)
        self.thought = f"Exploring {map_name(state.current_map)} — {self.sense.last_intent}"
        return action

    def _battle_thought(self, brain_thought: str) -> str:
        return brain_thought

    def _configure_battle(self, state) -> None:
        """Set up the BattleBrain for this battle step: decide whether to try for
        a capture. Catching happens when it's switched on (the dashboard's
        auto-catch, or the Catcher which always does) and it's worth it — a wild
        battle, a species we don't already have, a ball in the bag, and the
        target already weak (low HP or statused). Otherwise we just fight."""
        if not (self.auto_catch or self._always_catch):
            self.brain.want_catch = False
            return
        b = self.env.state_reader.read_battle()
        self._target_species = b.enemy_species
        want = False
        if (
            b.in_battle == 1  # wild only (can't catch a trainer's Pokémon)
            and b.enemy_species
            and b.enemy_species not in self._caught
            and self.brain.has_ball()
        ):
            want = b.enemy_hp_frac <= self.CATCH_HP_FRAC or b.enemy_status != 0
        self.brain.want_catch = want

    def _note_catches(self, state) -> None:
        """A new party member since last step means our last throw stuck — record
        the species so we don't keep re-catching it."""
        if state.party_count > self._last_party and self._target_species:
            self._caught.add(self._target_species)
            self._target_species = 0
        self._last_party = state.party_count

    # --- goal manager (shared) ---

    def _update_goal(self, state) -> None:
        if state.party_count == 0:
            self.goal_text = "Get my first Pokémon from Prof. Oak"
        elif state.badge_count == 0:
            self.goal_text = "Reach Pewter City and win the first Gym Badge"
        elif state.badge_count >= 8:
            self.goal_text = "Head for the Pokémon League"
        else:
            self.goal_text = f"Earn Gym Badge #{state.badge_count + 1}"

    # --- helpers ---

    def _handle_naming(self, state, view) -> int | None:
        """The intro's name-entry screen shows a preset menu (NEW NAME / RED /
        ASH / JACK). Pressing A on the default (NEW NAME) drops into a fiddly
        letter keyboard the agent can't finish; instead we move the cursor onto
        a preset and pick it, skipping the keyboard. Returns an action while that
        menu is up, else None."""
        if "NEW NAME" not in view.text.upper():
            return None
        cursor = (view.cursor_option or "").upper()
        if cursor in ("", "NEW NAME") or "NEW NAME" in cursor:
            self.active_capability = "Reading"
            self.thought = "Name screen — moving to a ready-made name"
            self.sense.note_action(state, int(Action.DOWN))
            return int(Action.DOWN)
        self.thought = f'Name screen — choosing "{view.cursor_option}"'
        self.sense.note_action(state, int(Action.A))
        return int(Action.A)

    def _is_intro(self, state) -> bool:
        return (
            state.current_map == 0
            and state.x_pos == 0
            and state.y_pos == 0
            and state.party_count == 0
        )

    def _adjacent_npc(self, state, sem) -> Action | None:
        """Direction of an adjacent person/object we haven't interacted with
        yet, or None. Used to walk up and talk to it / grab the starter. Records
        the handled tile in GameSense so both the queue and the explorer's NPC
        routing agree on who's already been spoken to."""
        for action, cells in _FACING.items():
            if not any(
                int(sem[r, c]) == int(TileClass.NPC)
                for r, c in cells
                if 0 <= r < sem.shape[0] and 0 <= c < sem.shape[1]
            ):
                continue
            dx, dy = {Action.UP: (0, -1), Action.DOWN: (0, 1),
                      Action.LEFT: (-1, 0), Action.RIGHT: (1, 0)}[action]
            tx, ty = state.x_pos + dx, state.y_pos + dy
            if (tx, ty) in self.sense._interacted_on(state.current_map):
                continue
            self.sense.mark_interacted(state.current_map, tx, ty)
            return action
        return None

    def _facing_grass(self, sem, action: Action) -> bool:
        return any(
            int(sem[r, c]) == int(TileClass.GRASS)
            for r, c in _FACING[action]
            if 0 <= r < sem.shape[0] and 0 <= c < sem.shape[1]
        )

    def _act_blind(self, observation: np.ndarray) -> int:
        from pokeai.env.pokemon_red_env import OBS_FIELDS

        if int(observation[OBS_FIELDS.index("battle_type")]) != 0:
            self.thought = "In battle (no screen access) — pressing A"
            return int(Action.A)
        action = Action(int(self.rng.choice([int(Action.UP), int(Action.DOWN),
                                             int(Action.LEFT), int(Action.RIGHT)])))
        self.thought = f"Wandering {action.name} (no screen access)"
        return int(action)


class PlannerAgent(BrainAgent):
    """Methodical explorer/navigator. Maps the world and routes toward the way
    onward; avoids dawdling in grass."""

    name = "planner"
    display_name = "Planner"
    capabilities = {
        "Navigation": 0.95,
        "Planning": 0.9,
        "Memory": 0.85,
        "Curiosity": 0.6,
        "Battling": 0.5,
        "Adaptation": 0.4,
    }


class BattleTacticianAgent(BrainAgent):
    """Fighter. Explores like the others, but when healthy it steps into grass
    to pick fights, and it leans on the type-aware BattleBrain to win them."""

    name = "tactician"
    display_name = "Battle Tactician"
    capabilities = {
        "Battling": 0.95,
        "Navigation": 0.7,
        "Planning": 0.6,
        "Curiosity": 0.75,
        "Memory": 0.6,
        "Adaptation": 0.5,
    }
    # Only seek battles while reasonably healthy.
    HEALTHY_HP_FRAC = 0.5

    def _overworld_action(self, state, sem) -> Action | None:
        healthy = (
            state.party_total_max_hp == 0
            or state.party_total_hp / max(state.party_total_max_hp, 1) >= self.HEALTHY_HP_FRAC
        )
        if healthy:
            for action in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
                if self._facing_grass(sem, action):
                    self.active_capability = "Battling"
                    self.thought = f"Tall grass {action.name} — stepping in to find a battle"
                    self.sense.last_intent = "hunting for a wild battle"
                    return action
        return super()._overworld_action(state, sem)

    def _battle_thought(self, brain_thought: str) -> str:
        return f"⚔ {brain_thought}"


class LearnerAgent(BrainAgent):
    """Adapts. Same instincts as the others, but it keeps a tally of what works
    this run (which directions keep getting blocked, how battles go) and tells
    you the lessons it has drawn."""

    name = "learner"
    display_name = "Learner"
    capabilities = {
        "Adaptation": 0.95,
        "Curiosity": 0.9,
        "Memory": 0.8,
        "Navigation": 0.7,
        "Planning": 0.6,
        "Battling": 0.6,
    }

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        self.lessons: list[str] = []
        self._wins = 0

    def reset(self) -> None:
        super().reset()
        self.lessons = []
        self._wins = 0

    def _overworld_action(self, state, sem) -> Action | None:
        # Note progress lessons as the map knowledge grows.
        known = self.sense.known_tiles(state.current_map)
        if known and known % 25 == 0:
            self._learn(f"Mapped {known} tiles of {map_name(state.current_map)}")
        self.active_capability = "Adaptation"
        action = self.sense.explore_action(state)
        self.thought = f"Learning {map_name(state.current_map)} — {self.sense.last_intent}"
        return action

    def _battle_thought(self, brain_thought: str) -> str:
        self._learn("Type matchups decide battles — picking super-effective moves")
        return brain_thought

    def _learn(self, lesson: str) -> None:
        if lesson not in self.lessons:
            self.lessons.append(lesson)
            self.lessons = self.lessons[-6:]  # keep the most recent half-dozen


class CatcherAgent(BrainAgent):
    """Collector. Hunts tall grass for wild Pokémon, weakens a new species with
    type-smart moves, then throws a ball to add it to the team — the way a human
    builds a roster instead of only fighting."""

    name = "catcher"
    display_name = "Catcher"
    capabilities = {
        "Catching": 0.95,
        "Curiosity": 0.85,
        "Battling": 0.7,
        "Navigation": 0.7,
        "Memory": 0.7,
        "Planning": 0.5,
    }
    # Only wade into grass to hunt when reasonably healthy.
    HEALTHY_HP_FRAC = 0.4

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        # The Catcher always tries to catch; the shared base handles the policy,
        # ball selection, and caught-species tracking.
        self._always_catch = True

    def _battle_thought(self, brain_thought: str) -> str:
        return f"🎯 {brain_thought}"

    def _overworld_action(self, state, sem) -> Action | None:
        healthy = (
            state.party_total_max_hp == 0
            or state.party_total_hp / max(state.party_total_max_hp, 1) >= self.HEALTHY_HP_FRAC
        )
        if healthy:
            for action in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
                if self._facing_grass(sem, action):
                    self.active_capability = "Catching"
                    self.thought = f"Tall grass {action.name} — looking for a Pokémon to catch"
                    self.sense.last_intent = "hunting for a wild Pokémon to catch"
                    return action
        return super()._overworld_action(state, sem)


class AdventurerAgent(BrainAgent):
    """Goal-directed player. A Needs/Goal arbiter (driven by docs/AGENT_ROOTS.md)
    decides what it should be doing — survive, make progress, prepare, grow, or
    explore — and dispatches to the right behaviour, narrating its reasoning so
    you can watch it think. It's the closest thing here to playing like a person.

    Executors land in increments. Working now: explore, retreat-to-a-Pokémon-
    Center to heal, and train/catch. Stubbed (correct intent + best-effort
    navigation, full automation still to come): shopping and running story-gate
    errands."""

    name = "adventurer"
    display_name = "Adventurer"
    capabilities = {
        "Decision-making": 0.9,
        "Navigation": 0.85,
        "Planning": 0.85,
        "Battling": 0.7,
        "Memory": 0.8,
        "Curiosity": 0.7,
    }
    HEALTHY_HP_FRAC = 0.5
    # Steps without any new event / badge / map before we decide we're stalled and
    # switch from exploring/training to actively working out what's blocking us.
    STALL_LIMIT = 120
    # Steps with no new *story* progress (event flag / badge) before we decide
    # we're spinning the overworld and should commit to figuring out the next
    # story step (consult the strategist) — even if we're still finding new tiles.
    STORY_STALL_LIMIT = 280

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        self.roots = load_roots()
        self.arbiter = NeedsArbiter(self.roots)
        self.advisor = LLMAdvisor()  # disabled unless HF_TOKEN is set
        # Startup confirmation so you can see the token was picked up.
        if self.advisor.available:
            print(f"[adventurer] LLM strategist ENABLED (model={self.advisor.model}); "
                  "consulted when stuck at a gate.")
        else:
            print("[adventurer] LLM strategist disabled (HF_TOKEN not set) — "
                  "using built-in judgement only.")
        self._decision = Decision("explore", "explore", "Getting my bearings.")
        self._stall_steps = 0
        self._story_stall_steps = 0
        self._last_progress_sig: tuple | None = None
        self._last_story_sig: tuple | None = None
        self._llm_target: int | None = None   # a map the strategist told us to go to
        # Dashboard-facing "thinking" state (drives the in-game animation).
        self.thinking = False
        self.think_elapsed = 0.0
        self.think_estimate = 0.0
        self.think_reason = ""

    def reset(self) -> None:
        super().reset()
        self._stall_steps = 0
        self._story_stall_steps = 0
        self._last_progress_sig = None
        self._last_story_sig = None
        self._llm_target = None
        self.thinking = False

    # The arbiter runs every step to set the strategic goal + the dashboard's
    # rationale; the base class then handles battle/dialogue and calls our
    # _overworld_action to execute the chosen goal.
    def act(self, observation):
        if self.env is not None:
            self._consume_advice()
            # While the strategist is thinking, stand still so the dashboard can
            # show the thinking animation (the call runs on a background thread).
            if self.advisor.pending and not self.advisor.expired():
                self.thinking = True
                self.think_elapsed = self.advisor.elapsed
                self.think_estimate = self.advisor.estimate
                self.thought = "Thinking… asking the strategist what to do"
                return int(Action.NOOP)
            self.thinking = False
            state = self.env.state_reader.read()
            self._update_stall(state)
            self._decision = self.arbiter.decide(self._context(state))
            # Only chase wild Pokémon when the goal is to grow the team.
            self.auto_catch = self._decision.goal == "train_or_catch"
            self._maybe_ask_advisor(state)
        return super().act(observation)

    # --- LLM advisor (consulted only when stuck) ---

    def _maybe_ask_advisor(self, state) -> None:
        if not self.advisor.available or self.advisor.pending:
            return
        if self._decision.goal != "unblock_gate" or self._llm_target is not None:
            return  # only ask when stuck, and not while already following advice
        self.advisor.request(self._situation_summary(state), self._place_options(state))

    def _consume_advice(self) -> None:
        suggestion = self.advisor.take_result()
        if not suggestion:
            return
        self.think_reason = suggestion.get("reason", "")
        target = suggestion.get("target", "")
        tid = _NAME_TO_MAP.get(target.strip().lower()) if target else None
        if tid is not None and suggestion.get("goal") in ("go_to", "shop", "heal", "explore"):
            self._llm_target = tid

    def _situation_summary(self, state) -> str:
        gym = self.roots.next_gym(state.badge_count)
        gate = self._current_gate(state)
        hp = int(100 * state.party_total_hp / max(state.party_total_max_hp, 1))
        lines = [
            f"Location: {map_name(state.current_map)}.",
            f"Badges: {state.badge_count}/8. Party HP: {hp}%.",
        ]
        if gym:
            lines.append(f"Next gym: {gym.leader} at {gym.town} ({gym.type}).")
        if gate:
            lines.append(f"Blocked by: {gate.blocker} ({gate.where}). Likely fix: {gate.unlock}.")
        lines.append("I've explored everywhere I can walk and spoken to everyone reachable, "
                     "but I can't find the way forward.")
        return "\n".join(lines)

    def _place_options(self, state) -> list[str]:
        names = {map_name(m) for m in self.sense._visited_maps}
        names.update(t.name for t in self.roots.towns)
        names.discard(map_name(state.current_map))
        return sorted(names)

    def _current_gate(self, state):
        cur = map_name(state.current_map).lower()
        for gate in self.roots.gates:
            if cur and cur.split()[0] in gate.where.lower():
                return gate
        return None

    def _update_stall(self, state) -> None:
        # "Progress" = a new event flag, a new badge, or newly-discovered ground.
        # Counting *known tiles* (not just new maps) means actively exploring a
        # room keeps the stall timer at zero — we only flip to "figure out the
        # blocker" when genuinely not discovering anything new (truly stuck).
        known_tiles = sum(self.sense.world.known_count(m) for m in self.sense.world.maps)
        sig = (state.event_flags_set, state.badge_count, known_tiles)
        if sig != self._last_progress_sig:
            self._last_progress_sig = sig
            self._stall_steps = 0
        else:
            self._stall_steps += 1
        # Story stall: tiles don't count — only events/badges. Wandering the
        # overworld forever without advancing the story should still send us to
        # the strategist to work out the next step.
        story_sig = (state.event_flags_set, state.badge_count)
        if story_sig != self._last_story_sig:
            self._last_story_sig = story_sig
            self._story_stall_steps = 0
        else:
            self._story_stall_steps += 1

    def _update_goal(self, state) -> None:
        # The GOAL line shows the arbiter's current call + reasoning, so the
        # dashboard literally displays what the agent has decided to do and why.
        self.goal_text = self._decision.rationale

    def _overworld_action(self, state, sem) -> Action | None:
        goal = self._decision.goal
        self.plan_text = self._decision.rationale
        if goal == "heal":
            return self._go_heal(state, sem)
        if goal == "train_or_catch":
            return self._go_train(state, sem)
        if goal == "shop":
            return self._go_toward_service(state, mart=True) or super()._overworld_action(state, sem)
        if goal == "unblock_gate":
            return self._go_unblock(state, sem)
        return super()._overworld_action(state, sem)  # explore

    # --- context the arbiter scores ---

    def _context(self, state) -> dict:
        max_hp = max(state.party_total_max_hp, 1)
        party = self.env.state_reader.read_party_details()
        top_level = max((p.level for p in party), default=0)
        gym = self.roots.next_gym(state.badge_count)
        cur_name = map_name(state.current_map)
        return {
            "party_hp_fraction": state.party_total_hp / max_hp,
            # Stuck = mapped out everywhere reachable, OR no progress for a while
            # (grinding/wall-bumping), OR the story hasn't advanced in ages (still
            # wandering) — any of these should flip us into figuring out the gate.
            "exploration_exhausted": (
                bool(self.sense.idle)
                or self._stall_steps >= self.STALL_LIMIT
                or self._story_stall_steps >= self.STORY_STALL_LIMIT
            ),
            "at_gym_town": bool(gym and gym.town.lower() == cur_name.lower()),
            "next_gym_unbeaten": gym is not None,
            "money": state.money,
            "healing_items": self.env.state_reader.count_heal_items(),
            "mart_known": self._mart_known(state),
            "party_top_level": top_level,
            "next_gym_recommended_level": gym.recommended_level if gym else 0,
            "always": True,
        }

    def _mart_known(self, state) -> bool:
        for m in self.sense._visited_maps | {state.current_map}:
            if _is_mart_map(m):
                return True
        town = self.roots.town(map_name(state.current_map))
        return bool(town and town.has_mart)

    # --- executors ---

    def _go_heal(self, state, sem) -> Action | None:
        self.active_capability = "Decision-making"
        m = state.current_map
        if _is_center_map(m):
            if state.party_total_max_hp > 0 and state.party_total_hp >= state.party_total_max_hp:
                self.thought = "All healed up — heading back out."
                exit_path = self.sense.world.path_to_warp(m, state.x_pos, state.y_pos)
                if exit_path:
                    return int(exit_path[0])
                return super()._overworld_action(state, sem)
            self.thought = "At the Pokémon Center — talking to the nurse to heal."
            return self._talk_to_nearest_person(state, sem)
        # Not in a Center: walk toward the nearest one we know.
        for center in sorted(c for c in (self.sense._visited_maps | {m}) if _is_center_map(c)):
            step = self.sense.route_toward_map(m, state.x_pos, state.y_pos, center)
            if step is not None:
                self.thought = f"Hurt — making for the {map_name(center)} to heal."
                return int(step)
        # None known yet: head for a town the roots say has one, else explore to find it.
        step = self._go_toward_service(state, center=True)
        if step is not None:
            self.thought = "Hurt — heading for a town with a Pokémon Center."
            return int(step)
        self.thought = "Hurt, but no Center found yet — exploring to find one."
        return super()._overworld_action(state, sem)

    def _go_train(self, state, sem) -> Action | None:
        """Train by ADVANCING through the world — wild battles happen naturally as
        we cross grass, and trainers along the way give the real XP — rather than
        camping one grass patch forever (which never makes progress). auto_catch
        is on (set in act) so we also grab new species we meet. We only stop to
        deliberately farm grass once there's no new ground left to discover."""
        self.active_capability = "Battling"
        healthy = (
            state.party_total_max_hp == 0
            or state.party_total_hp / max(state.party_total_max_hp, 1) >= self.HEALTHY_HP_FRAC
        )
        # Out of new ground but still under-levelled: now it's worth farming grass.
        if self.sense.idle and healthy:
            for action in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
                if self._facing_grass(sem, action):
                    self.thought = f"Grinding levels — into the grass {action.name}."
                    self.sense.last_intent = "training for the next gym"
                    return action
        return super()._overworld_action(state, sem)  # advance, fighting what we meet

    def _go_unblock(self, state, sem) -> Action | None:
        """Work out and run whatever opens the way on. Story progress in this game
        is almost always 'talk to the right person' — usually in another building
        or town (the Mart clerk hands Oak's Parcel; Oak takes it; etc.). So:
        we go find people we HAVEN'T spoken to yet: when this map's folk are all
        met, travel to another known map that still has someone new. We do NOT
        re-pester people already talked to — only a real story event (detected by
        GameSense) reopens them, which is exactly when their dialogue has changed.
        That event also reopens blocked doors, so the freshly-opened path gets used."""
        self.active_capability = "Decision-making"
        self._note_gate(state)
        m = state.current_map

        # Following the strategist's advice: head for the place it named.
        if self._llm_target is not None:
            if m == self._llm_target:
                self._llm_target = None  # arrived
            else:
                step = self.sense.route_toward_map(m, state.x_pos, state.y_pos, self._llm_target)
                if step is not None:
                    self.thought = f"Strategist says go to {map_name(self._llm_target)}."
                    return int(step)
                self._llm_target = None  # can't get there from here — drop it

        # If we've spoken to everyone reachable here, go where someone new is.
        if self.sense._uninteracted_npc_count(m) == 0:
            for target in self.sense.maps_with_unmet_npcs():
                if target == m:
                    continue
                step = self.sense.route_toward_map(m, state.x_pos, state.y_pos, target)
                if step is not None:
                    self.thought = f"Stuck — off to {map_name(target)} to talk to someone."
                    return int(step)

        # Otherwise let GameSense seek + talk to people on this map (its own
        # NPC-seeking sets seeking_event, so the base class walks up and presses
        # A) and re-probe the blocked path so a now-opened gate gets noticed.
        return super()._overworld_action(state, sem)

    def _go_toward_service(self, state, *, center: bool = False, mart: bool = False) -> Action | None:
        """Route toward the nearest roots-known town that has the wanted service,
        if we've been there (so a route exists). Returns None if none reachable."""
        names = self.roots.center_town_names() if center else self.roots.mart_town_names()
        m = state.current_map
        for name in names:
            target = _NAME_TO_MAP.get(name.lower())
            if target is None:
                continue
            step = self.sense.route_toward_map(m, state.x_pos, state.y_pos, target)
            if step is not None:
                if mart:
                    self.thought = f"Need supplies — heading to {name}'s Mart."
                return int(step)
        return None

    def _note_gate(self, state) -> None:
        """If a known story gate matches where we are, say what unlocks it (so the
        viewer sees the agent treats it as an errand, not a wall)."""
        gate = self._current_gate(state)
        if gate is not None:
            self.plan_text = f"Blocked here: {gate.unlock}"

    # --- helpers ---

    def _talk_to_nearest_person(self, state, sem) -> Action | None:
        """Walk up to and talk to the nearest person (e.g. the Center nurse),
        re-talking freely — unlike exploration, here we WANT to engage."""
        if self._interact_queue:
            a = self._interact_queue.pop(0)
            self.sense.note_action(state, a)
            return a
        facing = self._facing_person(state, sem)
        if facing is not None:
            self._interact_queue = [int(facing), int(Action.A), int(Action.A)]
            a = self._interact_queue.pop(0)
            self.sense.note_action(state, a)
            return a
        path = self.sense.world.path_to_adjacent_npc(state.current_map, state.x_pos, state.y_pos)
        if path:
            self.sense.note_action(state, int(path[0]))
            return int(path[0])
        action = self.sense.explore_action(state)  # wander the room to find them
        return int(action) if action is not None else int(Action.A)

    def _facing_person(self, state, sem) -> Action | None:
        """Direction of an adjacent person/object, ignoring the talked-to set."""
        for action, cells in _FACING.items():
            if any(
                int(sem[r, c]) == int(TileClass.NPC)
                for r, c in cells
                if 0 <= r < sem.shape[0] and 0 <= c < sem.shape[1]
            ):
                return action
        return None
