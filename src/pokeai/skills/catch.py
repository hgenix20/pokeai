"""Catch skill — throw balls at the active wild Pokemon until it's caught or we
run out. Live-verified on FireRed BPRE (2026-07-03); the first vertical slice of
the core-gameplay module (docs/CORE_GAMEPLAY.md).

Signals (all live-verified, see memory pokeai-catch-bag-addr):
  * action menu is up  : gActionSelectionCursor (0x02023FF8) responds to RIGHT/LEFT
                         (0=FIGHT 1=BAG 2=POKEMON 3=RUN); STABLE at rest, so no
                         false positive on the intro send-out animation.
  * catch succeeded    : gPlayerPartyCount (0x02024029) increments.
  * in-battle bag path : ITEMS -> KEY ITEMS -> POKe BALLS (RIGHT x2 from default),
                         A selects the top ball and throws it.
  * post-throw         : mash B -- advances every text box AND declines the
                         "give a nickname?" YES/NO prompt (B == NO).

This skill assumes a REAL wild battle is already active (caller detects it; a
plain gEnemyParty check false-positives on a stale post-battle enemy, so pair with
a movement-lock check).

v2 adds WEAKEN-FIRST: attempt(weaken_to=0.30) attacks with move slot 1 until the
foe is at/below that HP fraction before throwing (full-HP catch rate is ~7%/ball;
weakened is several times better, and it is the real gate on a green fill-to-6
run). Cursor normalization is RAM-honest: LEFT+UP always lands the 2x2 action
menu on FIGHT (Gen-3 menus don't wrap), verified by reading ACTION_CURSOR == 0.
"""
from __future__ import annotations

import time

from pokeai.emulator.firered_state_reader import GPLAYER_PARTY_COUNT

ACTION_CURSOR = 0x02023FF8   # gActionSelectionCursor: 0=FIGHT 1=BAG 2=POKEMON 3=RUN


class Catch:
    def __init__(self, bridge, battle):
        self.b = bridge
        self.battle = battle
        self.balls_thrown = 0   # updated by attempt(); lets a strategy track budget

    # ---- menu-state detection ---------------------------------------------
    # The battle-menu machinery moved into skills/battle.py (v2, 2026-07-05);
    # Catch delegates so there is exactly ONE implementation to keep honest.
    def menu_up(self) -> bool:
        return self.battle.menu_up()

    def wait_for_menu(self, tries: int = 30) -> bool:
        return self.battle.wait_for_menu(tries=tries)

    def confirm_real_battle(self, max_tries: int = 8,
                            assume_locked: bool = False) -> bool:
        """The STRONG battle test: enemy loaded AND movement locked AND the
        action menu (eventually) responds to the cursor probe.

        Why three signals: gEnemyParty lingers after a flee/catch, so
        battle.active() alone false-positives; and the movement-lock check
        alone false-positives when the player is wedged in a 1-tile corridor
        or an A-opened dialogue (seen live 2026-07-05: a 'stuck' fight() spent
        400 turns A-mashing an overworld dialogue). The same B that advances a
        real battle intro toward the menu also CLOSES an overworld dialogue,
        after which the movement probe passes and we know it was never a
        battle.

        `assume_locked=True` (nav-audit 2026-07-06): the CALLER already
        proved the player cannot move (a walk press was eaten), so skip the
        LEFT/RIGHT probe - when the battle has actually ended those presses
        physically walk the player 1-2 tiles and poison the position a
        path resume relies on."""
        if not self.battle.active():
            return False
        for _ in range(max_tries):
            if not assume_locked:
                p0 = self.b.player_xy()
                self.b.press_direction_settle("LEFT")
                if self.b.player_xy() != p0:
                    return False
                self.b.press_direction_settle("RIGHT")
                if self.b.player_xy() != p0:
                    return False
            if self.menu_up():
                return True
            self.b.tap("B", 6); time.sleep(0.4)
        return False

    # ---- one throw ------------------------------------------------------------
    def _throw_one(self) -> None:
        """From the action menu (cursor on FIGHT), open the bag, switch to the
        POKe BALLS pocket, and throw the top ball."""
        self.b.tap("RIGHT", 6); time.sleep(0.3)     # FIGHT -> BAG
        self.b.tap("A", 6); time.sleep(1.3)         # open bag (ITEMS pocket)
        self.b.tap("RIGHT", 6); time.sleep(0.5)     # ITEMS -> KEY ITEMS
        self.b.tap("RIGHT", 6); time.sleep(0.7)     # KEY ITEMS -> POKe BALLS
        self.b.tap("A", 6); time.sleep(0.8)         # select top ball (throws)
        self.b.tap("A", 6); time.sleep(0.8)         # confirm any USE submenu

    def party_count(self) -> int:
        return self.b.read_byte(GPLAYER_PARTY_COUNT)

    def party_species(self) -> list[int]:
        """Species ids currently in the party (0 for any decode surprise). The
        Nuzlocke dupes/species clauses read this to decide whether to catch."""
        out = []
        for i in range(min(self.party_count(), 6)):
            try:
                out.append(self.battle.reader.read_species(i))
            except Exception:
                out.append(0)
        return out

    # ---- weaken-first ----------------------------------------------------------
    def _to_fight(self) -> bool:
        return self.battle.to_fight()

    def _ride_out_ko(self) -> None:
        """After the foe faints, advance XP/level-up/move-learned text with B
        until MOVEMENT returns (ground truth for 'back in the overworld'). A
        level-up can add several boxes, so a fixed tap count is not enough."""
        for _ in range(30):
            self.b.tap("B", 5); time.sleep(0.4)
            p0 = self.b.player_xy()
            self.b.press_direction_settle("LEFT")
            if self.b.player_xy() != p0:
                return

    def _ride_out_lead_faint(self) -> None:
        """Resolve a mon faint in a WILD battle all the way back to the
        overworld. Two live-seen paths: (a) 'Use next POKeMON?' -> B answers
        NO -> run away; (b) some A already answered YES -> the FORCED party
        screen ('Choose a POKeMON.') that B cannot cancel — walk the cursor
        (DOWN + A + A[SHIFT]) until a healthy mon is sent in, then RUN from
        the action menu. Movement is the exit ground truth throughout."""
        for _round in range(10):
            p0 = self.b.player_xy()
            self.b.press_direction_settle("LEFT")
            if self.b.player_xy() != p0:
                return                              # overworld control is back
            if self.menu_up():
                if self.battle.is_trainer_battle():
                    return          # cannot flee a trainer: caller must FIGHT
                # a live mon is out and the action menu is up: RUN
                self._to_fight()
                self.b.tap("RIGHT", 6); time.sleep(0.3)   # -> BAG
                self.b.tap("DOWN", 6); time.sleep(0.3)    # -> RUN
                self.b.tap("A", 6); time.sleep(0.8)
                for _ in range(6):
                    self.b.tap("B", 5); time.sleep(0.4)
                continue
            for _ in range(3):                      # declines send-next -> flee
                self.b.tap("B", 5); time.sleep(0.4)
            p0 = self.b.player_xy()
            self.b.press_direction_settle("LEFT")
            if self.b.player_xy() != p0:
                return
            # possibly the forced party screen: advance + pick + shift; a
            # fainted pick just shows an error box the next B round clears
            self.b.tap("DOWN", 5); time.sleep(0.3)
            self.b.tap("A", 6); time.sleep(0.6)
            self.b.tap("A", 6); time.sleep(0.8)
            for _ in range(3):
                self.b.tap("B", 5); time.sleep(0.4)

    def weaken(self, target_frac: float = 0.30, max_turns: int = 8,
               narrate=None) -> str:
        """Attack with move slot 1 until the foe is at or below target_frac of
        its max HP -- or until one more hit might KO it (per-hit damage is
        estimated from observed HP deltas; overkill wastes the encounter).
        Returns 'weakened' (back at the action menu, ready to throw) | 'ko'
        (foe fainted -- encounter over) | 'lost' | 'no_menu'. Running out of
        turns returns 'weakened' (throw anyway rather than stall).

        Self-healing by construction: a missed A leaves us at a state the next
        menu_up()/B-tap recovers from, and the move cursor is re-normalized
        (UP+LEFT -> slot 1) every turn in case a probe tap moved it."""
        dmg_est = 0
        fainted0 = self.battle.party_fainted_count()
        for _turn in range(max_turns):
            if not self.wait_for_menu():
                return "no_menu"
            _lvl, ehp, emax = self.battle.enemy_stats()
            if emax <= 0:
                return "no_menu"
            floor = max(1, int(emax * target_frac))
            if ehp <= floor or (dmg_est and ehp <= dmg_est + 1):
                return "weakened"                    # low enough / can't hit again safely
            if narrate:
                narrate(f"weakening the foe: {ehp}/{emax} HP (target <= {floor})")
            self._to_fight()
            self.b.tap("A", 6); time.sleep(0.8)      # FIGHT -> move menu
            self.b.tap("UP", 5); time.sleep(0.2)     # normalize move cursor
            self.b.tap("LEFT", 5); time.sleep(0.2)   # -> slot 1
            self.b.tap("A", 6); time.sleep(0.8)      # commit the move
            for _ in range(24):                      # ride the turn (~12s cap)
                ehp_now = self.battle.enemy_stats()[1]
                if ehp_now == 0:
                    self._ride_out_ko()
                    return "ko"
                if self.battle.party_fainted_count() > fainted0:
                    self._ride_out_lead_faint()      # decline send-next -> flee
                    return "lost"
                if self.menu_up():
                    dmg_est = max(dmg_est, ehp - self.battle.enemy_stats()[1])
                    break                            # turn resolved, re-evaluate
                self.b.tap("B", 5); time.sleep(0.4)
        return "weakened"

    # ---- full attempt: (weaken then) throw until caught or out -----------------
    def _name_catch(self, nickname: str) -> None:
        """Answer FireRed's post-catch 'Give a nickname?' prompt YES and type
        `nickname`, reusing the SAME verified keyboard machinery as
        Overworld.pick_starter (screen.advance_until -> is_keyboard, type_name,
        confirm). advance_until presses A on the YES/NO box (cursor defaults to
        YES) until the naming keyboard appears, then we type + confirm. On any
        surprise (keyboard never shows) we fall back to mashing B so the catch
        still completes."""
        from pokeai.agents.firered_intro import Intro
        screen = Intro(self.b)
        try:
            if screen.advance_until(screen.is_keyboard, cap=20) is not None:
                screen.type_name(nickname.upper())
                screen.confirm()
                return
        except Exception:
            pass
        for _ in range(6):                        # keyboard never came: decline
            self.b.tap("B", 5); time.sleep(0.3)

    def attempt(self, max_balls: int = 6, narrate=None,
                weaken_to: float | None = None, nickname: str | None = None) -> str:
        """Throw balls at the active wild mon until caught or max_balls used.
        weaken_to=0.30 fights the foe down to 30% HP first. When `nickname` is
        supplied (the Nuzlocke nickname_all rule), the post-catch prompt is
        answered YES and the mon is named; otherwise the prompt is declined by
        mashing B (the default). Returns 'caught' | 'out_of_balls' | 'no_menu'
        | 'lost' | 'fainted_target' (weaken KO'd the foe -- encounter over,
        hunt another). Assumes a real wild battle is active."""
        party0 = self.party_count()
        fainted0 = self.battle.party_fainted_count()
        self.balls_thrown = 0
        if weaken_to is not None:
            res = self.weaken(target_frac=weaken_to, narrate=narrate)
            if res == "ko":
                return "fainted_target"
            if res in ("lost", "no_menu"):
                return res
        for ball in range(max_balls):
            if not self.wait_for_menu():
                return "no_menu"
            if narrate:
                narrate(f"throwing ball {ball + 1}/{max_balls} "
                        f"(foe lv{self.battle.enemy_stats()[0]})")
            self._throw_one()
            self.balls_thrown += 1
            # watch for the catch (party +1); mash B to advance wobble/Gotcha/
            # nickname text. Bail if our lead faints (shouldn't vs early wilds).
            for _ in range(40):                      # ~20s
                pc = self.party_count()
                if pc > party0:
                    if narrate:
                        narrate(f"caught! party {party0} -> {pc}")
                    if nickname:
                        self._name_catch(nickname)   # answer the naming prompt YES
                    for _ in range(6):               # settle post-catch
                        self.b.tap("B", 5); time.sleep(0.3)
                    return "caught"
                if self.battle.party_fainted_count() > fainted0:
                    self._ride_out_lead_faint()
                    return "lost"
                self.b.tap("B", 5); time.sleep(0.5)
            # broke free: the foe took its turn, we loop back to the menu
        return "out_of_balls"
