"""Gen 3 (FireRed) battle knowledge: type chart + move data + species types.

Sources: pret/pokefirered decompilation --
  - include/constants/pokemon.h   (TYPE_* engine ids)
  - src/battle_main.c             (gTypeEffectiveness table)
  - include/constants/moves.h     (MOVE_* engine ids, 1-354)
  - src/data/battle_moves.h       (gBattleMoves: power / type / PP)
  - src/data/pokemon/species_info.h (species typings; Kanto ids 1-151
    equal the National Dex numbers in the Gen 3 engine)

Gen 3 facts that differ from the Gen 1 module (type_chart.py):
  - Dark and Steel exist. Ghost and Dark hit Steel at 0.5x in Gen 3
    (this changed to 1x only in Gen 6).
  - Ghost -> Psychic is 2.0 (the Gen 1 "Ghost misses Psychic" bug is gone).
  - Bug -> Poison is 0.5 and Poison -> Bug is 1.0 (both were 2.0 in Gen 1).
  - Ice -> Fire is 0.5 (was 1.0 in Gen 1).
  - Bite is DARK, Gust is FLYING, Karate Chop is FIGHTING and
    Sand Attack is GROUND (all NORMAL in Gen 1). Charm is NORMAL in Gen 3.
  - Curse is the only TYPE_MYSTERY (0x09) move.

Fixed/variable-damage moves (Seismic Toss, Night Shade, Dragon Rage, ...)
carry power 1 in the FireRed data and therefore rank low; status moves have
power 0 and score 0. Values are verbatim from the decomp, not normalized.

Mirrors the type_chart.py API so battle v2 can swap modules per generation:
effectiveness(), MoveInfo, MOVES, MoveScore, score_moves(), best_move().
Unlike Gen 1, PP bytes are NOT masked with 0x3F: in the Gen 3 party
structure PP is a plain byte (PP Ups live in a separate ppBonuses field).

Pure data + scoring logic; no emulator dependency (testable without a ROM).
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Type IDs (Gen 3 engine values, pokefirered include/constants/pokemon.h) ---
NORMAL = 0x00
FIGHTING = 0x01
FLYING = 0x02
POISON = 0x03
GROUND = 0x04
ROCK = 0x05
BUG = 0x06
GHOST = 0x07
STEEL = 0x08
MYSTERY = 0x09  # "???" -- used only by Curse
FIRE = 0x0A
WATER = 0x0B
GRASS = 0x0C
ELECTRIC = 0x0D
PSYCHIC_T = 0x0E
ICE = 0x0F
DRAGON = 0x10
DARK = 0x11

TYPE_NAMES: dict[int, str] = {
    NORMAL: "Normal",
    FIGHTING: "Fighting",
    FLYING: "Flying",
    POISON: "Poison",
    GROUND: "Ground",
    ROCK: "Rock",
    BUG: "Bug",
    GHOST: "Ghost",
    STEEL: "Steel",
    MYSTERY: "???",
    FIRE: "Fire",
    WATER: "Water",
    GRASS: "Grass",
    ELECTRIC: "Electric",
    PSYCHIC_T: "Psychic",
    ICE: "Ice",
    DRAGON: "Dragon",
    DARK: "Dark",
}

# --- Effectiveness: (attack_type, defend_type) -> multiplier ---
# Pairs not listed are neutral (1.0). Transcribed 1:1 from gTypeEffectiveness
# in pokefirered src/battle_main.c (sentinel rows dropped; the Normal/Fighting
# vs Ghost immunities listed after the Foresight marker are included).
_EFFECT: dict[tuple[int, int], float] = {
    (NORMAL, ROCK): 0.5,
    (NORMAL, STEEL): 0.5,
    (FIRE, FIRE): 0.5,
    (FIRE, WATER): 0.5,
    (FIRE, GRASS): 2.0,
    (FIRE, ICE): 2.0,
    (FIRE, BUG): 2.0,
    (FIRE, ROCK): 0.5,
    (FIRE, DRAGON): 0.5,
    (FIRE, STEEL): 2.0,
    (WATER, FIRE): 2.0,
    (WATER, WATER): 0.5,
    (WATER, GRASS): 0.5,
    (WATER, GROUND): 2.0,
    (WATER, ROCK): 2.0,
    (WATER, DRAGON): 0.5,
    (ELECTRIC, WATER): 2.0,
    (ELECTRIC, ELECTRIC): 0.5,
    (ELECTRIC, GRASS): 0.5,
    (ELECTRIC, GROUND): 0.0,
    (ELECTRIC, FLYING): 2.0,
    (ELECTRIC, DRAGON): 0.5,
    (GRASS, FIRE): 0.5,
    (GRASS, WATER): 2.0,
    (GRASS, GRASS): 0.5,
    (GRASS, POISON): 0.5,
    (GRASS, GROUND): 2.0,
    (GRASS, FLYING): 0.5,
    (GRASS, BUG): 0.5,
    (GRASS, ROCK): 2.0,
    (GRASS, DRAGON): 0.5,
    (GRASS, STEEL): 0.5,
    (ICE, WATER): 0.5,
    (ICE, GRASS): 2.0,
    (ICE, ICE): 0.5,
    (ICE, GROUND): 2.0,
    (ICE, FLYING): 2.0,
    (ICE, DRAGON): 2.0,
    (ICE, STEEL): 0.5,
    (ICE, FIRE): 0.5,
    (FIGHTING, NORMAL): 2.0,
    (FIGHTING, ICE): 2.0,
    (FIGHTING, POISON): 0.5,
    (FIGHTING, FLYING): 0.5,
    (FIGHTING, PSYCHIC_T): 0.5,
    (FIGHTING, BUG): 0.5,
    (FIGHTING, ROCK): 2.0,
    (FIGHTING, DARK): 2.0,
    (FIGHTING, STEEL): 2.0,
    (POISON, GRASS): 2.0,
    (POISON, POISON): 0.5,
    (POISON, GROUND): 0.5,
    (POISON, ROCK): 0.5,
    (POISON, GHOST): 0.5,
    (POISON, STEEL): 0.0,
    (GROUND, FIRE): 2.0,
    (GROUND, ELECTRIC): 2.0,
    (GROUND, GRASS): 0.5,
    (GROUND, POISON): 2.0,
    (GROUND, FLYING): 0.0,
    (GROUND, BUG): 0.5,
    (GROUND, ROCK): 2.0,
    (GROUND, STEEL): 2.0,
    (FLYING, ELECTRIC): 0.5,
    (FLYING, GRASS): 2.0,
    (FLYING, FIGHTING): 2.0,
    (FLYING, BUG): 2.0,
    (FLYING, ROCK): 0.5,
    (FLYING, STEEL): 0.5,
    (PSYCHIC_T, FIGHTING): 2.0,
    (PSYCHIC_T, POISON): 2.0,
    (PSYCHIC_T, PSYCHIC_T): 0.5,
    (PSYCHIC_T, DARK): 0.0,
    (PSYCHIC_T, STEEL): 0.5,
    (BUG, FIRE): 0.5,
    (BUG, GRASS): 2.0,
    (BUG, FIGHTING): 0.5,
    (BUG, POISON): 0.5,
    (BUG, FLYING): 0.5,
    (BUG, PSYCHIC_T): 2.0,
    (BUG, GHOST): 0.5,
    (BUG, DARK): 2.0,
    (BUG, STEEL): 0.5,
    (ROCK, FIRE): 2.0,
    (ROCK, ICE): 2.0,
    (ROCK, FIGHTING): 0.5,
    (ROCK, GROUND): 0.5,
    (ROCK, FLYING): 2.0,
    (ROCK, BUG): 2.0,
    (ROCK, STEEL): 0.5,
    (GHOST, NORMAL): 0.0,
    (GHOST, PSYCHIC_T): 2.0,
    (GHOST, DARK): 0.5,
    (GHOST, STEEL): 0.5,
    (GHOST, GHOST): 2.0,
    (DRAGON, DRAGON): 2.0,
    (DRAGON, STEEL): 0.5,
    (DARK, FIGHTING): 0.5,
    (DARK, PSYCHIC_T): 2.0,
    (DARK, GHOST): 2.0,
    (DARK, DARK): 0.5,
    (DARK, STEEL): 0.5,
    (STEEL, FIRE): 0.5,
    (STEEL, WATER): 0.5,
    (STEEL, ELECTRIC): 0.5,
    (STEEL, ICE): 2.0,
    (STEEL, ROCK): 2.0,
    (STEEL, STEEL): 0.5,
    (NORMAL, GHOST): 0.0,
    (FIGHTING, GHOST): 0.0,
}


def effectiveness(attack_type: int, defend_type1: int, defend_type2: int | None) -> float:
    """Combined type multiplier of an attack against a (possibly dual-typed)
    defender. A mono-type defender may pass None or repeat type1 in slot 2."""
    mult = _EFFECT.get((attack_type, defend_type1), 1.0)
    if defend_type2 is not None and defend_type2 != defend_type1:
        mult *= _EFFECT.get((attack_type, defend_type2), 1.0)
    return mult


@dataclass(frozen=True)
class MoveInfo:
    move_id: int
    name: str
    type_id: int
    power: int  # 0 = status move; fixed-damage moves carry power 1 (as in ROM)
    pp: int


# --- Gen 3 move table (id -> name, type, power, max PP) ---
# All 354 FireRed moves, values verbatim from pokefirered src/data/battle_moves.h.
MOVES: dict[int, MoveInfo] = {
    m.move_id: m
    for m in [
        MoveInfo(1, "Pound", NORMAL, 40, 35),
        MoveInfo(2, "Karate Chop", FIGHTING, 50, 25),
        MoveInfo(3, "Double Slap", NORMAL, 15, 10),
        MoveInfo(4, "Comet Punch", NORMAL, 18, 15),
        MoveInfo(5, "Mega Punch", NORMAL, 80, 20),
        MoveInfo(6, "Pay Day", NORMAL, 40, 20),
        MoveInfo(7, "Fire Punch", FIRE, 75, 15),
        MoveInfo(8, "Ice Punch", ICE, 75, 15),
        MoveInfo(9, "Thunder Punch", ELECTRIC, 75, 15),
        MoveInfo(10, "Scratch", NORMAL, 40, 35),
        MoveInfo(11, "Vice Grip", NORMAL, 55, 30),
        MoveInfo(12, "Guillotine", NORMAL, 1, 5),
        MoveInfo(13, "Razor Wind", NORMAL, 80, 10),
        MoveInfo(14, "Swords Dance", NORMAL, 0, 30),
        MoveInfo(15, "Cut", NORMAL, 50, 30),
        MoveInfo(16, "Gust", FLYING, 40, 35),
        MoveInfo(17, "Wing Attack", FLYING, 60, 35),
        MoveInfo(18, "Whirlwind", NORMAL, 0, 20),
        MoveInfo(19, "Fly", FLYING, 70, 15),
        MoveInfo(20, "Bind", NORMAL, 15, 20),
        MoveInfo(21, "Slam", NORMAL, 80, 20),
        MoveInfo(22, "Vine Whip", GRASS, 35, 10),
        MoveInfo(23, "Stomp", NORMAL, 65, 20),
        MoveInfo(24, "Double Kick", FIGHTING, 30, 30),
        MoveInfo(25, "Mega Kick", NORMAL, 120, 5),
        MoveInfo(26, "Jump Kick", FIGHTING, 70, 25),
        MoveInfo(27, "Rolling Kick", FIGHTING, 60, 15),
        MoveInfo(28, "Sand Attack", GROUND, 0, 15),
        MoveInfo(29, "Headbutt", NORMAL, 70, 15),
        MoveInfo(30, "Horn Attack", NORMAL, 65, 25),
        MoveInfo(31, "Fury Attack", NORMAL, 15, 20),
        MoveInfo(32, "Horn Drill", NORMAL, 1, 5),
        MoveInfo(33, "Tackle", NORMAL, 35, 35),
        MoveInfo(34, "Body Slam", NORMAL, 85, 15),
        MoveInfo(35, "Wrap", NORMAL, 15, 20),
        MoveInfo(36, "Take Down", NORMAL, 90, 20),
        MoveInfo(37, "Thrash", NORMAL, 90, 20),
        MoveInfo(38, "Double Edge", NORMAL, 120, 15),
        MoveInfo(39, "Tail Whip", NORMAL, 0, 30),
        MoveInfo(40, "Poison Sting", POISON, 15, 35),
        MoveInfo(41, "Twineedle", BUG, 25, 20),
        MoveInfo(42, "Pin Missile", BUG, 14, 20),
        MoveInfo(43, "Leer", NORMAL, 0, 30),
        MoveInfo(44, "Bite", DARK, 60, 25),
        MoveInfo(45, "Growl", NORMAL, 0, 40),
        MoveInfo(46, "Roar", NORMAL, 0, 20),
        MoveInfo(47, "Sing", NORMAL, 0, 15),
        MoveInfo(48, "Supersonic", NORMAL, 0, 20),
        MoveInfo(49, "Sonic Boom", NORMAL, 1, 20),
        MoveInfo(50, "Disable", NORMAL, 0, 20),
        MoveInfo(51, "Acid", POISON, 40, 30),
        MoveInfo(52, "Ember", FIRE, 40, 25),
        MoveInfo(53, "Flamethrower", FIRE, 95, 15),
        MoveInfo(54, "Mist", ICE, 0, 30),
        MoveInfo(55, "Water Gun", WATER, 40, 25),
        MoveInfo(56, "Hydro Pump", WATER, 120, 5),
        MoveInfo(57, "Surf", WATER, 95, 15),
        MoveInfo(58, "Ice Beam", ICE, 95, 10),
        MoveInfo(59, "Blizzard", ICE, 120, 5),
        MoveInfo(60, "Psybeam", PSYCHIC_T, 65, 20),
        MoveInfo(61, "Bubble Beam", WATER, 65, 20),
        MoveInfo(62, "Aurora Beam", ICE, 65, 20),
        MoveInfo(63, "Hyper Beam", NORMAL, 150, 5),
        MoveInfo(64, "Peck", FLYING, 35, 35),
        MoveInfo(65, "Drill Peck", FLYING, 80, 20),
        MoveInfo(66, "Submission", FIGHTING, 80, 25),
        MoveInfo(67, "Low Kick", FIGHTING, 1, 20),
        MoveInfo(68, "Counter", FIGHTING, 1, 20),
        MoveInfo(69, "Seismic Toss", FIGHTING, 1, 20),
        MoveInfo(70, "Strength", NORMAL, 80, 15),
        MoveInfo(71, "Absorb", GRASS, 20, 20),
        MoveInfo(72, "Mega Drain", GRASS, 40, 10),
        MoveInfo(73, "Leech Seed", GRASS, 0, 10),
        MoveInfo(74, "Growth", NORMAL, 0, 40),
        MoveInfo(75, "Razor Leaf", GRASS, 55, 25),
        MoveInfo(76, "Solar Beam", GRASS, 120, 10),
        MoveInfo(77, "Poison Powder", POISON, 0, 35),
        MoveInfo(78, "Stun Spore", GRASS, 0, 30),
        MoveInfo(79, "Sleep Powder", GRASS, 0, 15),
        MoveInfo(80, "Petal Dance", GRASS, 70, 20),
        MoveInfo(81, "String Shot", BUG, 0, 40),
        MoveInfo(82, "Dragon Rage", DRAGON, 1, 10),
        MoveInfo(83, "Fire Spin", FIRE, 15, 15),
        MoveInfo(84, "Thunder Shock", ELECTRIC, 40, 30),
        MoveInfo(85, "Thunderbolt", ELECTRIC, 95, 15),
        MoveInfo(86, "Thunder Wave", ELECTRIC, 0, 20),
        MoveInfo(87, "Thunder", ELECTRIC, 120, 10),
        MoveInfo(88, "Rock Throw", ROCK, 50, 15),
        MoveInfo(89, "Earthquake", GROUND, 100, 10),
        MoveInfo(90, "Fissure", GROUND, 1, 5),
        MoveInfo(91, "Dig", GROUND, 60, 10),
        MoveInfo(92, "Toxic", POISON, 0, 10),
        MoveInfo(93, "Confusion", PSYCHIC_T, 50, 25),
        MoveInfo(94, "Psychic", PSYCHIC_T, 90, 10),
        MoveInfo(95, "Hypnosis", PSYCHIC_T, 0, 20),
        MoveInfo(96, "Meditate", PSYCHIC_T, 0, 40),
        MoveInfo(97, "Agility", PSYCHIC_T, 0, 30),
        MoveInfo(98, "Quick Attack", NORMAL, 40, 30),
        MoveInfo(99, "Rage", NORMAL, 20, 20),
        MoveInfo(100, "Teleport", PSYCHIC_T, 0, 20),
        MoveInfo(101, "Night Shade", GHOST, 1, 15),
        MoveInfo(102, "Mimic", NORMAL, 0, 10),
        MoveInfo(103, "Screech", NORMAL, 0, 40),
        MoveInfo(104, "Double Team", NORMAL, 0, 15),
        MoveInfo(105, "Recover", NORMAL, 0, 20),
        MoveInfo(106, "Harden", NORMAL, 0, 30),
        MoveInfo(107, "Minimize", NORMAL, 0, 20),
        MoveInfo(108, "Smokescreen", NORMAL, 0, 20),
        MoveInfo(109, "Confuse Ray", GHOST, 0, 10),
        MoveInfo(110, "Withdraw", WATER, 0, 40),
        MoveInfo(111, "Defense Curl", NORMAL, 0, 40),
        MoveInfo(112, "Barrier", PSYCHIC_T, 0, 30),
        MoveInfo(113, "Light Screen", PSYCHIC_T, 0, 30),
        MoveInfo(114, "Haze", ICE, 0, 30),
        MoveInfo(115, "Reflect", PSYCHIC_T, 0, 20),
        MoveInfo(116, "Focus Energy", NORMAL, 0, 30),
        MoveInfo(117, "Bide", NORMAL, 1, 10),
        MoveInfo(118, "Metronome", NORMAL, 0, 10),
        MoveInfo(119, "Mirror Move", FLYING, 0, 20),
        MoveInfo(120, "Self Destruct", NORMAL, 200, 5),
        MoveInfo(121, "Egg Bomb", NORMAL, 100, 10),
        MoveInfo(122, "Lick", GHOST, 20, 30),
        MoveInfo(123, "Smog", POISON, 20, 20),
        MoveInfo(124, "Sludge", POISON, 65, 20),
        MoveInfo(125, "Bone Club", GROUND, 65, 20),
        MoveInfo(126, "Fire Blast", FIRE, 120, 5),
        MoveInfo(127, "Waterfall", WATER, 80, 15),
        MoveInfo(128, "Clamp", WATER, 35, 10),
        MoveInfo(129, "Swift", NORMAL, 60, 20),
        MoveInfo(130, "Skull Bash", NORMAL, 100, 15),
        MoveInfo(131, "Spike Cannon", NORMAL, 20, 15),
        MoveInfo(132, "Constrict", NORMAL, 10, 35),
        MoveInfo(133, "Amnesia", PSYCHIC_T, 0, 20),
        MoveInfo(134, "Kinesis", PSYCHIC_T, 0, 15),
        MoveInfo(135, "Soft Boiled", NORMAL, 0, 10),
        MoveInfo(136, "Hi Jump Kick", FIGHTING, 85, 20),
        MoveInfo(137, "Glare", NORMAL, 0, 30),
        MoveInfo(138, "Dream Eater", PSYCHIC_T, 100, 15),
        MoveInfo(139, "Poison Gas", POISON, 0, 40),
        MoveInfo(140, "Barrage", NORMAL, 15, 20),
        MoveInfo(141, "Leech Life", BUG, 20, 15),
        MoveInfo(142, "Lovely Kiss", NORMAL, 0, 10),
        MoveInfo(143, "Sky Attack", FLYING, 140, 5),
        MoveInfo(144, "Transform", NORMAL, 0, 10),
        MoveInfo(145, "Bubble", WATER, 20, 30),
        MoveInfo(146, "Dizzy Punch", NORMAL, 70, 10),
        MoveInfo(147, "Spore", GRASS, 0, 15),
        MoveInfo(148, "Flash", NORMAL, 0, 20),
        MoveInfo(149, "Psywave", PSYCHIC_T, 1, 15),
        MoveInfo(150, "Splash", NORMAL, 0, 40),
        MoveInfo(151, "Acid Armor", POISON, 0, 40),
        MoveInfo(152, "Crabhammer", WATER, 90, 10),
        MoveInfo(153, "Explosion", NORMAL, 250, 5),
        MoveInfo(154, "Fury Swipes", NORMAL, 18, 15),
        MoveInfo(155, "Bonemerang", GROUND, 50, 10),
        MoveInfo(156, "Rest", PSYCHIC_T, 0, 10),
        MoveInfo(157, "Rock Slide", ROCK, 75, 10),
        MoveInfo(158, "Hyper Fang", NORMAL, 80, 15),
        MoveInfo(159, "Sharpen", NORMAL, 0, 30),
        MoveInfo(160, "Conversion", NORMAL, 0, 30),
        MoveInfo(161, "Tri Attack", NORMAL, 80, 10),
        MoveInfo(162, "Super Fang", NORMAL, 1, 10),
        MoveInfo(163, "Slash", NORMAL, 70, 20),
        MoveInfo(164, "Substitute", NORMAL, 0, 10),
        MoveInfo(165, "Struggle", NORMAL, 50, 1),
        MoveInfo(166, "Sketch", NORMAL, 0, 1),
        MoveInfo(167, "Triple Kick", FIGHTING, 10, 10),
        MoveInfo(168, "Thief", DARK, 40, 10),
        MoveInfo(169, "Spider Web", BUG, 0, 10),
        MoveInfo(170, "Mind Reader", NORMAL, 0, 5),
        MoveInfo(171, "Nightmare", GHOST, 0, 15),
        MoveInfo(172, "Flame Wheel", FIRE, 60, 25),
        MoveInfo(173, "Snore", NORMAL, 40, 15),
        MoveInfo(174, "Curse", MYSTERY, 0, 10),
        MoveInfo(175, "Flail", NORMAL, 1, 15),
        MoveInfo(176, "Conversion 2", NORMAL, 0, 30),
        MoveInfo(177, "Aeroblast", FLYING, 100, 5),
        MoveInfo(178, "Cotton Spore", GRASS, 0, 40),
        MoveInfo(179, "Reversal", FIGHTING, 1, 15),
        MoveInfo(180, "Spite", GHOST, 0, 10),
        MoveInfo(181, "Powder Snow", ICE, 40, 25),
        MoveInfo(182, "Protect", NORMAL, 0, 10),
        MoveInfo(183, "Mach Punch", FIGHTING, 40, 30),
        MoveInfo(184, "Scary Face", NORMAL, 0, 10),
        MoveInfo(185, "Faint Attack", DARK, 60, 20),
        MoveInfo(186, "Sweet Kiss", NORMAL, 0, 10),
        MoveInfo(187, "Belly Drum", NORMAL, 0, 10),
        MoveInfo(188, "Sludge Bomb", POISON, 90, 10),
        MoveInfo(189, "Mud Slap", GROUND, 20, 10),
        MoveInfo(190, "Octazooka", WATER, 65, 10),
        MoveInfo(191, "Spikes", GROUND, 0, 20),
        MoveInfo(192, "Zap Cannon", ELECTRIC, 100, 5),
        MoveInfo(193, "Foresight", NORMAL, 0, 40),
        MoveInfo(194, "Destiny Bond", GHOST, 0, 5),
        MoveInfo(195, "Perish Song", NORMAL, 0, 5),
        MoveInfo(196, "Icy Wind", ICE, 55, 15),
        MoveInfo(197, "Detect", FIGHTING, 0, 5),
        MoveInfo(198, "Bone Rush", GROUND, 25, 10),
        MoveInfo(199, "Lock On", NORMAL, 0, 5),
        MoveInfo(200, "Outrage", DRAGON, 90, 15),
        MoveInfo(201, "Sandstorm", ROCK, 0, 10),
        MoveInfo(202, "Giga Drain", GRASS, 60, 5),
        MoveInfo(203, "Endure", NORMAL, 0, 10),
        MoveInfo(204, "Charm", NORMAL, 0, 20),
        MoveInfo(205, "Rollout", ROCK, 30, 20),
        MoveInfo(206, "False Swipe", NORMAL, 40, 40),
        MoveInfo(207, "Swagger", NORMAL, 0, 15),
        MoveInfo(208, "Milk Drink", NORMAL, 0, 10),
        MoveInfo(209, "Spark", ELECTRIC, 65, 20),
        MoveInfo(210, "Fury Cutter", BUG, 10, 20),
        MoveInfo(211, "Steel Wing", STEEL, 70, 25),
        MoveInfo(212, "Mean Look", NORMAL, 0, 5),
        MoveInfo(213, "Attract", NORMAL, 0, 15),
        MoveInfo(214, "Sleep Talk", NORMAL, 0, 10),
        MoveInfo(215, "Heal Bell", NORMAL, 0, 5),
        MoveInfo(216, "Return", NORMAL, 1, 20),
        MoveInfo(217, "Present", NORMAL, 1, 15),
        MoveInfo(218, "Frustration", NORMAL, 1, 20),
        MoveInfo(219, "Safeguard", NORMAL, 0, 25),
        MoveInfo(220, "Pain Split", NORMAL, 0, 20),
        MoveInfo(221, "Sacred Fire", FIRE, 100, 5),
        MoveInfo(222, "Magnitude", GROUND, 1, 30),
        MoveInfo(223, "Dynamic Punch", FIGHTING, 100, 5),
        MoveInfo(224, "Megahorn", BUG, 120, 10),
        MoveInfo(225, "Dragon Breath", DRAGON, 60, 20),
        MoveInfo(226, "Baton Pass", NORMAL, 0, 40),
        MoveInfo(227, "Encore", NORMAL, 0, 5),
        MoveInfo(228, "Pursuit", DARK, 40, 20),
        MoveInfo(229, "Rapid Spin", NORMAL, 20, 40),
        MoveInfo(230, "Sweet Scent", NORMAL, 0, 20),
        MoveInfo(231, "Iron Tail", STEEL, 100, 15),
        MoveInfo(232, "Metal Claw", STEEL, 50, 35),
        MoveInfo(233, "Vital Throw", FIGHTING, 70, 10),
        MoveInfo(234, "Morning Sun", NORMAL, 0, 5),
        MoveInfo(235, "Synthesis", GRASS, 0, 5),
        MoveInfo(236, "Moonlight", NORMAL, 0, 5),
        MoveInfo(237, "Hidden Power", NORMAL, 1, 15),
        MoveInfo(238, "Cross Chop", FIGHTING, 100, 5),
        MoveInfo(239, "Twister", DRAGON, 40, 20),
        MoveInfo(240, "Rain Dance", WATER, 0, 5),
        MoveInfo(241, "Sunny Day", FIRE, 0, 5),
        MoveInfo(242, "Crunch", DARK, 80, 15),
        MoveInfo(243, "Mirror Coat", PSYCHIC_T, 1, 20),
        MoveInfo(244, "Psych Up", NORMAL, 0, 10),
        MoveInfo(245, "Extreme Speed", NORMAL, 80, 5),
        MoveInfo(246, "Ancient Power", ROCK, 60, 5),
        MoveInfo(247, "Shadow Ball", GHOST, 80, 15),
        MoveInfo(248, "Future Sight", PSYCHIC_T, 80, 15),
        MoveInfo(249, "Rock Smash", FIGHTING, 20, 15),
        MoveInfo(250, "Whirlpool", WATER, 15, 15),
        MoveInfo(251, "Beat Up", DARK, 10, 10),
        MoveInfo(252, "Fake Out", NORMAL, 40, 10),
        MoveInfo(253, "Uproar", NORMAL, 50, 10),
        MoveInfo(254, "Stockpile", NORMAL, 0, 10),
        MoveInfo(255, "Spit Up", NORMAL, 100, 10),
        MoveInfo(256, "Swallow", NORMAL, 0, 10),
        MoveInfo(257, "Heat Wave", FIRE, 100, 10),
        MoveInfo(258, "Hail", ICE, 0, 10),
        MoveInfo(259, "Torment", DARK, 0, 15),
        MoveInfo(260, "Flatter", DARK, 0, 15),
        MoveInfo(261, "Will O Wisp", FIRE, 0, 15),
        MoveInfo(262, "Memento", DARK, 0, 10),
        MoveInfo(263, "Facade", NORMAL, 70, 20),
        MoveInfo(264, "Focus Punch", FIGHTING, 150, 20),
        MoveInfo(265, "Smelling Salt", NORMAL, 60, 10),
        MoveInfo(266, "Follow Me", NORMAL, 0, 20),
        MoveInfo(267, "Nature Power", NORMAL, 0, 20),
        MoveInfo(268, "Charge", ELECTRIC, 0, 20),
        MoveInfo(269, "Taunt", DARK, 0, 20),
        MoveInfo(270, "Helping Hand", NORMAL, 0, 20),
        MoveInfo(271, "Trick", PSYCHIC_T, 0, 10),
        MoveInfo(272, "Role Play", PSYCHIC_T, 0, 10),
        MoveInfo(273, "Wish", NORMAL, 0, 10),
        MoveInfo(274, "Assist", NORMAL, 0, 20),
        MoveInfo(275, "Ingrain", GRASS, 0, 20),
        MoveInfo(276, "Superpower", FIGHTING, 120, 5),
        MoveInfo(277, "Magic Coat", PSYCHIC_T, 0, 15),
        MoveInfo(278, "Recycle", NORMAL, 0, 10),
        MoveInfo(279, "Revenge", FIGHTING, 60, 10),
        MoveInfo(280, "Brick Break", FIGHTING, 75, 15),
        MoveInfo(281, "Yawn", NORMAL, 0, 10),
        MoveInfo(282, "Knock Off", DARK, 20, 20),
        MoveInfo(283, "Endeavor", NORMAL, 1, 5),
        MoveInfo(284, "Eruption", FIRE, 150, 5),
        MoveInfo(285, "Skill Swap", PSYCHIC_T, 0, 10),
        MoveInfo(286, "Imprison", PSYCHIC_T, 0, 10),
        MoveInfo(287, "Refresh", NORMAL, 0, 20),
        MoveInfo(288, "Grudge", GHOST, 0, 5),
        MoveInfo(289, "Snatch", DARK, 0, 10),
        MoveInfo(290, "Secret Power", NORMAL, 70, 20),
        MoveInfo(291, "Dive", WATER, 60, 10),
        MoveInfo(292, "Arm Thrust", FIGHTING, 15, 20),
        MoveInfo(293, "Camouflage", NORMAL, 0, 20),
        MoveInfo(294, "Tail Glow", BUG, 0, 20),
        MoveInfo(295, "Luster Purge", PSYCHIC_T, 70, 5),
        MoveInfo(296, "Mist Ball", PSYCHIC_T, 70, 5),
        MoveInfo(297, "Feather Dance", FLYING, 0, 15),
        MoveInfo(298, "Teeter Dance", NORMAL, 0, 20),
        MoveInfo(299, "Blaze Kick", FIRE, 85, 10),
        MoveInfo(300, "Mud Sport", GROUND, 0, 15),
        MoveInfo(301, "Ice Ball", ICE, 30, 20),
        MoveInfo(302, "Needle Arm", GRASS, 60, 15),
        MoveInfo(303, "Slack Off", NORMAL, 0, 10),
        MoveInfo(304, "Hyper Voice", NORMAL, 90, 10),
        MoveInfo(305, "Poison Fang", POISON, 50, 15),
        MoveInfo(306, "Crush Claw", NORMAL, 75, 10),
        MoveInfo(307, "Blast Burn", FIRE, 150, 5),
        MoveInfo(308, "Hydro Cannon", WATER, 150, 5),
        MoveInfo(309, "Meteor Mash", STEEL, 100, 10),
        MoveInfo(310, "Astonish", GHOST, 30, 15),
        MoveInfo(311, "Weather Ball", NORMAL, 50, 10),
        MoveInfo(312, "Aromatherapy", GRASS, 0, 5),
        MoveInfo(313, "Fake Tears", DARK, 0, 20),
        MoveInfo(314, "Air Cutter", FLYING, 55, 25),
        MoveInfo(315, "Overheat", FIRE, 140, 5),
        MoveInfo(316, "Odor Sleuth", NORMAL, 0, 40),
        MoveInfo(317, "Rock Tomb", ROCK, 50, 10),
        MoveInfo(318, "Silver Wind", BUG, 60, 5),
        MoveInfo(319, "Metal Sound", STEEL, 0, 40),
        MoveInfo(320, "Grass Whistle", GRASS, 0, 15),
        MoveInfo(321, "Tickle", NORMAL, 0, 20),
        MoveInfo(322, "Cosmic Power", PSYCHIC_T, 0, 20),
        MoveInfo(323, "Water Spout", WATER, 150, 5),
        MoveInfo(324, "Signal Beam", BUG, 75, 15),
        MoveInfo(325, "Shadow Punch", GHOST, 60, 20),
        MoveInfo(326, "Extrasensory", PSYCHIC_T, 80, 30),
        MoveInfo(327, "Sky Uppercut", FIGHTING, 85, 15),
        MoveInfo(328, "Sand Tomb", GROUND, 15, 15),
        MoveInfo(329, "Sheer Cold", ICE, 1, 5),
        MoveInfo(330, "Muddy Water", WATER, 95, 10),
        MoveInfo(331, "Bullet Seed", GRASS, 10, 30),
        MoveInfo(332, "Aerial Ace", FLYING, 60, 20),
        MoveInfo(333, "Icicle Spear", ICE, 10, 30),
        MoveInfo(334, "Iron Defense", STEEL, 0, 15),
        MoveInfo(335, "Block", NORMAL, 0, 5),
        MoveInfo(336, "Howl", NORMAL, 0, 40),
        MoveInfo(337, "Dragon Claw", DRAGON, 80, 15),
        MoveInfo(338, "Frenzy Plant", GRASS, 150, 5),
        MoveInfo(339, "Bulk Up", FIGHTING, 0, 20),
        MoveInfo(340, "Bounce", FLYING, 85, 5),
        MoveInfo(341, "Mud Shot", GROUND, 55, 15),
        MoveInfo(342, "Poison Tail", POISON, 50, 25),
        MoveInfo(343, "Covet", NORMAL, 40, 40),
        MoveInfo(344, "Volt Tackle", ELECTRIC, 120, 15),
        MoveInfo(345, "Magical Leaf", GRASS, 60, 20),
        MoveInfo(346, "Water Sport", WATER, 0, 15),
        MoveInfo(347, "Calm Mind", PSYCHIC_T, 0, 20),
        MoveInfo(348, "Leaf Blade", GRASS, 70, 15),
        MoveInfo(349, "Dragon Dance", DRAGON, 0, 20),
        MoveInfo(350, "Rock Blast", ROCK, 25, 10),
        MoveInfo(351, "Shock Wave", ELECTRIC, 60, 20),
        MoveInfo(352, "Water Pulse", WATER, 60, 20),
        MoveInfo(353, "Doom Desire", STEEL, 120, 5),
        MoveInfo(354, "Psycho Boost", PSYCHIC_T, 140, 5),
    ]
}


def move_info(move_id: int) -> MoveInfo | None:
    return MOVES.get(move_id)


def move_name(move_id: int) -> str:
    m = MOVES.get(move_id)
    return m.name if m else (f"Move {move_id}" if move_id else "-")


# --- Species typings (Gen 3 internal species ids; Kanto 1-151 == National Dex) ---
# From pokefirered src/data/pokemon/species_info.h. Mono-typed species (which the
# ROM stores as the same type twice) use None in the second slot.
SPECIES_TYPES: dict[int, tuple[int, int | None]] = {
    1: (GRASS, POISON),  # Bulbasaur
    2: (GRASS, POISON),  # Ivysaur
    3: (GRASS, POISON),  # Venusaur
    4: (FIRE, None),  # Charmander
    5: (FIRE, None),  # Charmeleon
    6: (FIRE, FLYING),  # Charizard
    7: (WATER, None),  # Squirtle
    8: (WATER, None),  # Wartortle
    9: (WATER, None),  # Blastoise
    10: (BUG, None),  # Caterpie
    11: (BUG, None),  # Metapod
    12: (BUG, FLYING),  # Butterfree
    13: (BUG, POISON),  # Weedle
    14: (BUG, POISON),  # Kakuna
    15: (BUG, POISON),  # Beedrill
    16: (NORMAL, FLYING),  # Pidgey
    17: (NORMAL, FLYING),  # Pidgeotto
    18: (NORMAL, FLYING),  # Pidgeot
    19: (NORMAL, None),  # Rattata
    20: (NORMAL, None),  # Raticate
    21: (NORMAL, FLYING),  # Spearow
    22: (NORMAL, FLYING),  # Fearow
    23: (POISON, None),  # Ekans
    24: (POISON, None),  # Arbok
    25: (ELECTRIC, None),  # Pikachu
    26: (ELECTRIC, None),  # Raichu
    27: (GROUND, None),  # Sandshrew
    28: (GROUND, None),  # Sandslash
    29: (POISON, None),  # Nidoran-F
    30: (POISON, None),  # Nidorina
    31: (POISON, GROUND),  # Nidoqueen
    32: (POISON, None),  # Nidoran-M
    33: (POISON, None),  # Nidorino
    34: (POISON, GROUND),  # Nidoking
    35: (NORMAL, None),  # Clefairy
    36: (NORMAL, None),  # Clefable
    37: (FIRE, None),  # Vulpix
    38: (FIRE, None),  # Ninetales
    39: (NORMAL, None),  # Jigglypuff
    40: (NORMAL, None),  # Wigglytuff
    41: (POISON, FLYING),  # Zubat
    42: (POISON, FLYING),  # Golbat
    43: (GRASS, POISON),  # Oddish
    44: (GRASS, POISON),  # Gloom
    45: (GRASS, POISON),  # Vileplume
    46: (BUG, GRASS),  # Paras
    47: (BUG, GRASS),  # Parasect
    48: (BUG, POISON),  # Venonat
    49: (BUG, POISON),  # Venomoth
    50: (GROUND, None),  # Diglett
    51: (GROUND, None),  # Dugtrio
    52: (NORMAL, None),  # Meowth
    53: (NORMAL, None),  # Persian
    54: (WATER, None),  # Psyduck
    55: (WATER, None),  # Golduck
    56: (FIGHTING, None),  # Mankey
    57: (FIGHTING, None),  # Primeape
    58: (FIRE, None),  # Growlithe
    59: (FIRE, None),  # Arcanine
    60: (WATER, None),  # Poliwag
    61: (WATER, None),  # Poliwhirl
    62: (WATER, FIGHTING),  # Poliwrath
    63: (PSYCHIC_T, None),  # Abra
    64: (PSYCHIC_T, None),  # Kadabra
    65: (PSYCHIC_T, None),  # Alakazam
    66: (FIGHTING, None),  # Machop
    67: (FIGHTING, None),  # Machoke
    68: (FIGHTING, None),  # Machamp
    69: (GRASS, POISON),  # Bellsprout
    70: (GRASS, POISON),  # Weepinbell
    71: (GRASS, POISON),  # Victreebel
    72: (WATER, POISON),  # Tentacool
    73: (WATER, POISON),  # Tentacruel
    74: (ROCK, GROUND),  # Geodude
    75: (ROCK, GROUND),  # Graveler
    76: (ROCK, GROUND),  # Golem
    77: (FIRE, None),  # Ponyta
    78: (FIRE, None),  # Rapidash
    79: (WATER, PSYCHIC_T),  # Slowpoke
    80: (WATER, PSYCHIC_T),  # Slowbro
    81: (ELECTRIC, STEEL),  # Magnemite
    82: (ELECTRIC, STEEL),  # Magneton
    83: (NORMAL, FLYING),  # Farfetch'd
    84: (NORMAL, FLYING),  # Doduo
    85: (NORMAL, FLYING),  # Dodrio
    86: (WATER, None),  # Seel
    87: (WATER, ICE),  # Dewgong
    88: (POISON, None),  # Grimer
    89: (POISON, None),  # Muk
    90: (WATER, None),  # Shellder
    91: (WATER, ICE),  # Cloyster
    92: (GHOST, POISON),  # Gastly
    93: (GHOST, POISON),  # Haunter
    94: (GHOST, POISON),  # Gengar
    95: (ROCK, GROUND),  # Onix
    96: (PSYCHIC_T, None),  # Drowzee
    97: (PSYCHIC_T, None),  # Hypno
    98: (WATER, None),  # Krabby
    99: (WATER, None),  # Kingler
    100: (ELECTRIC, None),  # Voltorb
    101: (ELECTRIC, None),  # Electrode
    102: (GRASS, PSYCHIC_T),  # Exeggcute
    103: (GRASS, PSYCHIC_T),  # Exeggutor
    104: (GROUND, None),  # Cubone
    105: (GROUND, None),  # Marowak
    106: (FIGHTING, None),  # Hitmonlee
    107: (FIGHTING, None),  # Hitmonchan
    108: (NORMAL, None),  # Lickitung
    109: (POISON, None),  # Koffing
    110: (POISON, None),  # Weezing
    111: (GROUND, ROCK),  # Rhyhorn
    112: (GROUND, ROCK),  # Rhydon
    113: (NORMAL, None),  # Chansey
    114: (GRASS, None),  # Tangela
    115: (NORMAL, None),  # Kangaskhan
    116: (WATER, None),  # Horsea
    117: (WATER, None),  # Seadra
    118: (WATER, None),  # Goldeen
    119: (WATER, None),  # Seaking
    120: (WATER, None),  # Staryu
    121: (WATER, PSYCHIC_T),  # Starmie
    122: (PSYCHIC_T, None),  # Mr. Mime
    123: (BUG, FLYING),  # Scyther
    124: (ICE, PSYCHIC_T),  # Jynx
    125: (ELECTRIC, None),  # Electabuzz
    126: (FIRE, None),  # Magmar
    127: (BUG, None),  # Pinsir
    128: (NORMAL, None),  # Tauros
    129: (WATER, None),  # Magikarp
    130: (WATER, FLYING),  # Gyarados
    131: (WATER, ICE),  # Lapras
    132: (NORMAL, None),  # Ditto
    133: (NORMAL, None),  # Eevee
    134: (WATER, None),  # Vaporeon
    135: (ELECTRIC, None),  # Jolteon
    136: (FIRE, None),  # Flareon
    137: (NORMAL, None),  # Porygon
    138: (ROCK, WATER),  # Omanyte
    139: (ROCK, WATER),  # Omastar
    140: (ROCK, WATER),  # Kabuto
    141: (ROCK, WATER),  # Kabutops
    142: (ROCK, FLYING),  # Aerodactyl
    143: (NORMAL, None),  # Snorlax
    144: (ICE, FLYING),  # Articuno
    145: (ELECTRIC, FLYING),  # Zapdos
    146: (FIRE, FLYING),  # Moltres
    147: (DRAGON, None),  # Dratini
    148: (DRAGON, None),  # Dragonair
    149: (DRAGON, FLYING),  # Dragonite
    150: (PSYCHIC_T, None),  # Mewtwo
    151: (PSYCHIC_T, None),  # Mew
}


def species_types(species_id: int) -> tuple[int, int | None] | None:
    """(type1, type2 | None) for a species id, or None if unknown."""
    return SPECIES_TYPES.get(species_id)


@dataclass(frozen=True)
class MoveScore:
    """One scored move slot, with the reasoning the dashboard displays."""

    slot: int
    move_id: int
    name: str
    type_id: int
    power: int
    pp_left: int
    multiplier: float  # type effectiveness vs the enemy
    stab: float  # 1.5 if move type matches an attacker type
    score: float  # power * multiplier * stab (0 for status / no-PP moves)

    @property
    def effectiveness_label(self) -> str:
        if self.power == 0:
            return "status"
        if self.multiplier == 0:
            return "no effect"
        if self.multiplier >= 4:
            return "x4 devastating"
        if self.multiplier >= 2:
            return "super effective"
        if self.multiplier <= 0.25:
            return "x1/4 barely effective"
        if self.multiplier < 1:
            return "not very effective"
        return "effective"


def score_moves(
    moves: tuple[int, int, int, int] | list[int],
    pp: tuple[int, int, int, int] | list[int],
    attacker_type1: int,
    attacker_type2: int | None,
    enemy_type1: int,
    enemy_type2: int | None,
) -> list[MoveScore]:
    """Score each occupied move slot against the enemy's typing.

    Score = power x type multiplier x STAB. Status moves and empty/0-PP slots
    score 0 (they are still listed so the dashboard can show the whole moveset).
    """
    scores: list[MoveScore] = []
    for slot, move_id in enumerate(moves):
        if move_id == 0:
            continue
        info = MOVES.get(move_id)
        if info is None:
            # Unknown move id (glitch data): list it but never pick it.
            scores.append(MoveScore(slot, move_id, move_name(move_id), 0, 0, 0, 1.0, 1.0, 0.0))
            continue
        pp_left = pp[slot]  # Gen 3: plain byte, no PP-Up bits to mask
        mult = effectiveness(info.type_id, enemy_type1, enemy_type2)
        stab = 1.5 if info.type_id in (attacker_type1, attacker_type2) else 1.0
        usable = info.power > 0 and pp_left > 0
        score = info.power * mult * stab if usable else 0.0
        scores.append(
            MoveScore(
                slot=slot,
                move_id=move_id,
                name=info.name,
                type_id=info.type_id,
                power=info.power,
                pp_left=pp_left,
                multiplier=mult,
                stab=stab,
                score=score,
            )
        )
    return scores


def best_move(scores: list[MoveScore]) -> MoveScore | None:
    """Highest-scoring damaging move with PP, or None if nothing is usable."""
    usable = [s for s in scores if s.score > 0]
    if not usable:
        return None
    return max(usable, key=lambda s: s.score)
