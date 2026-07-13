"""CLI: `python -m pokeai run --config configs/random.yaml`"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pokeai.config import Config
from pokeai.evaluation.aggregate import aggregate
from pokeai.training.loop import run as run_training


def _force_utf8_io() -> None:
    """Make stdout/stderr UTF-8 so non-ASCII log text (e.g. the × in battle
    matchup messages) doesn't crash under Windows' cp1252 default when
    output is redirected to a file. Without this, `python -m pokeai run ... >log`
    dies with UnicodeEncodeError the moment it prints epsilon (watch mode only,
    since that's the path that resumes from a checkpoint)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # detached/!tty streams
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_io()
    parser = argparse.ArgumentParser(prog="pokeai")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run episodes with the configured agent")
    run_p.add_argument("--config", type=Path, required=True, help="Path to YAML config")
    run_p.add_argument(
        "--episodes",
        type=int,
        default=None,
        help="Override config.logging.episodes",
    )
    run_p.add_argument(
        "--ui",
        action="store_true",
        help="Open the diagnostic dashboard (HUD, minimap, start/stop controls)",
    )
    run_p.add_argument(
        "--agent",
        choices=["random", "heuristic", "strategist", "planner", "tactician",
                 "learner", "catcher", "adventurer"],
        default=None,
        help="Override config.agent.type (the AI strategy). In the dashboard you "
        "can also switch strategy live from the Options menu (O).",
    )

    report_p = sub.add_parser(
        "report", help="Aggregate a run's episodes.jsonl into eval_report.json"
    )
    report_p.add_argument(
        "--run-dir", type=Path, required=True, help="Path to runs/{run_id} directory"
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        config = Config.from_yaml(args.config)
        if args.episodes is not None:
            config.logging.episodes = args.episodes
        if args.agent is not None:
            config.agent.type = args.agent
        if args.ui:
            config.ui.enabled = True
        run_dir = run_training(config)
        print(f"Run complete. Results in: {run_dir}")
        return 0

    if args.command == "report":
        report = aggregate(args.run_dir)
        print(json.dumps(report, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
