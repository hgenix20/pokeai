"""Reward engine. Computes weighted reward from state deltas.

Extrinsic signals (Phase 1):
  - badge: count increase since previous state
  - event: event-flag-set count increase
  - map: new unique maps visited
  - level: party total level increase (optionally capped, anti-grind)
  - blackout: penalty when all party members faint (one-shot per episode)

Battle shaping (reward v2 — makes fighting learnable instead of incidental):
  - battle_damage: fraction of enemy max HP dealt while in battle
  - battle_win: bonus per enemy mon KO'd (battle ends or mon swaps at 0 HP)
  - faint: penalty per own party mon fainting
  - heal: fraction of party max HP restored (respawn healing excluded)

Intrinsic / reliability signals:
  - curiosity (5.1): novelty bonus 1/sqrt(visit_count) for the current
    position. Visit counts persist across episodes within a run so the
    agent is pushed toward genuinely new ground over its lifetime.
  - stuck (5.2 Adaptability): penalty when the same action repeats with
    no position change past a threshold (anti-perseveration).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeai.config import RewardWeights
from pokeai.emulator.state_reader import BattleState, GameState
from pokeai.knowledge.visit_memory import VisitMemory


@dataclass
class RewardBreakdown:
    """Per-step reward attribution. Useful for debugging."""

    badge: float = 0.0
    event: float = 0.0
    map: float = 0.0
    level: float = 0.0
    blackout: float = 0.0
    curiosity: float = 0.0
    stuck: float = 0.0
    battle_damage: float = 0.0
    battle_win: float = 0.0
    faint: float = 0.0
    heal: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.badge
            + self.event
            + self.map
            + self.level
            + self.blackout
            + self.curiosity
            + self.stuck
            + self.battle_damage
            + self.battle_win
            + self.faint
            + self.heal
        )


class RewardEngine:
    """Stateful: tracks previous state and visited-map set across an episode.

    The VisitMemory (curiosity counter) persists across episodes within a run —
    it is only reset when a new RewardEngine is constructed (i.e. a new run).
    """

    def __init__(self, weights: RewardWeights, visit_memory: VisitMemory | None = None):
        self.weights = weights
        self.visit_memory = visit_memory or VisitMemory()
        self._prev: GameState | None = None
        self._visited_maps: set[int] = set()
        self._blackout_triggered: bool = False
        # Anti-loop (5.2) state
        self._last_action: int | None = None
        self._repeat_no_move_count = 0
        # Episode counters for the skills profile
        self._episode_steps = 0
        self._episode_repeat_steps = 0
        self._episode_steps_stuck_total = 0
        self._episode_curiosity_total = 0.0
        # Adversity (5.3) proxy: did HP drop below 25% and recover above 50%?
        self._was_low_hp = False
        self._recovered_from_low_hp = False
        # Battle shaping (v2) state
        self._prev_battle: BattleState | None = None
        self._battles_won = 0

    def reset_episode(self) -> None:
        self._prev = None
        self._visited_maps = set()
        self._blackout_triggered = False
        self._last_action = None
        self._repeat_no_move_count = 0
        self._episode_steps = 0
        self._episode_repeat_steps = 0
        self._episode_steps_stuck_total = 0
        self._episode_curiosity_total = 0.0
        self._was_low_hp = False
        self._recovered_from_low_hp = False
        self._prev_battle = None
        self._battles_won = 0
        # Curiosity memory: episode-scoped counters reset, run-scoped persist
        self.visit_memory.reset_episode()

    def reset_run(self) -> None:
        """Complete reset: also wipe the run-level curiosity memory so the next
        episode explores from a blank slate (periodic full-reset)."""
        self.reset_episode()
        self.visit_memory.reset_run()

    def compute(
        self,
        state: GameState,
        action: int | None = None,
        battle: BattleState | None = None,
    ) -> RewardBreakdown:
        """Compute reward for transition from previous state to `state`.

        `action` is the action that produced this transition (used by the
        anti-loop module). `battle` is the battle perception snapshot for the
        same step (battle-shaping rewards). Both None on the seeding call.
        """
        breakdown = RewardBreakdown()

        # First call of an episode: seed state, record position, no reward
        if self._prev is None:
            self._prev = state
            self._prev_battle = battle
            self._visited_maps.add(state.current_map)
            self.visit_memory.record(state.current_map, state.x_pos, state.y_pos)
            return breakdown

        self._episode_steps += 1

        # Badge delta (non-negative)
        badge_delta = max(0, state.badge_count - self._prev.badge_count)
        breakdown.badge = self.weights.badge * badge_delta

        # Event flag delta (non-negative)
        event_delta = max(0, state.event_flags_set - self._prev.event_flags_set)
        breakdown.event = self.weights.event * event_delta

        # New map discovery
        if state.current_map not in self._visited_maps:
            self._visited_maps.add(state.current_map)
            breakdown.map = self.weights.map * 1.0

        # Level delta (non-negative; optionally capped to kill grind exploits)
        cap = self.weights.level_cap
        if cap > 0:
            level_delta = max(
                0,
                min(state.party_total_level, cap) - min(self._prev.party_total_level, cap),
            )
        else:
            level_delta = max(0, state.party_total_level - self._prev.party_total_level)
        breakdown.level = self.weights.level * level_delta

        # Blackout: trigger exactly once per episode
        if (not self._blackout_triggered) and state.all_party_fainted:
            breakdown.blackout = -self.weights.blackout
            self._blackout_triggered = True

        # --- Battle shaping (reward v2) ---
        if battle is not None and self._prev_battle is not None:
            pb = self._prev_battle
            if battle.in_battle and pb.in_battle:
                # Damage dealt: enemy HP fraction decrease (per-mon; a trainer
                # swap restores HP, which the max(0, ...) ignores).
                dmg = max(0.0, pb.enemy_hp_frac - battle.enemy_hp_frac)
                breakdown.battle_damage = self.weights.battle_damage * dmg
                # Trainer-battle KO: enemy hit 0 then the next mon swapped in.
                if pb.enemy_hp_frac <= 0.0 < battle.enemy_hp_frac:
                    breakdown.battle_win = self.weights.battle_win
                    self._battles_won += 1
            elif pb.in_battle and not battle.in_battle:
                # Battle ended; pay the win bonus only for a KO (not a flee).
                if pb.enemy_hp_frac <= 0.0:
                    breakdown.battle_win = self.weights.battle_win
                    self._battles_won += 1
        if battle is not None:
            self._prev_battle = battle

        # Own-mon faints (blackout penalty stacks on top of the last one)
        faint_delta = max(0, state.party_fainted_count - self._prev.party_fainted_count)
        breakdown.faint = -self.weights.faint_penalty * faint_delta

        # Healing: party HP fraction restored. Skip the post-blackout respawn
        # heal (that's the penalty path, not something to reward).
        if (
            self.weights.heal > 0
            and state.party_total_max_hp > 0
            and self._prev.party_total_max_hp > 0
            and not self._prev.all_party_fainted
        ):
            frac_now = state.party_total_hp / state.party_total_max_hp
            frac_prev = self._prev.party_total_hp / self._prev.party_total_max_hp
            if frac_now > frac_prev:
                breakdown.heal = self.weights.heal * (frac_now - frac_prev)

        # --- Curiosity: novelty BEFORE recording this visit ---
        if self.weights.curiosity > 0:
            novelty = self.visit_memory.novelty(state.current_map, state.x_pos, state.y_pos)
            breakdown.curiosity = self.weights.curiosity * novelty
            self._episode_curiosity_total += breakdown.curiosity
        self.visit_memory.record(state.current_map, state.x_pos, state.y_pos)

        # --- Anti-looping: anti-perseveration ---
        moved = (
            state.x_pos != self._prev.x_pos
            or state.y_pos != self._prev.y_pos
            or state.current_map != self._prev.current_map
        )
        in_battle = state.battle_type != 0
        # is_repeat: pressed the same action as last step without progress
        is_repeat = (
            action is not None
            and action == self._last_action
            and not moved
            and not in_battle
        )
        # no_move_press: any press that produced no progress (starts a repeat run)
        no_move_press = action is not None and not moved and not in_battle
        if is_repeat:
            self._repeat_no_move_count += 1
            self._episode_repeat_steps += 1
        elif no_move_press:
            self._repeat_no_move_count = 1  # first press of a potential repeat run
        else:
            self._repeat_no_move_count = 0
        if not moved and not in_battle:
            self._episode_steps_stuck_total += 1
        if (
            self.weights.stuck_penalty > 0
            and self._repeat_no_move_count >= self.weights.stuck_threshold
        ):
            breakdown.stuck = -self.weights.stuck_penalty
        self._last_action = action

        # --- Survival proxy: low-HP recovery tracking ---
        if state.party_count > 0 and state.party_total_max_hp > 0:
            hp_frac = state.party_total_hp / state.party_total_max_hp
            if hp_frac <= 0.25 and state.party_total_hp > 0:
                self._was_low_hp = True
            elif self._was_low_hp and hp_frac >= 0.5:
                self._recovered_from_low_hp = True

        self._prev = state
        return breakdown

    # --- Episode-level metrics (read by env/loop for the skills profile) ---

    @property
    def unique_maps_visited(self) -> int:
        return len(self._visited_maps)

    @property
    def blackout_occurred(self) -> bool:
        return self._blackout_triggered

    @property
    def battles_won(self) -> int:
        """Enemy mons KO'd this episode (reward v2 battle shaping)."""
        return self._battles_won

    @property
    def unique_tiles_visited(self) -> int:
        """Exploration metric: unique positions this episode."""
        return self.visit_memory.unique_positions_episode

    @property
    def repeat_action_rate(self) -> float:
        """Anti-looping metric: fraction of steps that repeated an
        action without moving. Should fall as adaptability develops."""
        if self._episode_steps == 0:
            return 0.0
        return self._episode_repeat_steps / self._episode_steps

    @property
    def steps_stuck(self) -> int:
        """Current consecutive repeat-without-movement count."""
        return self._repeat_no_move_count

    @property
    def total_steps_stuck(self) -> int:
        """Total no-movement steps this episode."""
        return self._episode_steps_stuck_total

    @property
    def curiosity_reward_total(self) -> float:
        return self._episode_curiosity_total

    @property
    def recovered_from_low_hp(self) -> bool:
        """Survival metric: recovered from <=25% HP to >=50%."""
        return self._recovered_from_low_hp
