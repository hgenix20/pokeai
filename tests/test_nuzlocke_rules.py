"""T0 tests for the pure Nuzlocke ruleset (pokeai.rules.nuzlocke).

No bridge, no ROM — the same pattern as tests/test_stream_state.py, which
tests the pure `classify` helper. All Nuzlocke decision logic lives in the
pure module by design, so `Control` keeps only thin glue; these tests pin the
whole surface: the should_catch matrix, permadeath death tracking, seeded
randomize, the level cap, and the to_public shape.
"""
from random import Random

from pokeai.rules.nuzlocke import (
    CORE_KEYS,
    NUZLOCKE_RULES,
    NuzlockeRuleset,
)

AREA_A = (3, 19)
AREA_B = (3, 20)


def _rs(*rules) -> NuzlockeRuleset:
    """A ruleset with the core active (add_rule auto-includes it) plus any
    extra rules. Passing no extras yields a core-only ruleset."""
    rs = NuzlockeRuleset()
    rs.add_rule("permadeath")  # pulls in the whole mandatory core
    for r in rules:
        rs.add_rule(r)
    return rs


# --- catalog ----------------------------------------------------------------


def test_core_rules_are_mandatory_and_enforced():
    assert set(CORE_KEYS) == {"permadeath", "first_encounter", "nickname_all"}
    for key in CORE_KEYS:
        assert NUZLOCKE_RULES[key].mandatory is True
        assert NUZLOCKE_RULES[key].enforced is True


def test_display_only_rules_declare_not_enforced():
    for key in ("shiny_clause", "no_legendaries", "mono_type"):
        assert NUZLOCKE_RULES[key].enforced is False


def test_adding_any_rule_auto_includes_the_core():
    rs = _rs("no_battle_items")
    assert set(CORE_KEYS) <= rs.active
    assert "no_battle_items" in rs.active


def test_adding_an_unknown_rule_is_a_noop():
    rs = NuzlockeRuleset()
    assert rs.add_rule("does_not_exist") is False
    assert rs.active == set()


# --- should_catch matrix ----------------------------------------------------


def test_should_catch_false_when_no_ruleset_active():
    rs = NuzlockeRuleset()
    assert rs.should_catch(AREA_A, [], 16) is False


def test_first_encounter_only_once_per_area():
    rs = _rs()  # core only -> first_encounter active
    assert rs.should_catch(AREA_A, [], 16) is True
    rs.on_caught(AREA_A, 16)
    # same area is now spent
    assert rs.should_catch(AREA_A, [16], 19) is False
    # a different area is fresh again
    assert rs.should_catch(AREA_B, [16], 19) is True


def test_dupes_clause_skips_owned_species():
    rs = _rs("dupes_clause")
    rs.on_caught(AREA_A, 16)  # own species 16
    assert rs.should_catch(AREA_B, [16], 16) is False  # dupe by species
    assert rs.should_catch(AREA_B, [16], 19) is True   # new species ok


def test_species_clause_blocks_a_species_already_on_team():
    rs = _rs("species_clause")
    assert rs.should_catch(AREA_A, [25], 25) is False
    assert rs.should_catch(AREA_A, [25], 19) is True


# --- nickname ---------------------------------------------------------------


def test_nickname_for_none_without_rule_else_uppercase():
    rs = NuzlockeRuleset()
    assert rs.nickname_for(25) is None
    rs.add_rule("dupes_clause")  # core (nickname_all) auto-added
    nick = rs.nickname_for(25)
    assert nick is not None
    assert nick == nick.upper()
    # deterministic per species
    assert rs.nickname_for(25) == nick


# --- permadeath tracking ----------------------------------------------------


def test_permadeath_records_death_on_alive_to_fainted_transition():
    rs = _rs()  # permadeath active (core)
    alive = [{"species": 25, "hp": 20, "max_hp": 20, "level": 12}]
    fainted = [{"species": 25, "hp": 0, "max_hp": 20, "level": 12}]

    rs.observe_party(alive, AREA_A)
    assert rs.tracker.deaths == []          # still alive, nothing recorded
    rs.observe_party(fainted, AREA_A)
    assert len(rs.tracker.deaths) == 1
    assert rs.is_dead(25) is True

    # idempotent: re-observing the same fainted slot never double-counts
    rs.observe_party(fainted, AREA_A)
    assert len(rs.tracker.deaths) == 1


def test_permadeath_ignores_a_slot_never_seen_alive():
    rs = _rs()
    # first observation already fainted -> not a transition, not recorded
    rs.observe_party([{"species": 19, "hp": 0, "max_hp": 18, "level": 3}], AREA_A)
    assert rs.tracker.deaths == []
    assert rs.is_dead(19) is False


def test_is_dead_false_when_permadeath_off():
    rs = _rs("no_battle_items")
    rs.active.discard("permadeath")  # simulate permadeath disabled
    assert rs.is_dead(25) is False


# --- difficulty gates -------------------------------------------------------


def test_level_cap_gate():
    rs = _rs("level_cap")
    rs.level_cap = 14
    assert rs.level_cap_ok(14) is True
    assert rs.level_cap_ok(15) is False
    # off -> always ok
    rs2 = _rs()
    assert rs2.level_cap_ok(99) is True


def test_battle_item_and_center_gates():
    rs = _rs()
    assert rs.allow_battle_item() is True
    assert rs.allow_center() is True
    rs.add_rule("no_battle_items")
    rs.add_rule("no_pokemon_centers")
    assert rs.allow_battle_item() is False
    assert rs.allow_center() is False


# --- randomize (seeded) -----------------------------------------------------


def test_randomize_is_seeded_and_includes_core():
    a = NuzlockeRuleset()
    a.randomize(Random(42))
    b = NuzlockeRuleset()
    b.randomize(Random(42))
    assert a.active == b.active                 # deterministic under a seed
    assert set(CORE_KEYS) <= a.active           # core always included
    assert all(k in NUZLOCKE_RULES for k in a.active)


def test_apply_directive_random_clear_and_add():
    rs = NuzlockeRuleset()
    assert rs.apply_directive("random", Random(1)) == "randomized"
    assert rs.is_active() is True
    assert rs.apply_directive("clear", Random(1)) == "cleared"
    assert rs.active == set()
    assert rs.apply_directive("no_battle_items", Random(1)) == "added:no_battle_items"
    assert "no_battle_items" in rs.active
    assert rs.apply_directive("bogus", Random(1)) == "unknown:bogus"


def test_clear_resets_the_tracker():
    rs = _rs()
    rs.on_caught(AREA_A, 25)
    rs.observe_party([{"species": 25, "hp": 20, "max_hp": 20}], AREA_A)
    rs.observe_party([{"species": 25, "hp": 0, "max_hp": 20}], AREA_A)
    assert rs.tracker.deaths
    rs.clear()
    assert rs.tracker.deaths == []
    assert rs.tracker.areas_used == set()
    assert rs.tracker.species_owned == set()


# --- to_public shape --------------------------------------------------------


def test_to_public_shape():
    rs = _rs("no_battle_items", "shiny_clause")
    rs.on_caught(AREA_A, 25)
    pub = rs.to_public()
    assert pub["active"] is True
    keys = {r["key"] for r in pub["rules"]}
    assert set(CORE_KEYS) <= keys
    assert "no_battle_items" in keys and "shiny_clause" in keys
    # the honest enforced flag rides along
    shiny = next(r for r in pub["rules"] if r["key"] == "shiny_clause")
    assert shiny["enforced"] is False
    tr = pub["tracker"]
    assert tr_keys(tr) == {"deaths", "death_count", "encounters", "areas_used", "species_owned"}
    assert tr["encounters"] == 1
    assert tr["areas_used"] == 1
    assert tr["species_owned"] == 1


def tr_keys(tracker: dict) -> set:
    return set(tracker.keys())


def test_to_public_empty_when_inactive():
    rs = NuzlockeRuleset()
    pub = rs.to_public()
    assert pub["active"] is False
    assert pub["rules"] == []
