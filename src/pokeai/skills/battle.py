"""Battle skill v2 — type-aware move selection, multi-mon trainer battles,
in-battle potions, and RAM-honest verdicts (G7, 2026-07-05).

Ground truth (all live-verified):
  * gEnemyParty 0x0202402C (2026-07-02); 6 x 100-byte slots like gPlayerParty.
  * gActionSelectionCursor 0x02023FF8 (2026-07-03): 0=FIGHT 1=BAG 2=POKEMON
    3=RUN; menu detection = stability + normalize + probe (see menu_up).
  * gBattleTypeFlags 0x02022B4C (2026-07-05): bit 3 set = TRAINER battle
    (rival fight 0x1C vs wild 0x04). Trainers cannot be fled.
  * ACTIVE battler on both sides = the first non-fainted party slot (Gen 3
    sends in party order); slot-0 reads misreport once anything faints.

Move scoring uses knowledge/gen3_battle.py (decomp-sourced chart/moves/species)
over the Attacks-substruct decode; PP-less/status moves score 0 and the loop
falls back to slot 1. The v1 A-mash survives as `fight()` for scripted fights.
"""
from __future__ import annotations

import time

from pokeai.emulator.firered_state_reader import (
    GPLAYER_PARTY,
    GPLAYER_PARTY_COUNT,
    HEAL_ITEM_IDS,
    SLOT_CURHP_OFF,
    SLOT_LEVEL_OFF,
    SLOT_MAXHP_OFF,
    SLOT_SIZE,
    FireRedStateReader,
)
from pokeai.knowledge.gen3_battle import best_move, score_moves, species_types

GENEMY_PARTY = 0x0202402C     # gEnemyParty (BPRE)          [VERIFIED 2026-07-02]
ACTION_CURSOR = 0x02023FF8    # gActionSelectionCursor      [VERIFIED 2026-07-03]
GBATTLE_TYPE_FLAGS = 0x02022B4C  # bit 3 = trainer          [VERIFIED 2026-07-05]
# In-battle move menu is a 2x2 grid; moves 0..3 = TL TR BL BR.
_MOVE_PATHS = {0: (), 1: ("RIGHT",), 2: ("DOWN",), 3: ("DOWN", "RIGHT")}


def _slot_stats(b, base) -> tuple[int, int, int]:
    """(level, cur_hp, max_hp) from a party slot's unencrypted battle-stats."""
    return (b.read_byte(base + SLOT_LEVEL_OFF),
            b.read_u16(base + SLOT_CURHP_OFF),
            b.read_u16(base + SLOT_MAXHP_OFF))


def _valid_slot(b, base) -> bool:
    lvl = b.read_byte(base + SLOT_LEVEL_OFF)
    mx = b.read_u16(base + SLOT_MAXHP_OFF)
    return 1 <= lvl <= 100 and 0 < mx <= 999


class Battle:
    """Owns one battle: detect it, drive its menus, fight it, call the verdict."""

    def __init__(self, bridge, reader: FireRedStateReader | None = None,
                 ruleset=None):
        self.b = bridge
        self.reader = reader or FireRedStateReader(bridge)
        # Optional Nuzlocke ruleset (pokeai.rules.nuzlocke.NuzlockeRuleset).
        # When set + permadeath active, dead species are excluded from battle
        # participation and mid-battle heals are suppressed under no_battle_items.
        self.ruleset = ruleset

    # ---- side state -----------------------------------------------------
    def battle_type_flags(self) -> int:
        return self.b.read_u32(GBATTLE_TYPE_FLAGS)

    def is_trainer_battle(self) -> bool:
        return bool(self.battle_type_flags() & 8)

    def _party_count(self) -> int:
        return min(self.b.read_byte(GPLAYER_PARTY_COUNT), 6)

    def _ruleset_dead(self, slot: int) -> bool:
        """Whether the mon in this slot is a Nuzlocke permadeath casualty
        (excluded from battle participation). False when no ruleset is wired."""
        if self.ruleset is None:
            return False
        try:
            return self.ruleset.is_dead(self.reader.read_species(slot))
        except Exception:
            return False

    def enemy_species(self) -> int:
        """Species id of THEIR active battler (0 on any decode surprise). The
        Nuzlocke catch gate reads this to apply the dupes/species clauses."""
        try:
            base = GENEMY_PARTY + self.enemy_active_slot() * SLOT_SIZE
            return self.reader.read_species_at(base)
        except Exception:
            return 0

    def active_slot(self) -> int:
        """OUR active battler: the first non-fainted party slot. Under an
        active Nuzlocke ruleset, permadeath-dead species are skipped (a dead
        mon 'can no longer be used'), falling through to the next healthy slot."""
        for i in range(self._party_count()):
            if self.b.read_u16(GPLAYER_PARTY + i * SLOT_SIZE + SLOT_CURHP_OFF) > 0:
                if self._ruleset_dead(i):
                    continue
                return i
        return 0

    def my_stats(self) -> tuple[int, int, int]:
        return _slot_stats(self.b, GPLAYER_PARTY + self.active_slot() * SLOT_SIZE)

    def party_fainted_count(self) -> int:
        n = 0
        for i in range(self._party_count()):
            base = GPLAYER_PARTY + i * SLOT_SIZE
            if (self.b.read_u16(base + SLOT_MAXHP_OFF) > 0
                    and self.b.read_u16(base + SLOT_CURHP_OFF) == 0):
                n += 1
        return n

    def all_fainted(self) -> bool:
        cnt = self._party_count()
        return cnt > 0 and self.party_fainted_count() >= cnt

    def enemy_active_slot(self) -> int:
        """THEIR active battler: trainers send party order; wild = slot 0."""
        for i in range(6):
            base = GENEMY_PARTY + i * SLOT_SIZE
            if not _valid_slot(self.b, base):
                break
            if self.b.read_u16(base + SLOT_CURHP_OFF) > 0:
                return i
        return 0

    def enemy_stats(self) -> tuple[int, int, int]:
        return _slot_stats(self.b, GENEMY_PARTY + self.enemy_active_slot() * SLOT_SIZE)

    def enemy_alive_count(self) -> int:
        n = 0
        for i in range(6):
            base = GENEMY_PARTY + i * SLOT_SIZE
            if not _valid_slot(self.b, base):
                break
            if self.b.read_u16(base + SLOT_CURHP_OFF) > 0:
                n += 1
        return n

    def active(self) -> bool:
        """Battle engine has a live opponent loaded. NOTE: gEnemyParty is NOT
        cleared after a battle ends — pair with a control check (the strong
        three-signal test lives in confirm-style callers)."""
        lvl, hp, mx = _slot_stats(self.b, GENEMY_PARTY)
        alive_later = any(
            _valid_slot(self.b, GENEMY_PARTY + i * SLOT_SIZE)
            and self.b.read_u16(GENEMY_PARTY + i * SLOT_SIZE + SLOT_CURHP_OFF) > 0
            for i in range(6))
        return (1 <= lvl <= 100 and mx <= 999 and alive_later)

    # ---- battle-menu machinery (moved here from Catch in v2) -------------
    def menu_up(self) -> bool:
        """True iff the action menu is up and accepting input. Normalize-first
        (2026-07-05): LEFT+UP parks a live menu on FIGHT from ANY rest
        position; verify by RAM (cursor==0), then probe RIGHT->1, restore."""
        r0 = self.b.read_byte(ACTION_CURSOR); time.sleep(0.3)
        if self.b.read_byte(ACTION_CURSOR) != r0:
            return False
        self.b.tap("LEFT", 5); time.sleep(0.25)
        self.b.tap("UP", 5); time.sleep(0.25)
        if self.b.read_byte(ACTION_CURSOR) != 0:
            return False
        self.b.tap("RIGHT", 5); time.sleep(0.25)
        moved = self.b.read_byte(ACTION_CURSOR)
        self.b.tap("LEFT", 5); time.sleep(0.25)
        return moved == 1 and self.b.read_byte(ACTION_CURSOR) == 0

    def wait_for_menu(self, tries: int = 30) -> bool:
        """Ride battle text to the action menu. B advances boxes and is a
        harmless no-op at the menu / backs out of stray submenus."""
        for _ in range(tries):
            if self.menu_up():
                return True
            self.b.tap("B", 8); time.sleep(0.5)
        return False

    def to_fight(self) -> bool:
        """Normalize the action cursor onto FIGHT (LEFT+UP never wrap)."""
        self.b.tap("LEFT", 5); time.sleep(0.2)
        self.b.tap("UP", 5); time.sleep(0.2)
        return self.b.read_byte(ACTION_CURSOR) == 0

    # ---- decisions --------------------------------------------------------
    def choose_move(self) -> int:
        """Best damaging move index (0-3) for the active matchup, by the Gen-3
        chart + STAB + PP. Falls back to 0 on any decode surprise."""
        try:
            mine = self.active_slot()
            moves = self.reader.read_moves(mine)
            my_sp = self.reader.read_species(mine)
            foe_base = GENEMY_PARTY + self.enemy_active_slot() * SLOT_SIZE
            foe_sp = self.reader.read_species_at(foe_base)
            m1, m2 = species_types(my_sp)
            e1, e2 = species_types(foe_sp)
            scores = score_moves([m for m, _ in moves], [pp for _, pp in moves],
                                 m1, m2, e1, e2)
            best = best_move(scores)
            return best.slot if best else 0
        except Exception:
            return 0

    def _select_move(self, idx: int) -> None:
        """From the action menu: FIGHT -> normalize move cursor to slot 0 ->
        walk to `idx` -> commit."""
        self.to_fight()
        self.b.tap("A", 6); time.sleep(0.8)       # FIGHT -> move menu
        self.b.tap("UP", 5); time.sleep(0.2)      # normalize to TL
        self.b.tap("LEFT", 5); time.sleep(0.2)
        for d in _MOVE_PATHS.get(idx, ()):
            self.b.tap(d, 5); time.sleep(0.25)
        self.b.tap("A", 6); time.sleep(0.8)       # commit the move

    def _potion_index(self) -> int | None:
        """Items-pocket cursor index of the first HP-heal item, or None."""
        pocket = self.reader.read_bag_pocket("items")
        for i, (item, qty) in enumerate(pocket):
            if item in HEAL_ITEM_IDS and qty > 0:
                return i
        return None

    def _allow_battle_item(self) -> bool:
        """Whether a mid-battle heal is allowed. False under the Nuzlocke
        `no_battle_items` rule; True when no ruleset is wired."""
        return self.ruleset is None or self.ruleset.allow_battle_item()

    def use_potion(self) -> bool:
        """From the action menu: BAG -> ITEMS pocket (default) -> the first
        heal item -> use on the active mon. Verified by the HP delta."""
        idx = self._potion_index()
        if idx is None:
            return False
        hp0 = self.my_stats()[1]
        self.to_fight()
        self.b.tap("RIGHT", 6); time.sleep(0.3)   # FIGHT -> BAG
        self.b.tap("A", 6); time.sleep(1.3)       # open bag (ITEMS pocket)
        for _ in range(idx):
            self.b.tap("DOWN", 5); time.sleep(0.3)
        self.b.tap("A", 6); time.sleep(0.8)       # select item
        self.b.tap("A", 6); time.sleep(0.8)       # USE
        self.b.tap("A", 6); time.sleep(0.8)       # target = active (cursor default)
        for _ in range(8):                        # ride the heal text
            if self.my_stats()[1] > hp0:
                break
            self.b.tap("B", 5); time.sleep(0.4)
        healed = self.my_stats()[1] > hp0
        if not healed:                            # back out of any stray menu
            for _ in range(3):
                self.b.tap("B", 5); time.sleep(0.3)
        return healed

    def send_next_mon(self) -> bool:
        """After OUR active mon faints in a battle we must CONTINUE (trainer
        fights can't be fled): drive the forced party screen until a healthy
        mon is out (the action menu returns).

        Order matters (micro-probed live 2026-07-05): B-CLEAR FIRST (an open
        error/summary/submenu box eats direction presses - the earlier
        A-first sweep re-polluted the screen every round and the cursor
        never moved), THEN step the list cursor one UP (a DOWN walk sinks
        into CANCEL), THEN A (pick) + A (SHIFT). Fainted picks error out and
        the next round's B clears them; within a lap the sweep sends the
        first healthy mon. On the 'Use next POKeMON?' prompt the same round
        reads as NO -> re-ask -> YES, which is harmless."""
        for _ in range(14):
            if self.menu_up():
                return True
            self.b.tap("B", 5); time.sleep(0.5)     # clear any box first
            self.b.tap("UP", 5); time.sleep(0.4)    # step the list cursor
            self.b.tap("A", 6); time.sleep(0.8)     # pick under cursor
            self.b.tap("A", 6); time.sleep(1.0)     # SHIFT -> send in
        return self.menu_up()

    # ---- ride-outs ---------------------------------------------------------
    def _moved_probe(self) -> bool:
        p0 = self.b.player_xy()
        self.b.press_direction_settle("LEFT")
        return self.b.player_xy() != p0

    def ride_out_end(self, button: str = "B", cap: int = 40) -> bool:
        """Advance end-of-battle text (XP, level-ups, payout) until MOVEMENT
        returns. B declines learn/nickname prompts safely."""
        for _ in range(cap):
            self.b.tap(button, 5); time.sleep(0.4)
            if self._moved_probe():
                return True
        return False

    # ---- the fight loops -----------------------------------------------------
    def fight(self, narrate=None, turn_cap=400) -> str:
        """v1 A-mash (kept for scripted fights): 'win' | 'lose' | 'stuck'."""
        last = ""
        for _ in range(turn_cap):
            elvl, ehp, emx = self.enemy_stats()
            mlvl, mhp, mmx = self.my_stats()
            line = f"me lv{mlvl} {mhp}/{mmx}  vs  foe lv{elvl} {ehp}/{emx}"
            if narrate and line != last:
                narrate(line)
                last = line
            if ehp == 0 and self.enemy_alive_count() == 0:
                return "win"
            if self.all_fainted():
                return "lose"
            self.b.tap("A", 6)
            time.sleep(0.5)
        return "stuck"

    def fight_smart(self, narrate=None, turn_cap=30,
                    potion_below: float = 0.25) -> str:
        """Type-aware battle loop for REAL fights (G7): per turn, heal with a
        potion when the active mon is low (trainer battles only - wilds we
        can flee), else the best-scored move. Returns 'win' | 'lose' |
        'stuck'. 'win' is RAM-honest: every enemy slot fainted AND the
        overworld gives movement back (rode out)."""
        say = narrate or (lambda m: None)
        trainer = self.is_trainer_battle()
        for _turn in range(turn_cap):
            if self.all_fainted():
                say("everyone is down - riding out the loss")
                self.ride_out_end(button="A", cap=60)   # blackout warp text
                return "lose"
            if self.enemy_alive_count() == 0:
                say("that was their last one - riding out the win")
                self.ride_out_end()
                return "win"
            if not self.wait_for_menu():
                # menu never came: the battle ended, or OUR mon fainted and
                # the send-next prompt / forced party screen is up
                if self.all_fainted():
                    say("everyone is down - riding out the loss")
                    self.ride_out_end(button="A", cap=60)
                    return "lose"
                if self.enemy_alive_count() == 0 or not self.active():
                    self.ride_out_end()
                    return "win"
                say("our mon fainted - sending the next one")
                if self.send_next_mon():
                    continue
                self.ride_out_end(cap=10)
                continue
            mlvl, mhp, mmx = self.my_stats()
            elvl, ehp, emx = self.enemy_stats()
            say(f"me lv{mlvl} {mhp}/{mmx} vs foe lv{elvl} {ehp}/{emx}"
                f"{' (trainer)' if trainer else ''}")
            if (trainer and mmx > 0 and mhp / mmx < potion_below
                    and self._potion_index() is not None
                    and self._allow_battle_item()):
                say("low HP - using a potion")
                if self.use_potion():
                    continue
            idx = self.choose_move()
            self._select_move(idx)
            # ride the turn: watch both sides while text plays
            for _ in range(24):
                if self.all_fainted():
                    break
                if self.enemy_alive_count() == 0:
                    break
                if self.menu_up():
                    break
                self.b.tap("B", 5); time.sleep(0.4)
        else:
            return "stuck"
        return "stuck"
