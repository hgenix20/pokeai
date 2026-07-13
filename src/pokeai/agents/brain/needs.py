"""Needs/Goal arbiter — the decision layer that turns roots into intent.

Each step it scores the authored drives (docs/AGENT_ROOTS.md §1) against the live
game context and returns the most urgent one as a goal + a plain-language reason.
This is the "what should I be doing right now and why" layer that sits above
navigation (GameSense) and combat (BattleBrain) — the thing a human has that a
mapper doesn't.

Drive triggers are short boolean expressions authored in the roots file (e.g.
`party_hp_fraction < 0.35 and mart_known`). They're evaluated against a context
dict of named facts the agent computes from RAM + memory. Evaluation is done with
a restricted `eval` (no builtins) over that dict — the roots file is a trusted,
human-authored local file, and this keeps triggers expressive without hard-coding
each one here.

Pure logic, no emulator/UI dependency.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeai.knowledge.roots import Roots


@dataclass(frozen=True)
class Decision:
    drive: str       # which drive won (e.g. "survive")
    goal: str        # its resolves_to (e.g. "heal")
    rationale: str   # human-readable "why" for the dashboard
    critical: bool = False  # the drive's emergency threshold is also met


class NeedsArbiter:
    def __init__(self, roots: Roots):
        self.roots = roots

    def decide(self, ctx: dict) -> Decision:
        """Return the highest-priority drive whose trigger is satisfied."""
        for drive in self.roots.drives:  # already sorted by priority desc
            if self._truthy(drive.trigger, ctx):
                critical = bool(drive.critical) and self._truthy(drive.critical, ctx)
                return Decision(drive.name, drive.resolves_to,
                                self._rationale(drive.name, drive.resolves_to, ctx), critical)
        # No drive fired (e.g. empty roots): just explore.
        return Decision("explore", "explore", "Looking around to find the way onward.")

    # --- internals ---

    @staticmethod
    def _truthy(expr: str | None, ctx: dict) -> bool:
        if not expr:
            return False
        try:
            return bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307 (trusted roots file)
        except Exception:
            return False  # an unknown name / bad expr just means "doesn't fire"

    @staticmethod
    def _rationale(drive: str, goal: str, ctx: dict) -> str:
        hp = ctx.get("party_hp_fraction")
        hp_pct = f"{hp * 100:.0f}%" if isinstance(hp, (int, float)) else "?"
        lvl = ctx.get("next_gym_recommended_level")
        top = ctx.get("party_top_level")
        if drive == "survive":
            return f"Party down to {hp_pct} HP — head to a Pokémon Center to heal."
        if drive == "rest_before_gym":
            return f"At the gym town ({hp_pct} HP) — top up before the badge fight."
        if goal == "unblock_gate":
            return "Explored everywhere I can reach — work out what's blocking the way on."
        if goal == "shop":
            return "Some money and low on supplies — stock up at the Mart."
        if goal == "restock":
            balls = ctx.get("ball_count")
            return f"Only {balls} ball(s) left — buy more at the Mart."
        if goal == "catch":
            have = ctx.get("party_count")
            want = ctx.get("party_target")
            return f"Party at {have}/{want} — hunt the grass and catch."
        if goal == "train_or_catch":
            return f"Under-levelled for the next gym (want ~Lv{lvl}, at Lv{top}) — train and catch."
        return "Exploring to find the way onward."
