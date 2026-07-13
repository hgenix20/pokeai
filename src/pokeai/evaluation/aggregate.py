"""Aggregate per-episode metrics into a summary report + a skills profile.

Reads a run's episodes.jsonl and computes:
  1. eval_report.json — mean/median/max/min/std per numeric metric,
     termination reason counts, blackout rate.
  2. skills_profile.json — how the agent's skills change over a run: for each
     skill a per-episode series + a verdict (improving / steady / regressing /
     collapsed), so you can see whether the agent is actually getting better.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

# Numeric metric fields to aggregate
_NUMERIC_FIELDS = (
    "steps_taken",
    "badges_earned",
    "events_triggered",
    "unique_maps_visited",
    "total_party_level",
    "cumulative_reward",
    "wall_clock_seconds",
    "unique_tiles_visited",
    "repeat_action_rate",
    "total_steps_stuck",
    "curiosity_reward_total",
    "battles_won",
)

# skill -> spec. "direction": "up" = improving means the metric rises; "down" =
# improving means it falls. Optional keys make the verdict collapse-aware:
#   "collapse": a catastrophe marker for this skill
#       {"type": "sign_flip"}              -> was net-positive, now net-negative
#       {"type": "abs_high", "level": L}   -> late level >= L (failure floor)
#       {"type": "peak_ratio", "ratio": r} -> late < r * run-peak (cratered)
#   "good": for "down" metrics, the absolute late level considered healthy.
_SKILLS: dict[str, dict[str, Any]] = {
    "exploration": {
        "metric": "unique_tiles_visited",
        "direction": "up",
        "description": "New ground covered per episode",
        "collapse": {"type": "peak_ratio", "ratio": 0.5},
    },
    "anti_looping": {
        "metric": "repeat_action_rate",
        "direction": "down",
        "description": "Wasted repeated moves (lower is better)",
        "good": 0.25,
        "collapse": {"type": "abs_high", "level": 0.40},
    },
    "survival": {
        "metric": "blackout_occurred",
        "direction": "down",
        "description": "Blackout rate (lower is better)",
        "good": 0.20,
        "collapse": {"type": "abs_high", "level": 0.50},
    },
    "battling": {
        "metric": "battles_won",
        "direction": "up",
        "description": "Enemy Pokemon knocked out per episode",
    },
    "progress": {
        "metric": "cumulative_reward",
        "direction": "up",
        "description": "Total reward per episode (overall progress)",
        "collapse": {"type": "sign_flip"},
    },
    "goals": {
        "metric": "badges_earned",
        "direction": "up",
        "description": "Badges earned (long-horizon goals)",
    },
}

# +/-25% of the early baseline is "steady" for up-metrics. RL skill series
# are noisy and the early (high-epsilon) episodes carry an inflated intrinsic /
# exploration signal, so a healthy agent tapers as it shifts to exploitation.
# This band separates that benign taper from a genuine regression.
_UP_REL_BAND = 0.25


def _summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "max": 0.0, "min": 0.0, "std": 0.0}
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "max": max(values),
        "min": min(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def _trend(series: list[float]) -> str:
    """Crude trend: compare mean of first half vs second half."""
    if len(series) < 4:
        return "insufficient_data"
    mid = len(series) // 2
    first, second = statistics.fmean(series[:mid]), statistics.fmean(series[mid:])
    if abs(second - first) < 1e-9:
        return "flat"
    return "rising" if second > first else "falling"


def load_episodes(episodes_path: Path) -> list[dict[str, Any]]:
    records = []
    with episodes_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _segment_means(series: list[float]) -> tuple[float, float]:
    """Mean of the first third vs the last third (>= 1 episode each)."""
    seg = max(1, len(series) // 3)
    return statistics.fmean(series[:seg]), statistics.fmean(series[-seg:])


def _verdict(series: list[float], spec: dict[str, Any]) -> dict[str, Any]:
    """Magnitude/shape-aware verdict on how a skill changed over the run.

    More than a first-vs-second-half direction test: it distinguishes a benign
    exploration taper from a real collapse. Returns early_mean, late_mean, and a
    verdict in {improving, steady, regressing, collapsed, not_developing,
    insufficient_data}. "steady" means the skill is held; "collapsed" is a
    death-spiral (reward sign-flips, exploration craters, looping sets in).
    """
    desired = spec["direction"]
    if len(series) < 4:
        return {"early_mean": None, "late_mean": None, "verdict": "insufficient_data"}

    early, late = _segment_means(series)
    out: dict[str, Any] = {"early_mean": round(early, 4), "late_mean": round(late, 4)}

    if max(abs(v) for v in series) < 1e-9:
        out["verdict"] = "not_developing"  # capacity never manifested
        return out

    # Skill-specific catastrophe markers.
    collapse = spec.get("collapse")
    if collapse:
        ctype = collapse["type"]
        if ctype == "sign_flip" and early > 0 and late < 0:
            out["verdict"] = "collapsed"
            return out
        if ctype == "abs_high" and late >= collapse["level"]:
            out["verdict"] = "collapsed"
            return out
        if ctype == "peak_ratio":
            peak = max(series)
            if peak > 0 and late < collapse["ratio"] * peak and late < early:
                out["verdict"] = "collapsed"
                return out

    if desired == "down":
        # Judge by absolute level — relative change is unstable near zero
        # (0.10 -> 0.15 looks like +50% but is still healthy).
        good = spec.get("good", 0.0)
        if late <= good:
            out["verdict"] = "improving" if late < early - 0.03 else "steady"
        else:
            out["verdict"] = "regressing"
        return out

    # up-metric: relative change off the early baseline, tolerant of taper.
    scale = abs(early) if abs(early) > 1e-9 else (abs(max(series)) or 1.0)
    favorable = (late - early) / scale
    if favorable > _UP_REL_BAND:
        out["verdict"] = "improving"
    elif favorable < -_UP_REL_BAND:
        out["verdict"] = "regressing"
    else:
        out["verdict"] = "steady"
    return out


def build_skills_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-skill series + verdicts: is the agent getting better over the run?"""
    profile: dict[str, Any] = {}
    for skill, spec in _SKILLS.items():
        field = spec["metric"]
        series = [float(r.get(field, 0) or 0) for r in records]
        v = _verdict(series, spec)
        profile[skill] = {
            "description": spec["description"],
            "metric": field,
            "desired_direction": spec["direction"],
            "per_episode": series,
            "trend": _trend(series),          # raw direction (first vs second half)
            "early_mean": v["early_mean"],     # last-third vs first-third basis
            "late_mean": v["late_mean"],
            "verdict": v["verdict"],
        }
    return profile


def aggregate(run_dir: Path) -> dict[str, Any]:
    """Aggregate episodes.jsonl in run_dir. Writes eval_report.json and
    skills_profile.json; returns the eval report."""
    episodes_path = run_dir / "episodes.jsonl"
    if not episodes_path.exists():
        raise FileNotFoundError(f"No episodes.jsonl in {run_dir}")

    records = load_episodes(episodes_path)
    if not records:
        raise ValueError(f"episodes.jsonl in {run_dir} is empty")

    numeric_summary = {
        field: _summarize([float(r[field]) for r in records if field in r])
        for field in _NUMERIC_FIELDS
    }

    # Categorical: termination reasons
    reason_counts: dict[str, int] = {}
    for r in records:
        reason = r.get("terminated_reason", "UNKNOWN")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    # Boolean: blackout rate
    blackout_count = sum(1 for r in records if r.get("blackout_occurred"))

    # Skills profile (built first so the report can surface a collapse signal).
    profile = build_skills_profile(records)
    collapsed = sorted(c for c, p in profile.items() if p["verdict"] == "collapsed")

    report = {
        "run_id": records[0].get("run_id"),
        "agent_name": records[0].get("agent_name"),
        "config_hash": records[0].get("config_hash"),
        "episode_count": len(records),
        "numeric_summary": numeric_summary,
        "termination_reason_counts": reason_counts,
        "blackout_count": blackout_count,
        "blackout_rate": blackout_count / len(records),
        "episodes_with_positive_reward": sum(
            1 for r in records if r.get("cumulative_reward", 0) > 0
        ),
        # Episodes that left the starting map (basic exploration gate)
        "episodes_left_starting_map": sum(
            1 for r in records if r.get("unique_maps_visited", 1) > 1
        ),
        # Skills that died in a death-spiral over the run (empty = none)
        "collapsed_skills": collapsed,
    }

    report_path = run_dir / "eval_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    profile_path = run_dir / "skills_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2))

    return report
