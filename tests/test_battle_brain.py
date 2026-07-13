"""Tests for the Gen 1 type chart, move scoring, and the BattleBrain driver."""
from __future__ import annotations

from pokeai.agents.battle_brain import BattleBrain, STUCK_DECISIONS
from pokeai.emulator.state_reader import StateReader
from pokeai.env.action_controller import Action
from pokeai.knowledge import type_chart as tc
from pokeai.knowledge.type_chart import best_move, effectiveness, score_moves
from tests.mock_emulator import MockEmulator, encode_state

# Move IDs
EMBER = 0x34       # Fire, 40 power
SCRATCH = 0x0A     # Normal, 40 power
GROWL = 0x2D       # status
WATER_GUN = 0x37   # Water, 40 power


class TestTypeChart:
    def test_water_beats_fire(self):
        assert effectiveness(tc.WATER, tc.FIRE, tc.FIRE) == 2.0

    def test_gen1_ghost_does_not_hit_psychic(self):
        assert effectiveness(tc.GHOST, tc.PSYCHIC_T, tc.PSYCHIC_T) == 0.0

    def test_gen1_bug_poison_mutual_super_effective(self):
        assert effectiveness(tc.BUG, tc.POISON, tc.POISON) == 2.0
        assert effectiveness(tc.POISON, tc.BUG, tc.BUG) == 2.0

    def test_gen1_ice_neutral_vs_fire(self):
        assert effectiveness(tc.ICE, tc.FIRE, tc.FIRE) == 1.0

    def test_dual_type_multiplies(self):
        # Electric vs Flying/Water (e.g. Gyarados): 2 x 2 = 4
        assert effectiveness(tc.ELECTRIC, tc.FLYING, tc.WATER) == 4.0

    def test_immunity_dominates_dual_type(self):
        # Ground vs Flying/anything = 0
        assert effectiveness(tc.GROUND, tc.FLYING, tc.FIRE) == 0.0


class TestMoveScoring:
    def test_stab_and_effectiveness(self):
        # Charmander (Fire) vs Oddish (Grass/Poison): Ember = 40 * 2 * 1.5
        scores = score_moves(
            (EMBER, SCRATCH, 0, 0), (25, 35, 0, 0),
            tc.FIRE, tc.FIRE, tc.GRASS, tc.POISON,
        )
        ember = next(s for s in scores if s.move_id == EMBER)
        assert ember.multiplier == 2.0
        assert ember.stab == 1.5
        assert ember.score == 40 * 2.0 * 1.5
        assert best_move(scores).move_id == EMBER

    def test_zero_pp_moves_unusable(self):
        scores = score_moves(
            (EMBER, SCRATCH, 0, 0), (0, 35, 0, 0),
            tc.FIRE, tc.FIRE, tc.GRASS, tc.GRASS,
        )
        ember = next(s for s in scores if s.move_id == EMBER)
        assert ember.score == 0.0
        assert best_move(scores).move_id == SCRATCH

    def test_status_moves_score_zero(self):
        scores = score_moves(
            (GROWL, 0, 0, 0), (40, 0, 0, 0),
            tc.NORMAL, tc.NORMAL, tc.NORMAL, tc.NORMAL,
        )
        assert scores[0].score == 0.0
        assert best_move(scores) is None

    def test_type_disadvantage_changes_pick(self):
        # Fire mon vs Water enemy: Ember halved (x0.5 * 1.5 STAB = 30),
        # Water Gun (x0.5, no STAB = 10), Scratch neutral 40 wins.
        scores = score_moves(
            (EMBER, WATER_GUN, SCRATCH, 0), (25, 25, 35, 0),
            tc.FIRE, tc.FIRE, tc.WATER, tc.WATER,
        )
        assert best_move(scores).move_id == SCRATCH


def _battle_snapshot(**over):
    """Mid-battle snapshot: Charmander (Ember+Scratch+Growl) vs Oddish."""
    defaults = dict(
        party_count=1,
        party_hp=[18],
        party_max_hp=[20],
        party_levels=[10],
        party_species=[0xB0],
        party_types=[(tc.FIRE, tc.FIRE)],
        party_moves=[(EMBER, SCRATCH, GROWL, 0)],
        party_pp=[(25, 35, 40, 0)],
        battle_type=1,
        enemy_species=0xB9,  # Oddish
        enemy_hp=20,
        enemy_max_hp=20,
        enemy_level=8,
        enemy_types=(tc.GRASS, tc.POISON),
    )
    defaults.update(over)
    return encode_state(**defaults)


def _brain(snapshots):
    reader = StateReader(MockEmulator(snapshots))
    return BattleBrain(reader)


class TestBattleBrainDriver:
    def test_no_menu_presses_a(self):
        brain = _brain([_battle_snapshot(text_box_id=1)])
        assert brain.decide() == int(Action.A)
        assert "advancing" in brain.thought.lower() or "Battling" in brain.thought

    def test_action_menu_on_fight_confirms(self):
        snap = _battle_snapshot(text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=0)
        brain = _brain([snap])
        assert brain.decide() == int(Action.A)
        assert "Ember" in brain.thought  # the type-smart pick is narrated

    def test_action_menu_wrong_column_moves_left(self):
        snap = _battle_snapshot(text_box_id=11, top_menu_y=14, top_menu_x=15, cursor_item=0)
        brain = _brain([snap])
        assert brain.decide() == int(Action.LEFT)

    def test_action_menu_wrong_row_moves_up(self):
        snap = _battle_snapshot(text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=1)
        brain = _brain([snap])
        assert brain.decide() == int(Action.UP)

    def test_move_menu_navigates_to_best_move(self):
        # Cursor on Scratch but Ember is the right call vs a Grass type.
        snap = _battle_snapshot(
            text_box_id=11, top_menu_y=12, top_menu_x=5,
            cursor_item=2, selected_move_id=SCRATCH,
        )
        brain = _brain([snap])
        assert brain.decide() == int(Action.DOWN)

    def test_move_menu_confirms_best_move(self):
        snap = _battle_snapshot(
            text_box_id=11, top_menu_y=12, top_menu_x=5,
            cursor_item=1, selected_move_id=EMBER,
        )
        brain = _brain([snap])
        assert brain.decide() == int(Action.A)
        assert "super effective" in brain.thought

    def test_flee_when_hopeless_wild_battle(self):
        # 2/20 HP vs a healthy enemy -> RUN (right column first).
        snap = _battle_snapshot(
            party_hp=[2], text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=0,
        )
        brain = _brain([snap])
        assert brain.decide() == int(Action.RIGHT)

    def test_no_flee_from_trainer_battle(self):
        snap = _battle_snapshot(
            party_hp=[2], battle_type=2,
            text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=0,
        )
        brain = _brain([snap])
        assert brain.decide() == int(Action.A)  # stays on FIGHT

    def test_wedge_detection_backs_out_with_b(self):
        # Same unrecognized open menu every decision -> eventually press B.
        snap = _battle_snapshot(text_box_id=11, top_menu_y=7, top_menu_x=15, cursor_item=0)
        brain = _brain([snap])
        actions = [brain.decide() for _ in range(STUCK_DECISIONS + 2)]
        assert int(Action.B) in actions
