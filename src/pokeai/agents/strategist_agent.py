"""Strategist: a perception-driven agent that plays the game like a person.

Unlike the learners (which discover behavior from reward), the Strategist is a
hand-written "expert" that actually *reads the screen* and acts on what it sees:

  1. Reads on-screen text. If someone is talking or a message is up, it reads
     it and presses A to continue. If a yes/no prompt appears, it answers.
  2. In battle, hands off to the BattleBrain (type-aware move selection through
     the real menus), which it also narrates.
  3. In the overworld it knows what each tile *is* (walkable, wall, grass,
     person) from the semantic tile grid, and explores like a person looking
     for the way out: it picks the least-explored global direction (from its
     visit memory) and commits to it, and when a fence or building blocks the
     way it **follows the wall** sideways until it finds the gap — instead of
     mashing into it. When under-leveled it steers into grass to train, and it
     walks up to people to talk to them.

Everything it "knows" comes from perception + memory, and every decision is
narrated in plain language for the stream THOUGHTS panel.

Needs an attached env (RAM, collision, screen). Without one it degrades to a
simple wander so build_agent never hard-fails.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from pokeai.agents.base import Agent
from pokeai.agents.battle_brain import BattleBrain
from pokeai.emulator.screen_reader import ScreenContext, TileClass
from pokeai.env.action_controller import Action
from pokeai.knowledge.game_data import map_name

# Direction -> map-coordinate delta (y grows south). Used for global novelty.
_MAP_DELTA: dict[Action, tuple[int, int]] = {
    Action.UP: (0, -1),
    Action.DOWN: (0, 1),
    Action.LEFT: (-1, 0),
    Action.RIGHT: (1, 0),
}
_DIRS = list(_MAP_DELTA.keys())

# The 16px tile the player would step into, as a block of 8px collision cells.
# The player sprite sits at rows 8-9, cols 8-9 of the 18x20 grid.
_FACING_CELLS: dict[Action, list[tuple[int, int]]] = {
    Action.UP: [(7, 8), (7, 9)],
    Action.DOWN: [(10, 8), (10, 9)],
    Action.LEFT: [(8, 7), (9, 7)],
    Action.RIGHT: [(8, 10), (9, 10)],
}
_PERPENDICULAR: dict[Action, list[Action]] = {
    Action.UP: [Action.LEFT, Action.RIGHT],
    Action.DOWN: [Action.LEFT, Action.RIGHT],
    Action.LEFT: [Action.UP, Action.DOWN],
    Action.RIGHT: [Action.UP, Action.DOWN],
}

# Episodes reset to the level-5 starter, so deep grinding is pointless — the
# agent makes forward progress toward new towns/routes (that's what's worth
# watching), and battles happen naturally where the path crosses grass.
# Steps without our map-position changing before we treat ourselves as stuck.
STUCK_AFTER = 6
# How far ahead (map tiles) to integrate novelty when choosing a heading.
HEADING_LOOKAHEAD = 5
# Loop detection: if the last LOOP_WINDOW moves only covered <= LOOP_UNIQUE
# distinct map tiles, we're ping-ponging (e.g. A<->B against a fence) even
# though our position keeps "changing" — break out with a committed detour.
LOOP_WINDOW = 12
LOOP_UNIQUE = 3
# Steps to commit to a forced escape heading once a loop is detected (long
# enough to actually leave the pocket we were trapped in).
BREAKOUT_STEPS = 8
# Map-bounce detection: warping back and forth between the same two maps (e.g.
# up/down a staircase, or in/out a doorway) is a loop our tile-based detector
# misses because each visit covers several distinct tiles. If the last
# BOUNCE_WINDOW overworld steps crossed between just two maps at least
# BOUNCE_MIN times, we're stuck on a warp — commit to a long, rotating sweep of
# the current floor so we actually find the real exit instead of the warp.
BOUNCE_WINDOW = 28
BOUNCE_MIN = 3
BOUNCE_BREAKOUT_STEPS = 16
# Rotation order tried, in turn, when one breakout sweep doesn't free us.
_ROTATION = [Action.DOWN, Action.LEFT, Action.RIGHT, Action.UP]


class StrategistAgent(Agent):
    name = "strategist"

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)
        self.env = None
        self.brain: BattleBrain | None = None
        self._last_pos: tuple[int, int, int] | None = None
        self._stuck_steps = 0
        self._rescue_i = 0
        self._heading: Action | None = None
        self._sweep: Action | None = None
        self._recent: deque[tuple[int, int, int]] = deque(maxlen=LOOP_WINDOW)
        self._recent_maps: deque[int] = deque(maxlen=BOUNCE_WINDOW)
        self._breakout: Action | None = None
        self._breakout_left = 0
        self._rotation_i = 0
    # --- Wiring ---

    def attach_env(self, env) -> None:
        self.env = env
        self.brain = BattleBrain(env.state_reader)

    def reset(self) -> None:
        self._last_pos = None
        self._stuck_steps = 0
        self._rescue_i = 0
        self._heading = None
        self._sweep = None
        self._recent.clear()
        self._recent_maps.clear()
        self._breakout = None
        self._breakout_left = 0
        self._rotation_i = 0
        if self.brain is not None:
            self.brain.reset()

    # --- Decision ---

    def act(self, observation: np.ndarray) -> int:
        if self.env is None or self.brain is None:
            return self._act_blind(observation)

        state = self.env.state_reader.read()
        view = self.env.screen_reader.view(in_battle=state.battle_type != 0)

        # 0) Opening sequence — before we have a Pokemon (party_count == 0):
        # title screen, Oak's intro speech, the naming screens, and walking from
        # the bedroom to Oak's lab. There are no battles here and nothing to
        # cancel, so the rule is simple and robust: advance any text/menu with A,
        # otherwise walk. (Pressing B here could delete a name letter or back out
        # of the intro, and the speech frames sometimes look like a menu — so we
        # never hand this phase to the normal menu/dialogue handlers.)
        if state.party_count == 0:
            if self._in_intro(state) or view.has_text or view.context != ScreenContext.FREE_ROAM:
                self.thought = "At the start of the game — pressing A through the intro"
                return int(Action.A)
            self.thought = "Just got control — finding my way to Prof. Oak's lab"
            return self._act_overworld(state)

        # 1) Battle: the BattleBrain reads the battle menus and picks moves.
        if view.context == ScreenContext.BATTLE or state.battle_type != 0:
            self._stuck_steps = 0
            self._last_pos = None
            action = self.brain.decide()
            self.thought = self.brain.thought
            return action

        # 2) A menu is open in the overworld (START menu, a shop, a sign list).
        if view.context == ScreenContext.MENU:
            return self._handle_menu(view)

        # 3) A message / dialogue box is up — read it and continue.
        if view.context == ScreenContext.DIALOGUE:
            snippet = view.dialogue[:38]
            self.thought = f'Reading: "{snippet}" — pressing A to continue'
            return int(Action.A)

        # 4) Free roam: navigate with intent.
        return self._act_overworld(state)

    @staticmethod
    def _in_intro(state) -> bool:
        """True on the title screen / opening cutscene, before player control.
        The overworld map+position registers are all zero there, which never
        happens once the player is actually walking the world."""
        return (
            state.current_map == 0
            and state.x_pos == 0
            and state.y_pos == 0
            and state.party_count == 0
        )

    # --- Overworld navigation (committed-heading wall-follower) ---

    def _act_overworld(self, state) -> int:
        pos = (state.current_map, state.x_pos, state.y_pos)
        if self._last_pos is not None and pos == self._last_pos:
            self._stuck_steps += 1
        else:
            self._stuck_steps = 0
        self._last_pos = pos
        self._recent.append(pos)
        self._recent_maps.append(state.current_map)
        if self._stuck_steps >= STUCK_AFTER:
            return self._rescue()

        sem = self.env.screen_reader.semantic_tiles()

        # Already committed to a breakout heading? Keep pushing it (open or
        # wall-follow) until the budget runs out — this is how we leave a pocket
        # we were ping-ponging in.
        if self._breakout_left > 0:
            self._breakout_left -= 1
            return self._drive_heading(state, sem, self._breakout, breakout=True)

        # Map-bounce: warping back and forth between two maps (stairs, doorway).
        # Each visit covers several tiles so the tile loop-check below misses it;
        # detect the warp toggling and sweep the floor in a rotating direction.
        if self._is_map_bouncing():
            return self._start_bounce_breakout(state, sem)

        # Loop detection: position keeps "changing" but only across a handful of
        # tiles (oscillating against a fence). The frozen-position check above
        # never catches this, so detect the small cycle and force a detour.
        if len(self._recent) == LOOP_WINDOW and len(set(self._recent)) <= LOOP_UNIQUE:
            return self._start_breakout(state, sem)

        # Head toward the least-explored ground (forward progress / the exit to
        # the next area). Battles happen naturally where that path crosses grass.
        self._heading = self._choose_heading(state, sem)
        return self._drive_heading(state, sem, self._heading)

    def _drive_heading(self, state, sem, heading: Action, *, breakout: bool = False) -> int:
        """Walk `heading` if it's open; otherwise follow the wall sideways until
        it opens up (find the gap). People and buildings are obstacles to route
        around; bumping one that talks is read as dialogue next step."""
        self._heading = heading
        m = state.current_map
        if self._walkable_dir(sem, heading):
            self._sweep = None
            if breakout:
                self.thought = f"Breaking out of the loop — pushing {heading.name} to new ground"
            else:
                reason = (
                    "through the grass" if self._dir_is_grass(sem, heading)
                    else "exploring for the way onward"
                )
                self.thought = f"Exploring {map_name(m)} — heading {heading.name} ({reason})"
            return int(heading)

        # Heading blocked: follow the obstacle sideways (persist the sweep side).
        sweep = self._pick_sweep(sem, state)
        if sweep is not None:
            self._sweep = sweep
            self.thought = (
                f"{map_name(m)}: {heading.name} is blocked — following the wall "
                f"{sweep.name} to find a way through"
            )
            return int(sweep)

        # Boxed in on three sides: turn around.
        return self._rescue()

    def _is_map_bouncing(self) -> bool:
        """True when recent steps keep crossing between just two maps (warp
        toggling), e.g. up and down a staircase."""
        if len(self._recent_maps) < BOUNCE_WINDOW:
            return False
        maps = list(self._recent_maps)
        if len(set(maps)) != 2:
            return False
        crossings = sum(1 for a, b in zip(maps, maps[1:]) if a != b)
        return crossings >= BOUNCE_MIN

    def _start_bounce_breakout(self, state, sem) -> int:
        """Stuck toggling a warp. Pick the next walkable direction in a fixed
        rotation (so successive attempts try genuinely different ways out, not
        the warp we keep falling into) and commit to a long floor sweep."""
        self._recent.clear()
        self._recent_maps.clear()
        heading = None
        for _ in range(len(_ROTATION)):
            cand = _ROTATION[self._rotation_i % len(_ROTATION)]
            self._rotation_i += 1
            if self._walkable_dir(sem, cand):
                heading = cand
                break
        heading = heading or _ROTATION[self._rotation_i % len(_ROTATION)]
        self._breakout = heading
        self._breakout_left = BOUNCE_BREAKOUT_STEPS
        self._sweep = None
        self.thought = (
            f"Stuck on a staircase/doorway — sweeping {heading.name} to find the real way out"
        )
        return self._drive_heading(state, sem, heading, breakout=True)

    def _start_breakout(self, state, sem) -> int:
        """We're cycling over a few tiles. Commit to the walkable direction that
        leads to the most novel ground and push it hard for several steps so we
        actually escape the pocket instead of sliding back in."""
        self._recent.clear()
        vm = self.env.reward_engine.visit_memory
        m, x, y = state.current_map, state.x_pos, state.y_pos
        walkable = [d for d in _DIRS if self._walkable_dir(sem, d)]
        cands = walkable or _DIRS
        heading = max(
            cands,
            key=lambda d: sum(
                vm.novelty(m, x + _MAP_DELTA[d][0] * k, y + _MAP_DELTA[d][1] * k)
                for k in range(1, HEADING_LOOKAHEAD + 1)
            ),
        )
        self._breakout = heading
        self._breakout_left = BREAKOUT_STEPS
        self._sweep = None
        return self._drive_heading(state, sem, heading, breakout=True)

    def _choose_heading(self, state, sem) -> Action:
        """Pick the globally least-explored direction, with commitment.

        Integrates visit-memory novelty several tiles ahead in each direction so
        the choice reflects where unexplored ground actually lies, and adds a
        bonus for keeping the current heading so the agent doesn't dither.
        """
        vm = self.env.reward_engine.visit_memory
        m, x, y = state.current_map, state.x_pos, state.y_pos
        best, best_score = self._heading or Action.UP, -1.0
        for action in _DIRS:
            dx, dy = _MAP_DELTA[action]
            score = sum(vm.novelty(m, x + dx * k, y + dy * k) for k in range(1, HEADING_LOOKAHEAD + 1))
            if action == self._heading:
                score += 0.75  # commitment: don't abandon a heading on a tie
            if score > best_score:
                best, best_score = action, score
        return best

    def _dir_is_grass(self, sem, action: Action) -> bool:
        return any(int(sem[r, c]) == int(TileClass.GRASS) for r, c in _FACING_CELLS[action])

    def _pick_sweep(self, sem, state) -> Action | None:
        """Choose which way to follow a wall: keep sweeping the same way if we
        still can, else pick the walkable perpendicular with more novelty."""
        if self._sweep is not None and self._walkable_dir(sem, self._sweep):
            return self._sweep
        vm = self.env.reward_engine.visit_memory
        m, x, y = state.current_map, state.x_pos, state.y_pos
        cands = [d for d in _PERPENDICULAR[self._heading] if self._walkable_dir(sem, d)]
        if not cands:
            return None
        return max(cands, key=lambda d: vm.novelty(m, x + _MAP_DELTA[d][0], y + _MAP_DELTA[d][1]))

    def _walkable_dir(self, sem, action: Action) -> bool:
        ok = (int(TileClass.WALKABLE), int(TileClass.GRASS), int(TileClass.PLAYER))
        return any(int(sem[r, c]) in ok for r, c in _FACING_CELLS[action])

    def _rescue(self) -> int:
        """Wedged: clear a stray message (A), back out of a menu (B), or turn."""
        self._sweep = None
        phase = self._rescue_i % 3
        self._rescue_i += 1
        if phase == 0:
            self.thought = "Stuck — checking for a message I missed (A)"
            return int(Action.A)
        if phase == 1:
            self.thought = "Stuck — backing out of anything open (B)"
            return int(Action.B)
        turn = Action(int(self.rng.choice([int(a) for a in _DIRS])))
        self._heading = turn
        self.thought = f"Stuck — trying a new direction ({turn.name})"
        return int(turn)

    def _handle_menu(self, view) -> int:
        """A menu/list is open. The Strategist walks rather than shops, so it
        reads the prompt and backs out (B = no/cancel) to keep moving."""
        if view.asks_yes_no:
            self.thought = f'Prompt: "{view.dialogue[:30]}" — answering NO to keep exploring'
            return int(Action.B)
        opt = view.cursor_option or (view.menu_options[0] if view.menu_options else "")
        self.thought = f'Menu open (on "{opt}") — closing it to keep moving (B)'
        return int(Action.B)

    def _act_blind(self, observation: np.ndarray) -> int:
        from pokeai.env.pokemon_red_env import OBS_FIELDS

        if int(observation[OBS_FIELDS.index("battle_type")]) != 0:
            self.thought = "In battle (no screen access) — mashing A"
            return int(Action.A)
        action = Action(int(self.rng.choice([int(a) for a in _DIRS])))
        self.thought = f"Wandering {action.name} (no screen access)"
        return int(action)
