"""stream_state classifier v3 (G4/B1) — pure function over live facts.

Emits the DETECTABLE subset of the 28-state vocabulary from
docs/Native-Stream-Operator.md, resolving anything it cannot prove to the
NEAREST SAFER ANCESTOR (unknown battle -> TRAINER_BATTLE, unknown overworld ->
ROUTE_TRAVEL) so the bot's gating engine errs conservative.

Inputs are plain values gathered by the caller (stream.py stats_tick); the
function itself touches no emulator, so it is fully T0-testable.

v3 (2026-07-06, FIXLIST op-states cluster): LOW_HP_DANGER moved INSIDE the
battle branch (the doc scopes it to "any battle where active Pokemon is at
risky HP"; it used to fire in the overworld and never in battle),
GYM_BATTLE via gym interior map ids, BOSS_TRANSITION via gym-arc story
tasks, RIVAL_BATTLE by task-id prefix (the Route 22 rematch counts, not
just Part 1's "rival1"), CUTSCENE via the script-lock frozen bit,
POST_BATTLE_SAFE for a grace window after a battle ends,
BETWEEN_OBJECTIVES when the task queue is idle, CATCH_DECISION while a
catch is armed for the current wild battle.
"""
from __future__ import annotations

# Pallet-era maps (town + home/rival/lab interiors).
PALLET_MAPS = {(3, 0), (4, 0), (4, 1), (4, 2), (4, 3)}
# Live-confirmed service interiors (extend per town as landmarks are verified).
CENTER_MAPS = {(5, 4), (6, 5), (16, 0), (7, 3)}
MART_MAPS = {(5, 3), (6, 3)}
# Gym interiors (live-confirmed: Pewter (6,2) during the Brock arc 2026-07-05).
GYM_MAPS = {(6, 2)}
# Story-task markers: a rival fight is any task id starting "rival"; the
# boss-prep window is the gym-arc tasks BEFORE the gym battle itself.
RIVAL_TASK_PREFIX = "rival"
BOSS_PREP_TASKS = {"p3_gym", "p3_trainer", "brock"}
# POST_BATTLE_SAFE grace window (doc: "best state for promos/polls/clips").
POST_BATTLE_GRACE_S = 45.0


def classify(*, connected: bool, in_world: bool, status: str,
             saving: bool, in_battle: bool, active_task_id: str | None,
             cur_map: tuple[int, int] | None,
             active_hp_frac: float | None = None,
             wild_battle: bool | None = None,
             frozen: bool = False,
             seconds_since_battle: float | None = None,
             catch_armed: bool = False) -> str:
    """Return the stream_state string for the current tick.

    wild_battle: True/False when the caller can prove it (RAM flag, G7);
    None = unknown -> safer ancestor TRAINER_BATTLE.
    active_hp_frac: current HP fraction of the mon that would fight (the
    first non-fainted slot); None when not readable.
    frozen: the player ObjectEvent script-lock bit (cutscenes force-walk).
    seconds_since_battle: since the last battle ENDED (None = long ago).
    catch_armed: a catch_next directive (or roster policy) will attempt a
    catch in the current wild encounter.
    """
    if not connected:
        return "OFFLINE"
    if saving:
        return "SAVE_CRITICAL"
    if in_battle:
        # LOW_HP_DANGER outranks every battle flavor: its row is the
        # strictest ("suppress distractions, prevent forced bad actions").
        if active_hp_frac is not None and active_hp_frac < 0.30:
            return "LOW_HP_DANGER"
        if active_task_id and active_task_id.startswith(RIVAL_TASK_PREFIX):
            return "RIVAL_BATTLE"
        if cur_map in GYM_MAPS:
            return "GYM_BATTLE"
        if wild_battle:
            return "CATCH_DECISION" if catch_armed else "WILD_BATTLE"
        return "TRAINER_BATTLE"
    if not in_world:
        return "INTRO" if status == "running" else "STARTING_SOON"
    if frozen:
        return "CUTSCENE"
    if active_task_id in BOSS_PREP_TASKS:
        return "BOSS_TRANSITION"
    if (seconds_since_battle is not None
            and seconds_since_battle < POST_BATTLE_GRACE_S):
        return "POST_BATTLE_SAFE"
    if cur_map in CENTER_MAPS:
        return "POKEMON_CENTER"
    if cur_map in MART_MAPS:
        return "SHOPPING"
    if cur_map in PALLET_MAPS:
        return "PALLET_TOWN"
    if active_task_id is None:
        return "BETWEEN_OBJECTIVES"
    return "ROUTE_TRAVEL"
