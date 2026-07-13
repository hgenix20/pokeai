"""Tests for the Gen 3 (FireRed) battle knowledge module.

Spot-checks the type chart against Bulbapedia's Gen 2-5 chart (including every
delta from the Gen 1 chart), move ids/stats against pokefirered's
src/data/battle_moves.h, species typings against species_info.h, and the
score_moves/best_move API that battle v2 shares with the Gen 1 module.
"""
from __future__ import annotations

from pokeai.knowledge import gen3_battle as g3
from pokeai.knowledge import type_chart as g1
from pokeai.knowledge.gen3_battle import (
    BUG,
    DARK,
    DRAGON,
    ELECTRIC,
    FIGHTING,
    FIRE,
    FLYING,
    GHOST,
    GRASS,
    GROUND,
    ICE,
    MOVES,
    MYSTERY,
    NORMAL,
    POISON,
    PSYCHIC_T,
    ROCK,
    SPECIES_TYPES,
    STEEL,
    WATER,
    MoveScore,
    best_move,
    effectiveness,
    move_name,
    score_moves,
    species_types,
)

# ---------------------------------------------------------------- type ids


def test_type_ids_are_firered_engine_values():
    # pokefirered include/constants/pokemon.h
    assert NORMAL == 0x00
    assert FIGHTING == 0x01
    assert FLYING == 0x02
    assert POISON == 0x03
    assert GROUND == 0x04
    assert ROCK == 0x05
    assert BUG == 0x06
    assert GHOST == 0x07
    assert STEEL == 0x08
    assert MYSTERY == 0x09
    assert FIRE == 0x0A
    assert WATER == 0x0B
    assert GRASS == 0x0C
    assert ELECTRIC == 0x0D
    assert PSYCHIC_T == 0x0E
    assert ICE == 0x0F
    assert DRAGON == 0x10
    assert DARK == 0x11


def test_bug_and_ghost_ids_differ_from_gen1():
    # Gen 1 RAM used BUG=0x07 / GHOST=0x08; the GBA engine packs them at 6/7.
    assert (g1.BUG, g1.GHOST) == (0x07, 0x08)
    assert (BUG, GHOST) == (0x06, 0x07)


# ---------------------------------------------------------------- type chart


def _e(atk, dfn):
    return effectiveness(atk, dfn, None)


def test_chart_matches_grand_total_from_decomp():
    # gTypeEffectiveness has 112 triples; 2 are sentinels (Foresight, end).
    assert len(g3._EFFECT) == 110


def test_gen1_to_gen3_deltas():
    # Bug/Poison: mutually super effective in Gen 1 only.
    assert _e(BUG, POISON) == 0.5
    assert _e(POISON, BUG) == 1.0
    assert g1.effectiveness(g1.BUG, g1.POISON, g1.POISON) == 2.0
    assert g1.effectiveness(g1.POISON, g1.BUG, g1.BUG) == 2.0
    # Ghost -> Psychic: the Gen 1 "no effect" bug is fixed.
    assert _e(GHOST, PSYCHIC_T) == 2.0
    assert g1.effectiveness(g1.GHOST, g1.PSYCHIC_T, g1.PSYCHIC_T) == 0.0
    # Ice -> Fire: neutral in Gen 1, resisted from Gen 2 on.
    assert _e(ICE, FIRE) == 0.5
    assert g1.effectiveness(g1.ICE, g1.FIRE, g1.FIRE) == 1.0


def test_dark_rows():
    assert _e(DARK, PSYCHIC_T) == 2.0
    assert _e(DARK, GHOST) == 2.0
    assert _e(DARK, DARK) == 0.5
    assert _e(DARK, FIGHTING) == 0.5
    assert _e(DARK, STEEL) == 0.5  # Gen 3: Steel still resists Dark
    assert _e(PSYCHIC_T, DARK) == 0.0
    assert _e(FIGHTING, DARK) == 2.0
    assert _e(BUG, DARK) == 2.0
    assert _e(GHOST, DARK) == 0.5


def test_steel_rows():
    assert _e(STEEL, ROCK) == 2.0
    assert _e(STEEL, ICE) == 2.0
    assert _e(STEEL, STEEL) == 0.5
    assert _e(STEEL, FIRE) == 0.5
    assert _e(STEEL, WATER) == 0.5
    assert _e(STEEL, ELECTRIC) == 0.5
    # Attacks into Steel.
    assert _e(POISON, STEEL) == 0.0
    assert _e(NORMAL, STEEL) == 0.5
    assert _e(FIGHTING, STEEL) == 2.0
    assert _e(GROUND, STEEL) == 2.0
    assert _e(FIRE, STEEL) == 2.0
    assert _e(GHOST, STEEL) == 0.5  # Gen 3: Steel still resists Ghost
    assert _e(BUG, STEEL) == 0.5
    assert _e(GRASS, STEEL) == 0.5
    assert _e(WATER, STEEL) == 1.0
    assert _e(ELECTRIC, STEEL) == 1.0


def test_classic_chart_spot_checks():
    assert _e(NORMAL, GHOST) == 0.0  # post-Foresight row in gTypeEffectiveness
    assert _e(FIGHTING, GHOST) == 0.0  # post-Foresight row in gTypeEffectiveness
    assert _e(NORMAL, ROCK) == 0.5
    assert _e(GROUND, FLYING) == 0.0
    assert _e(ELECTRIC, GROUND) == 0.0
    assert _e(GHOST, NORMAL) == 0.0
    assert _e(WATER, FIRE) == 2.0
    assert _e(FIRE, GRASS) == 2.0
    assert _e(GRASS, WATER) == 2.0
    assert _e(ELECTRIC, WATER) == 2.0
    assert _e(ICE, DRAGON) == 2.0
    assert _e(DRAGON, DRAGON) == 2.0
    assert _e(FIGHTING, PSYCHIC_T) == 0.5
    assert _e(GHOST, GHOST) == 2.0
    assert _e(FIRE, WATER) == 0.5
    assert _e(MYSTERY, NORMAL) == 1.0  # ??? (Curse) is neutral vs everything


def test_dual_type_multiplication():
    assert effectiveness(WATER, ROCK, GROUND) == 4.0
    assert effectiveness(GRASS, ROCK, GROUND) == 4.0
    assert effectiveness(ELECTRIC, ROCK, GROUND) == 0.0
    assert effectiveness(ELECTRIC, NORMAL, FLYING) == 2.0
    assert effectiveness(GROUND, ELECTRIC, STEEL) == 4.0
    assert effectiveness(FIGHTING, NORMAL, FLYING) == 1.0  # 2.0 * 0.5


def test_mono_type_second_slot_conventions():
    # None and a repeated type1 must both mean "mono-typed".
    assert effectiveness(WATER, FIRE, None) == 2.0
    assert effectiveness(WATER, FIRE, FIRE) == 2.0


# ---------------------------------------------------------------- moves


def test_move_spot_checks():
    # ids and stats verbatim from pokefirered src/data/battle_moves.h
    tackle = MOVES[33]
    assert (tackle.name, tackle.type_id, tackle.power, tackle.pp) == ("Tackle", NORMAL, 35, 35)
    bubble = MOVES[145]
    assert (bubble.type_id, bubble.power, bubble.pp) == (WATER, 20, 30)
    vine_whip = MOVES[22]
    assert (vine_whip.type_id, vine_whip.power, vine_whip.pp) == (GRASS, 35, 10)
    bite = MOVES[44]
    assert (bite.type_id, bite.power, bite.pp) == (DARK, 60, 25)  # Dark from Gen 2 on
    water_gun = MOVES[55]
    assert (water_gun.type_id, water_gun.power, water_gun.pp) == (WATER, 40, 25)
    rock_tomb = MOVES[317]
    assert (rock_tomb.type_id, rock_tomb.power, rock_tomb.pp) == (ROCK, 50, 10)


def test_gen3_move_typing_deltas_from_gen1():
    assert MOVES[16].type_id == FLYING  # Gust (Normal in Gen 1)
    assert MOVES[2].type_id == FIGHTING  # Karate Chop (Normal in Gen 1)
    assert MOVES[28].type_id == GROUND  # Sand Attack (Normal in Gen 1)
    assert MOVES[44].type_id == DARK  # Bite (Normal in Gen 1)
    assert MOVES[204].type_id == NORMAL  # Charm is Normal in Gen 3 (Fairy is Gen 6+)
    assert MOVES[174].type_id == MYSTERY  # Curse is the lone ??? move


def test_status_moves_have_zero_power():
    assert MOVES[28].power == 0  # Sand Attack
    assert MOVES[204].power == 0  # Charm
    assert MOVES[174].power == 0  # Curse
    assert MOVES[14].power == 0  # Swords Dance


def test_move_table_sanity():
    # Contiguous FireRed id space 1..354, sane stats everywhere.
    assert set(MOVES.keys()) == set(range(1, 355))
    valid_types = set(range(0x12))  # NORMAL..DARK, including MYSTERY
    for move_id, m in MOVES.items():
        assert m.move_id == move_id
        assert isinstance(m.name, str) and m.name.strip()
        assert m.type_id in valid_types, m.name
        assert 0 <= m.power <= 250, m.name  # Explosion tops out at 250 in Gen 3
        assert 1 <= m.pp <= 40, m.name  # Sketch has 1; nothing exceeds 40
    assert MOVES[153].power == 250  # Explosion is the ceiling
    assert MOVES[166].pp == 1  # Sketch is the floor


def test_move_name_helper():
    assert move_name(33) == "Tackle"
    assert move_name(0) == "-"
    assert move_name(999) == "Move 999"


# ---------------------------------------------------------------- species


def test_species_spot_checks():
    assert species_types(7) == (WATER, None)  # Squirtle
    assert species_types(16) == (NORMAL, FLYING)  # Pidgey
    assert species_types(74) == (ROCK, GROUND)  # Geodude
    assert species_types(95) == (ROCK, GROUND)  # Onix
    assert species_types(10) == (BUG, None)  # Caterpie
    assert species_types(25) == (ELECTRIC, None)  # Pikachu
    assert species_types(81) == (ELECTRIC, STEEL)  # Magnemite (Steel from Gen 2 on)
    assert species_types(82) == (ELECTRIC, STEEL)  # Magneton
    assert species_types(35) == (NORMAL, None)  # Clefairy: Normal (no Fairy in Gen 3)
    assert species_types(1) == (GRASS, POISON)  # Bulbasaur
    assert species_types(151) == (PSYCHIC_T, None)  # Mew
    assert species_types(999) is None


def test_species_table_sanity():
    # Every Kanto species (Gen 3 internal ids 1-151 == National Dex).
    assert set(SPECIES_TYPES.keys()) == set(range(1, 152))
    valid_types = set(range(0x12))
    for sid, (t1, t2) in SPECIES_TYPES.items():
        assert t1 in valid_types, sid
        assert t2 is None or (t2 in valid_types and t2 != t1), sid


# ---------------------------------------------------------------- scoring


def test_stab_scoring():
    # Squirtle (Water) using Water Gun vs Charmander (Fire): 40 * 2.0 * 1.5.
    scores = score_moves([55, 33, 0, 0], [25, 35, 0, 0], WATER, None, FIRE, None)
    assert len(scores) == 2  # empty slots skipped
    water_gun, tackle = scores
    assert water_gun.score == 40 * 2.0 * 1.5 == 120.0
    assert water_gun.stab == 1.5
    assert water_gun.multiplier == 2.0
    assert tackle.score == 35.0  # no STAB, neutral
    assert best_move(scores) is water_gun


def test_stab_with_dual_typed_attacker():
    # Geodude (Rock/Ground) using Rock Tomb vs Charmander: 50 * 2.0 * 1.5.
    scores = score_moves([317, 0, 0, 0], [10, 0, 0, 0], ROCK, GROUND, FIRE, None)
    assert scores[0].score == 150.0


def test_x4_scoring_and_label():
    # Water Gun vs Geodude (Rock/Ground): 40 * 4.0, no STAB.
    scores = score_moves([55, 0, 0, 0], [25, 0, 0, 0], NORMAL, None, ROCK, GROUND)
    assert scores[0].score == 160.0
    assert scores[0].effectiveness_label == "x4 devastating"


def test_immune_status_and_no_pp_score_zero():
    # Thunder Shock vs Geodude (immune), Sand Attack (status), Tackle with 0 PP.
    scores = score_moves([84, 28, 33, 0], [30, 15, 0, 0], ELECTRIC, None, ROCK, GROUND)
    shock, sand, tackle = scores
    assert shock.multiplier == 0.0 and shock.score == 0.0
    assert shock.effectiveness_label == "no effect"
    assert sand.power == 0 and sand.score == 0.0
    assert sand.effectiveness_label == "status"
    assert tackle.pp_left == 0 and tackle.score == 0.0
    assert best_move(scores) is None


def test_unknown_move_listed_but_never_picked():
    scores = score_moves([999, 33], [5, 35], NORMAL, None, NORMAL, None)
    unknown = scores[0]
    assert unknown.move_id == 999 and unknown.score == 0.0
    picked = best_move(scores)
    assert picked is not None and picked.move_id == 33
    # STAB applies: Tackle from a Normal attacker.
    assert picked.score == 35 * 1.0 * 1.5


def test_move_score_is_frozen_dataclass():
    s = MoveScore(0, 33, "Tackle", NORMAL, 35, 35, 1.0, 1.0, 35.0)
    try:
        s.score = 0.0
        raised = False
    except Exception:
        raised = True
    assert raised
