"""Gen 1 battle knowledge: type effectiveness chart + move data.

Sources: pret/pokered disassembly (TypeEffects table, moves.asm), Bulbapedia
"List of moves" Gen 1 values. Includes Gen 1 quirks that differ from later
generations: Bug/Poison are super-effective against each other, Ghost does
NOT hit Psychic (the famous bug), Ice is neutral against Fire, and
Bite/Gust/Karate Chop/Sand Attack are Normal-type.

Type IDs are the Gen 1 internal IDs used in RAM (see game_data.TYPE_NAMES).
Move IDs are the Gen 1 internal move indices stored in party data.

Pure data + scoring logic; no emulator dependency (testable without a ROM).
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Type IDs (Gen 1 internal) ---
NORMAL = 0x00
FIGHTING = 0x01
FLYING = 0x02
POISON = 0x03
GROUND = 0x04
ROCK = 0x05
BUG = 0x07
GHOST = 0x08
FIRE = 0x14
WATER = 0x15
GRASS = 0x16
ELECTRIC = 0x17
PSYCHIC_T = 0x18
ICE = 0x19
DRAGON = 0x1A

# --- Effectiveness: (attack_type, defend_type) -> multiplier ---
# Pairs not listed are neutral (1.0). Mirrors pokered's TypeEffects table.
_EFFECT: dict[tuple[int, int], float] = {
    (NORMAL, ROCK): 0.5,
    (NORMAL, GHOST): 0.0,
    (FIGHTING, NORMAL): 2.0,
    (FIGHTING, FLYING): 0.5,
    (FIGHTING, POISON): 0.5,
    (FIGHTING, ROCK): 2.0,
    (FIGHTING, BUG): 0.5,
    (FIGHTING, GHOST): 0.0,
    (FIGHTING, PSYCHIC_T): 0.5,
    (FIGHTING, ICE): 2.0,
    (FLYING, FIGHTING): 2.0,
    (FLYING, ROCK): 0.5,
    (FLYING, BUG): 2.0,
    (FLYING, GRASS): 2.0,
    (FLYING, ELECTRIC): 0.5,
    (POISON, POISON): 0.5,
    (POISON, GROUND): 0.5,
    (POISON, ROCK): 0.5,
    (POISON, BUG): 2.0,  # Gen 1 only
    (POISON, GHOST): 0.5,
    (POISON, GRASS): 2.0,
    (GROUND, FLYING): 0.0,
    (GROUND, POISON): 2.0,
    (GROUND, ROCK): 2.0,
    (GROUND, BUG): 0.5,
    (GROUND, FIRE): 2.0,
    (GROUND, GRASS): 0.5,
    (GROUND, ELECTRIC): 2.0,
    (ROCK, FIGHTING): 0.5,
    (ROCK, FLYING): 2.0,
    (ROCK, GROUND): 0.5,
    (ROCK, BUG): 2.0,
    (ROCK, FIRE): 2.0,
    (ROCK, ICE): 2.0,
    (BUG, FIGHTING): 0.5,
    (BUG, FLYING): 0.5,
    (BUG, POISON): 2.0,  # Gen 1 only
    (BUG, GHOST): 0.5,
    (BUG, FIRE): 0.5,
    (BUG, GRASS): 2.0,
    (BUG, PSYCHIC_T): 2.0,
    (GHOST, NORMAL): 0.0,
    (GHOST, GHOST): 2.0,
    (GHOST, PSYCHIC_T): 0.0,  # Gen 1 bug: Ghost does not affect Psychic
    (FIRE, ROCK): 0.5,
    (FIRE, BUG): 2.0,
    (FIRE, FIRE): 0.5,
    (FIRE, WATER): 0.5,
    (FIRE, GRASS): 2.0,
    (FIRE, ICE): 2.0,
    (FIRE, DRAGON): 0.5,
    (WATER, GROUND): 2.0,
    (WATER, ROCK): 2.0,
    (WATER, FIRE): 2.0,
    (WATER, WATER): 0.5,
    (WATER, GRASS): 0.5,
    (WATER, DRAGON): 0.5,
    (GRASS, FLYING): 0.5,
    (GRASS, POISON): 0.5,
    (GRASS, GROUND): 2.0,
    (GRASS, ROCK): 2.0,
    (GRASS, BUG): 0.5,
    (GRASS, FIRE): 0.5,
    (GRASS, WATER): 2.0,
    (GRASS, GRASS): 0.5,
    (GRASS, DRAGON): 0.5,
    (ELECTRIC, FLYING): 2.0,
    (ELECTRIC, GROUND): 0.0,
    (ELECTRIC, WATER): 2.0,
    (ELECTRIC, GRASS): 0.5,
    (ELECTRIC, ELECTRIC): 0.5,
    (ELECTRIC, DRAGON): 0.5,
    (PSYCHIC_T, FIGHTING): 2.0,
    (PSYCHIC_T, POISON): 2.0,
    (PSYCHIC_T, PSYCHIC_T): 0.5,
    (ICE, FLYING): 2.0,
    (ICE, GROUND): 2.0,
    (ICE, WATER): 0.5,
    (ICE, GRASS): 2.0,
    (ICE, ICE): 0.5,
    (ICE, DRAGON): 2.0,
    (DRAGON, DRAGON): 2.0,
}


def effectiveness(attack_type: int, defend_type1: int, defend_type2: int) -> float:
    """Combined type multiplier of an attack against a (possibly dual-typed)
    defender. A mono-type defender stores the same ID in both slots."""
    mult = _EFFECT.get((attack_type, defend_type1), 1.0)
    if defend_type2 != defend_type1:
        mult *= _EFFECT.get((attack_type, defend_type2), 1.0)
    return mult


@dataclass(frozen=True)
class MoveInfo:
    move_id: int
    name: str
    type_id: int
    power: int  # 0 = status move; fixed-damage moves use a representative value
    pp: int


# --- Gen 1 move table (id -> name, type, power, max PP) ---
# Power/PP are Gen 1 values. Fixed/variable-damage moves (Seismic Toss, Night
# Shade, Dragon Rage, Sonic Boom, Super Fang, Psywave, Counter, Bide) carry a
# representative power so the scorer ranks them reasonably.
MOVES: dict[int, MoveInfo] = {
    m.move_id: m
    for m in [
        MoveInfo(0x01, "Pound", NORMAL, 40, 35),
        MoveInfo(0x02, "Karate Chop", NORMAL, 50, 25),
        MoveInfo(0x03, "Double Slap", NORMAL, 15, 10),
        MoveInfo(0x04, "Comet Punch", NORMAL, 18, 15),
        MoveInfo(0x05, "Mega Punch", NORMAL, 80, 20),
        MoveInfo(0x06, "Pay Day", NORMAL, 40, 20),
        MoveInfo(0x07, "Fire Punch", FIRE, 75, 15),
        MoveInfo(0x08, "Ice Punch", ICE, 75, 15),
        MoveInfo(0x09, "Thunder Punch", ELECTRIC, 75, 15),
        MoveInfo(0x0A, "Scratch", NORMAL, 40, 35),
        MoveInfo(0x0B, "Vice Grip", NORMAL, 55, 30),
        MoveInfo(0x0C, "Guillotine", NORMAL, 0, 5),
        MoveInfo(0x0D, "Razor Wind", NORMAL, 80, 10),
        MoveInfo(0x0E, "Swords Dance", NORMAL, 0, 30),
        MoveInfo(0x0F, "Cut", NORMAL, 50, 30),
        MoveInfo(0x10, "Gust", NORMAL, 40, 35),
        MoveInfo(0x11, "Wing Attack", FLYING, 35, 35),
        MoveInfo(0x12, "Whirlwind", NORMAL, 0, 20),
        MoveInfo(0x13, "Fly", FLYING, 70, 15),
        MoveInfo(0x14, "Bind", NORMAL, 15, 20),
        MoveInfo(0x15, "Slam", NORMAL, 80, 20),
        MoveInfo(0x16, "Vine Whip", GRASS, 35, 10),
        MoveInfo(0x17, "Stomp", NORMAL, 65, 20),
        MoveInfo(0x18, "Double Kick", FIGHTING, 30, 30),
        MoveInfo(0x19, "Mega Kick", NORMAL, 120, 5),
        MoveInfo(0x1A, "Jump Kick", FIGHTING, 70, 25),
        MoveInfo(0x1B, "Rolling Kick", FIGHTING, 60, 15),
        MoveInfo(0x1C, "Sand Attack", NORMAL, 0, 15),
        MoveInfo(0x1D, "Headbutt", NORMAL, 70, 15),
        MoveInfo(0x1E, "Horn Attack", NORMAL, 65, 25),
        MoveInfo(0x1F, "Fury Attack", NORMAL, 15, 20),
        MoveInfo(0x20, "Horn Drill", NORMAL, 0, 5),
        MoveInfo(0x21, "Tackle", NORMAL, 35, 35),
        MoveInfo(0x22, "Body Slam", NORMAL, 85, 15),
        MoveInfo(0x23, "Wrap", NORMAL, 15, 20),
        MoveInfo(0x24, "Take Down", NORMAL, 90, 20),
        MoveInfo(0x25, "Thrash", NORMAL, 90, 20),
        MoveInfo(0x26, "Double-Edge", NORMAL, 100, 15),
        MoveInfo(0x27, "Tail Whip", NORMAL, 0, 30),
        MoveInfo(0x28, "Poison Sting", POISON, 15, 35),
        MoveInfo(0x29, "Twineedle", BUG, 25, 20),
        MoveInfo(0x2A, "Pin Missile", BUG, 14, 20),
        MoveInfo(0x2B, "Leer", NORMAL, 0, 30),
        MoveInfo(0x2C, "Bite", NORMAL, 60, 25),
        MoveInfo(0x2D, "Growl", NORMAL, 0, 40),
        MoveInfo(0x2E, "Roar", NORMAL, 0, 20),
        MoveInfo(0x2F, "Sing", NORMAL, 0, 15),
        MoveInfo(0x30, "Supersonic", NORMAL, 0, 20),
        MoveInfo(0x31, "Sonic Boom", NORMAL, 20, 20),
        MoveInfo(0x32, "Disable", NORMAL, 0, 20),
        MoveInfo(0x33, "Acid", POISON, 40, 30),
        MoveInfo(0x34, "Ember", FIRE, 40, 25),
        MoveInfo(0x35, "Flamethrower", FIRE, 95, 15),
        MoveInfo(0x36, "Mist", ICE, 0, 30),
        MoveInfo(0x37, "Water Gun", WATER, 40, 25),
        MoveInfo(0x38, "Hydro Pump", WATER, 120, 5),
        MoveInfo(0x39, "Surf", WATER, 95, 15),
        MoveInfo(0x3A, "Ice Beam", ICE, 95, 10),
        MoveInfo(0x3B, "Blizzard", ICE, 120, 5),
        MoveInfo(0x3C, "Psybeam", PSYCHIC_T, 65, 20),
        MoveInfo(0x3D, "Bubble Beam", WATER, 65, 20),
        MoveInfo(0x3E, "Aurora Beam", ICE, 65, 20),
        MoveInfo(0x3F, "Hyper Beam", NORMAL, 150, 5),
        MoveInfo(0x40, "Peck", FLYING, 35, 35),
        MoveInfo(0x41, "Drill Peck", FLYING, 80, 20),
        MoveInfo(0x42, "Submission", FIGHTING, 80, 25),
        MoveInfo(0x43, "Low Kick", FIGHTING, 50, 20),
        MoveInfo(0x44, "Counter", FIGHTING, 0, 20),
        MoveInfo(0x45, "Seismic Toss", FIGHTING, 40, 20),
        MoveInfo(0x46, "Strength", NORMAL, 80, 15),
        MoveInfo(0x47, "Absorb", GRASS, 20, 20),
        MoveInfo(0x48, "Mega Drain", GRASS, 40, 10),
        MoveInfo(0x49, "Leech Seed", GRASS, 0, 10),
        MoveInfo(0x4A, "Growth", NORMAL, 0, 40),
        MoveInfo(0x4B, "Razor Leaf", GRASS, 55, 25),
        MoveInfo(0x4C, "Solar Beam", GRASS, 120, 10),
        MoveInfo(0x4D, "Poison Powder", POISON, 0, 35),
        MoveInfo(0x4E, "Stun Spore", GRASS, 0, 30),
        MoveInfo(0x4F, "Sleep Powder", GRASS, 0, 15),
        MoveInfo(0x50, "Petal Dance", GRASS, 70, 20),
        MoveInfo(0x51, "String Shot", BUG, 0, 40),
        MoveInfo(0x52, "Dragon Rage", DRAGON, 40, 10),
        MoveInfo(0x53, "Fire Spin", FIRE, 15, 15),
        MoveInfo(0x54, "Thunder Shock", ELECTRIC, 40, 30),
        MoveInfo(0x55, "Thunderbolt", ELECTRIC, 95, 15),
        MoveInfo(0x56, "Thunder Wave", ELECTRIC, 0, 20),
        MoveInfo(0x57, "Thunder", ELECTRIC, 120, 10),
        MoveInfo(0x58, "Rock Throw", ROCK, 50, 15),
        MoveInfo(0x59, "Earthquake", GROUND, 100, 10),
        MoveInfo(0x5A, "Fissure", GROUND, 0, 5),
        MoveInfo(0x5B, "Dig", GROUND, 100, 10),
        MoveInfo(0x5C, "Toxic", POISON, 0, 10),
        MoveInfo(0x5D, "Confusion", PSYCHIC_T, 50, 25),
        MoveInfo(0x5E, "Psychic", PSYCHIC_T, 90, 10),
        MoveInfo(0x5F, "Hypnosis", PSYCHIC_T, 0, 20),
        MoveInfo(0x60, "Meditate", PSYCHIC_T, 0, 40),
        MoveInfo(0x61, "Agility", PSYCHIC_T, 0, 30),
        MoveInfo(0x62, "Quick Attack", NORMAL, 40, 30),
        MoveInfo(0x63, "Rage", NORMAL, 20, 20),
        MoveInfo(0x64, "Teleport", PSYCHIC_T, 0, 20),
        MoveInfo(0x65, "Night Shade", GHOST, 40, 15),
        MoveInfo(0x66, "Mimic", NORMAL, 0, 10),
        MoveInfo(0x67, "Screech", NORMAL, 0, 40),
        MoveInfo(0x68, "Double Team", NORMAL, 0, 15),
        MoveInfo(0x69, "Recover", NORMAL, 0, 20),
        MoveInfo(0x6A, "Harden", NORMAL, 0, 30),
        MoveInfo(0x6B, "Minimize", NORMAL, 0, 20),
        MoveInfo(0x6C, "Smokescreen", NORMAL, 0, 20),
        MoveInfo(0x6D, "Confuse Ray", GHOST, 0, 10),
        MoveInfo(0x6E, "Withdraw", WATER, 0, 40),
        MoveInfo(0x6F, "Defense Curl", NORMAL, 0, 40),
        MoveInfo(0x70, "Barrier", PSYCHIC_T, 0, 30),
        MoveInfo(0x71, "Light Screen", PSYCHIC_T, 0, 30),
        MoveInfo(0x72, "Haze", ICE, 0, 30),
        MoveInfo(0x73, "Reflect", PSYCHIC_T, 0, 20),
        MoveInfo(0x74, "Focus Energy", NORMAL, 0, 30),
        MoveInfo(0x75, "Bide", NORMAL, 0, 10),
        MoveInfo(0x76, "Metronome", NORMAL, 0, 10),
        MoveInfo(0x77, "Mirror Move", FLYING, 0, 20),
        MoveInfo(0x78, "Self-Destruct", NORMAL, 130, 5),
        MoveInfo(0x79, "Egg Bomb", NORMAL, 100, 10),
        MoveInfo(0x7A, "Lick", GHOST, 20, 30),
        MoveInfo(0x7B, "Smog", POISON, 20, 20),
        MoveInfo(0x7C, "Sludge", POISON, 65, 20),
        MoveInfo(0x7D, "Bone Club", GROUND, 65, 20),
        MoveInfo(0x7E, "Fire Blast", FIRE, 120, 5),
        MoveInfo(0x7F, "Waterfall", WATER, 80, 15),
        MoveInfo(0x80, "Clamp", WATER, 35, 10),
        MoveInfo(0x81, "Swift", NORMAL, 60, 20),
        MoveInfo(0x82, "Skull Bash", NORMAL, 100, 15),
        MoveInfo(0x83, "Spike Cannon", NORMAL, 20, 15),
        MoveInfo(0x84, "Constrict", NORMAL, 10, 35),
        MoveInfo(0x85, "Amnesia", PSYCHIC_T, 0, 20),
        MoveInfo(0x86, "Kinesis", PSYCHIC_T, 0, 15),
        MoveInfo(0x87, "Soft-Boiled", NORMAL, 0, 10),
        MoveInfo(0x88, "Hi Jump Kick", FIGHTING, 85, 20),
        MoveInfo(0x89, "Glare", NORMAL, 0, 30),
        MoveInfo(0x8A, "Dream Eater", PSYCHIC_T, 100, 15),
        MoveInfo(0x8B, "Poison Gas", POISON, 0, 40),
        MoveInfo(0x8C, "Barrage", NORMAL, 15, 20),
        MoveInfo(0x8D, "Leech Life", BUG, 20, 15),
        MoveInfo(0x8E, "Lovely Kiss", NORMAL, 0, 10),
        MoveInfo(0x8F, "Sky Attack", FLYING, 140, 5),
        MoveInfo(0x90, "Transform", NORMAL, 0, 10),
        MoveInfo(0x91, "Bubble", WATER, 20, 30),
        MoveInfo(0x92, "Dizzy Punch", NORMAL, 70, 10),
        MoveInfo(0x93, "Spore", GRASS, 0, 15),
        MoveInfo(0x94, "Flash", NORMAL, 0, 20),
        MoveInfo(0x95, "Psywave", PSYCHIC_T, 30, 15),
        MoveInfo(0x96, "Splash", NORMAL, 0, 40),
        MoveInfo(0x97, "Acid Armor", POISON, 0, 40),
        MoveInfo(0x98, "Crabhammer", WATER, 90, 10),
        MoveInfo(0x99, "Explosion", NORMAL, 170, 5),
        MoveInfo(0x9A, "Fury Swipes", NORMAL, 18, 15),
        MoveInfo(0x9B, "Bonemerang", GROUND, 50, 10),
        MoveInfo(0x9C, "Rest", PSYCHIC_T, 0, 10),
        MoveInfo(0x9D, "Rock Slide", ROCK, 75, 10),
        MoveInfo(0x9E, "Hyper Fang", NORMAL, 80, 15),
        MoveInfo(0x9F, "Sharpen", NORMAL, 0, 30),
        MoveInfo(0xA0, "Conversion", NORMAL, 0, 30),
        MoveInfo(0xA1, "Tri Attack", NORMAL, 80, 10),
        MoveInfo(0xA2, "Super Fang", NORMAL, 40, 10),
        MoveInfo(0xA3, "Slash", NORMAL, 70, 20),
        MoveInfo(0xA4, "Substitute", NORMAL, 0, 10),
        MoveInfo(0xA5, "Struggle", NORMAL, 50, 10),
    ]
}


def move_info(move_id: int) -> MoveInfo | None:
    return MOVES.get(move_id)


def move_name(move_id: int) -> str:
    m = MOVES.get(move_id)
    return m.name if m else (f"Move 0x{move_id:02X}" if move_id else "—")


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
            return "×4 devastating"
        if self.multiplier >= 2:
            return "super effective"
        if self.multiplier <= 0.25:
            return "×¼ barely effective"
        if self.multiplier < 1:
            return "not very effective"
        return "effective"


def score_moves(
    moves: tuple[int, int, int, int] | list[int],
    pp: tuple[int, int, int, int] | list[int],
    attacker_type1: int,
    attacker_type2: int,
    enemy_type1: int,
    enemy_type2: int,
) -> list[MoveScore]:
    """Score each occupied move slot against the enemy's typing.

    Score = power × type multiplier × STAB. Status moves and empty/0-PP slots
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
        pp_left = pp[slot] & 0x3F  # high bits store PP-Up count
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
