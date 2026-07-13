"""T0 tests for the stream_state classifier v3 (pokeai.ui.stream_state).

The vocabulary and the safer-ancestor rule come from
docs/Native-Stream-Operator.md (State Rules / State detectability).
v3 (FIXLIST op-states cluster 2026-07-06): LOW_HP_DANGER scoped to battles,
GYM_BATTLE/BOSS_TRANSITION/CUTSCENE/POST_BATTLE_SAFE/BETWEEN_OBJECTIVES/
CATCH_DECISION emitted, RIVAL_BATTLE by task prefix.
"""
from pokeai.ui.stream_state import classify


def _c(**kw):
    base = dict(connected=True, in_world=True, status="running",
                saving=False, in_battle=False, active_task_id="route1",
                cur_map=(3, 19), active_hp_frac=1.0, wild_battle=None)
    base.update(kw)
    return classify(**base)


def test_offline_wins_over_everything():
    assert _c(connected=False, saving=True, in_battle=True) == "OFFLINE"


def test_save_critical_beats_battle():
    assert _c(saving=True, in_battle=True) == "SAVE_CRITICAL"


def test_rival_battle_by_task_prefix():
    """Any rival-arc task id counts, not just Part 1's literal 'rival1'
    (FIXLIST rival-battle-keyed-to-rival1-only: Route 22's rematch)."""
    assert _c(in_battle=True, active_task_id="rival1") == "RIVAL_BATTLE"
    assert _c(in_battle=True, active_task_id="rival_route22") == "RIVAL_BATTLE"


def test_unknown_battle_resolves_to_trainer_safer_ancestor():
    assert _c(in_battle=True) == "TRAINER_BATTLE"
    assert _c(in_battle=True, wild_battle=None) == "TRAINER_BATTLE"


def test_wild_battle_when_proven():
    assert _c(in_battle=True, wild_battle=True) == "WILD_BATTLE"


def test_catch_decision_when_armed():
    """An armed catch_next turns the wild battle into CATCH_DECISION (polls
    Yes vs WILD_BATTLE's Limited - FIXLIST catch-decision-...-missing)."""
    assert _c(in_battle=True, wild_battle=True, catch_armed=True) == "CATCH_DECISION"
    # arming is meaningless in a trainer fight
    assert _c(in_battle=True, wild_battle=False, catch_armed=True) == "TRAINER_BATTLE"


def test_gym_battle_by_gym_map():
    """In battle inside a gym interior = GYM_BATTLE (FIXLIST
    gym-battle-boss-transition-never-emitted; Pewter gym = (6,2))."""
    assert _c(in_battle=True, cur_map=(6, 2)) == "GYM_BATTLE"


def test_boss_transition_on_gym_arc_tasks():
    assert _c(active_task_id="brock") == "BOSS_TRANSITION"
    assert _c(active_task_id="p3_gym") == "BOSS_TRANSITION"
    # but IN the gym fight it is GYM_BATTLE, not the prep window
    assert _c(in_battle=True, cur_map=(6, 2), active_task_id="brock") == "GYM_BATTLE"


def test_intro_vs_starting_soon():
    assert _c(in_world=False, status="running") == "INTRO"
    assert _c(in_world=False, status="ready") == "STARTING_SOON"


def test_low_hp_danger_scoped_to_battles():
    """The doc: 'Any battle where active Pokemon is at risky HP'. v2 had it
    inverted - firing in the overworld, never in battle (FIXLIST
    low-hp-danger-scope-inverted)."""
    assert _c(in_battle=True, active_hp_frac=0.29) == "LOW_HP_DANGER"
    assert _c(in_battle=True, wild_battle=True, active_hp_frac=0.1) == "LOW_HP_DANGER"
    # outside battle low HP is NOT the danger state; map states win
    assert _c(active_hp_frac=0.1) == "ROUTE_TRAVEL"
    assert _c(active_hp_frac=0.1, cur_map=(5, 4)) == "POKEMON_CENTER"
    assert _c(in_battle=True, active_hp_frac=0.30) == "TRAINER_BATTLE"


def test_cutscene_via_frozen_bit():
    assert _c(frozen=True) == "CUTSCENE"
    # battle outranks the frozen bit (battle intros can set script locks)
    assert _c(frozen=True, in_battle=True) == "TRAINER_BATTLE"


def test_post_battle_safe_grace_window():
    assert _c(seconds_since_battle=10.0) == "POST_BATTLE_SAFE"
    assert _c(seconds_since_battle=44.9) == "POST_BATTLE_SAFE"
    assert _c(seconds_since_battle=45.0) == "ROUTE_TRAVEL"
    assert _c(seconds_since_battle=None) == "ROUTE_TRAVEL"


def test_between_objectives_when_task_queue_idle():
    assert _c(active_task_id=None) == "BETWEEN_OBJECTIVES"
    # a map landmark still wins over idle
    assert _c(active_task_id=None, cur_map=(5, 4)) == "POKEMON_CENTER"


def test_center_and_mart_interiors():
    assert _c(cur_map=(5, 4)) == "POKEMON_CENTER"
    assert _c(cur_map=(5, 3)) == "SHOPPING"
    # the interiors confirmed live 7/5-7/6
    assert _c(cur_map=(6, 5)) == "POKEMON_CENTER"   # Pewter
    assert _c(cur_map=(16, 0)) == "POKEMON_CENTER"  # Route 4
    assert _c(cur_map=(7, 3)) == "POKEMON_CENTER"   # Cerulean
    assert _c(cur_map=(6, 3)) == "SHOPPING"         # Pewter Mart


def test_pallet_and_default_route():
    assert _c(cur_map=(3, 0)) == "PALLET_TOWN"
    assert _c(cur_map=(4, 1)) == "PALLET_TOWN"
    assert _c(cur_map=(3, 19)) == "ROUTE_TRAVEL"
    assert _c(cur_map=(99, 99)) == "ROUTE_TRAVEL"  # unknown overworld -> safer ancestor


def test_battle_beats_location_states():
    assert _c(in_battle=True, cur_map=(5, 4)) == "TRAINER_BATTLE"
