"""BattleBrain: type-aware battle policy.

Reactive controller for Gen 1 battles. Each decide() call reads the live RAM
fresh and returns exactly one button press, so it works step-by-step inside
the normal env loop (one env step = one held button press):

  - text / animation on screen  -> A (advance)
  - action menu (FIGHT/PkMn/ITEM/RUN) -> navigate to FIGHT (or RUN when
    fleeing a hopeless wild battle), then A
  - move menu -> cycle the cursor until wPlayerSelectedMove equals the best
    move (power x type effectiveness x STAB, PP-aware), then A

Menu signatures were verified live against the real ROM
(scripts/probe_battle_ram.py); see state_reader address comments.

The brain also exposes analyze() so the dashboard can display the move
scores and matchup reasoning for ANY agent, not just ones driven by it.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeai.emulator.state_reader import (
    ITEM_GREAT_BALL,
    ITEM_MASTER_BALL,
    ITEM_POKE_BALL,
    ITEM_ULTRA_BALL,
    BattleState,
    PartyMon,
    StateReader,
)
from pokeai.env.action_controller import Action
from pokeai.knowledge.game_data import species_name, type_name
from pokeai.knowledge.type_chart import MoveScore, best_move, score_moves

# Flee a *wild* battle when our active mon is below this HP fraction and the
# enemy still has meaningful HP left (no shame in running from a lost cause).
FLEE_HP_FRAC = 0.15
FLEE_ENEMY_HP_MIN = 0.25

# If the same menu+cursor state repeats this many decisions in a row, we're
# wedged in an unrecognized submenu (e.g. ITEM list) — press B to back out.
STUCK_DECISIONS = 10

# Give up trying to catch (and just fight) after this many thrown balls in one
# battle, so a mis-read bag menu can never softlock the agent on a stream.
MAX_CATCH_ATTEMPTS = 6

_BALL_NAMES = {
    ITEM_MASTER_BALL: "Master Ball",
    ITEM_ULTRA_BALL: "Ultra Ball",
    ITEM_GREAT_BALL: "Great Ball",
    ITEM_POKE_BALL: "Poké Ball",
}


@dataclass(frozen=True)
class BattleAnalysis:
    """Everything the dashboard needs to narrate a battle decision."""

    own: PartyMon | None
    battle: BattleState
    scores: list[MoveScore]
    best: MoveScore | None
    intent: str  # "fight" | "flee"

    @property
    def matchup_text(self) -> str:
        if self.best is None:
            return "no usable attack — struggling through"
        return f"{self.best.name}: {self.best.effectiveness_label}"


class BattleBrain:
    """Stateless-ish battle driver; reads RAM fresh every decision."""

    def __init__(self, state_reader: StateReader):
        self.reader = state_reader
        self.thought = ""
        self._last_menu_sig: tuple | None = None
        self._same_sig_count = 0
        # Catching: the driving agent sets want_catch each step. The phase tracks
        # where we are in the throw-a-ball sequence (open ITEM -> pick a ball ->
        # watch it resolve); attempts bound how many balls we'll spend.
        self.want_catch = False
        self._catch_phase: str | None = None
        self._catch_attempts = 0

    def reset(self) -> None:
        self._last_menu_sig = None
        self._same_sig_count = 0
        self.want_catch = False
        self._catch_phase = None
        self._catch_attempts = 0

    def has_ball(self) -> bool:
        return self.reader.best_ball() is not None

    # --- Analysis (pure read, also used by the dashboard) ---

    def analyze(self) -> BattleAnalysis:
        battle = self.reader.read_battle()
        party = self.reader.read_party_details()
        own: PartyMon | None = None
        if party:
            active = self.reader.emu.read_byte(0xCC2F)  # wPlayerMonNumber
            own = party[active] if active < len(party) else party[0]

        scores: list[MoveScore] = []
        best: MoveScore | None = None
        if own is not None and battle.in_battle:
            scores = score_moves(
                own.moves,
                own.pp,
                own.type1,
                own.type2,
                battle.enemy_type1,
                battle.enemy_type2,
            )
            best = best_move(scores)

        intent = "fight"
        if (
            battle.in_battle == 1  # wild battles only — can't flee trainers
            and battle.own_hp_frac <= FLEE_HP_FRAC
            and battle.enemy_hp_frac >= FLEE_ENEMY_HP_MIN
        ):
            intent = "flee"
        return BattleAnalysis(own=own, battle=battle, scores=scores, best=best, intent=intent)

    # --- Decision (one button per call) ---

    def decide(self) -> int:
        analysis = self.analyze()
        menus = self.reader.read_battle_menus()

        # Wedge detection: same open menu + cursor for too many decisions
        # means we're in a submenu we don't model (ITEM list, PkMn list...).
        sig = (menus.menu_open, menus.top_y, menus.top_x, menus.cursor_item)
        if menus.menu_open and sig == self._last_menu_sig:
            self._same_sig_count += 1
        else:
            self._same_sig_count = 0
        self._last_menu_sig = sig
        if menus.menu_open and self._same_sig_count >= STUCK_DECISIONS:
            self.thought = "Backing out of an unfamiliar menu (B)"
            self._same_sig_count = 0
            return int(Action.B)

        # Catching takes priority over fighting when the agent has asked for it
        # and it's actually possible (wild battle, a ball in the bag, attempts
        # left). Returns None to defer to normal fighting if it can't proceed.
        if self._wants_catch_now(analysis):
            catch = self._drive_catch(menus, analysis)
            if catch is not None:
                return catch
        else:
            self._catch_phase = None

        if menus.action_menu_open:
            return self._drive_action_menu(menus, analysis)
        if menus.move_menu_open:
            return self._drive_move_menu(menus, analysis)

        # Text box, animation, or menu not open yet: advance.
        enemy = species_name(analysis.battle.enemy_species) if analysis.battle.in_battle else ""
        self.thought = f"Battling {enemy} — advancing text" if enemy else "Advancing battle text"
        return int(Action.A)

    def _wants_catch_now(self, analysis: BattleAnalysis) -> bool:
        return (
            self.want_catch
            and analysis.battle.in_battle == 1  # wild only (can't catch trainers')
            and self._catch_attempts < MAX_CATCH_ATTEMPTS
            and self.reader.best_ball() is not None
        )

    def _drive_catch(self, menus, analysis: BattleAnalysis) -> int | None:
        """Throw a ball, one button per call. Phase machine: open the ITEM menu,
        move the bag cursor onto the chosen ball and select it, then advance the
        throw animation. Self-verifies against RAM (the highlighted bag item),
        and is bounded by MAX_CATCH_ATTEMPTS so a mis-read can't softlock — it
        just falls back to fighting."""
        ball = self.reader.best_ball()
        if ball is None:
            self._catch_phase = None
            return None
        ball_id, ball_index = ball
        enemy = species_name(analysis.battle.enemy_species)

        # At the action menu: move to ITEM (left column, bottom row) and open it.
        if menus.action_menu_open:
            if menus.top_x != 9:
                self.thought = f"Going for a {_BALL_NAMES.get(ball_id, 'ball')} — moving to ITEM"
                return int(Action.LEFT)
            if menus.cursor_item != 1:
                self.thought = "Opening the ITEM menu"
                return int(Action.DOWN)
            self._catch_phase = "bag"
            self.thought = "Opening the bag for a ball"
            return int(Action.A)

        # In the move menu while trying to catch? Back out to the action menu.
        if menus.move_menu_open:
            self.thought = "Backing out to throw a ball instead"
            return int(Action.B)

        # In the bag: walk the cursor onto the ball, then select it to throw.
        if self._catch_phase == "bag":
            sel = self.reader.list_selection_index()
            if sel < ball_index:
                self.thought = f"Finding the {_BALL_NAMES.get(ball_id, 'ball')} in the bag..."
                return int(Action.DOWN)
            if sel > ball_index:
                self.thought = f"Finding the {_BALL_NAMES.get(ball_id, 'ball')} in the bag..."
                return int(Action.UP)
            self._catch_phase = "thrown"
            self._catch_attempts += 1
            self.thought = f"Throwing a {_BALL_NAMES.get(ball_id, 'ball')} at {enemy}!"
            return int(Action.A)

        # Throw is resolving (or we just selected the ball): advance the text.
        if self._catch_phase == "thrown":
            self.thought = f"Come on, {enemy} — stay in there!"
            return int(Action.A)

        return None

    def _drive_action_menu(self, menus, analysis: BattleAnalysis) -> int:
        """Action menu: columns FIGHT/ITEM (x=9) and PkMn/RUN (x=15)."""
        if analysis.intent == "flee":
            # RUN = right column, bottom row.
            if menus.top_x != 15:
                self.thought = "HP critical — moving to RUN"
                return int(Action.RIGHT)
            if menus.cursor_item != 1:
                self.thought = "HP critical — selecting RUN"
                return int(Action.DOWN)
            self.thought = "HP critical — running from this battle!"
            return int(Action.A)
        # FIGHT = left column, top row.
        if menus.top_x != 9:
            self.thought = "Moving to FIGHT"
            return int(Action.LEFT)
        if menus.cursor_item != 0:
            self.thought = "Selecting FIGHT"
            return int(Action.UP)
        self.thought = self._fight_thought(analysis)
        return int(Action.A)

    def _drive_move_menu(self, menus, analysis: BattleAnalysis) -> int:
        """Move menu: cycle DOWN until the live-selected move is our pick.

        wPlayerSelectedMove tracks the cursor, so this self-verifies and is
        immune to 1-based indexing / wraparound details.
        """
        best = analysis.best
        if best is None:
            self.thought = "No usable damaging move — using whatever's selected"
            return int(Action.A)
        if menus.selected_move_id == best.move_id:
            self.thought = self._fight_thought(analysis)
            return int(Action.A)
        self.thought = f"Looking for {best.name} in the move list..."
        return int(Action.DOWN)

    def _fight_thought(self, analysis: BattleAnalysis) -> str:
        b = analysis.battle
        enemy = species_name(b.enemy_species)
        etype = type_name(b.enemy_type1)
        if b.enemy_type2 != b.enemy_type1:
            etype += "/" + type_name(b.enemy_type2)
        best = analysis.best
        if best is None:
            return f"Fighting {enemy} ({etype}) — no scored move, mashing on"
        stab = " +STAB" if best.stab > 1 else ""
        return (
            f"{best.name} vs {enemy} ({etype}): ×{best.multiplier:g} "
            f"{best.effectiveness_label}{stab}"
        )
