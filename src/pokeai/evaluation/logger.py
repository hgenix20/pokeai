"""JSONL episode logger + run.json metadata writer."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pokeai.evaluation.metrics import RunMetrics


class RunLogger:
    """Writes one JSON object per line to episodes.jsonl. Appends as it goes."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_path = self.run_dir / "episodes.jsonl"
        self.run_meta_path = self.run_dir / "run.json"
        self._start_time = time.time()
        # Truncate any prior file for this run
        self.episodes_path.write_text("")

    def write_run_metadata(
        self,
        run_id: str,
        agent_name: str,
        config_snapshot: dict[str, Any],
        config_hash: str,
        git_commit: str | None = None,
    ) -> None:
        meta = {
            "run_id": run_id,
            "agent_name": agent_name,
            "config_hash": config_hash,
            "config_snapshot": config_snapshot,
            "git_commit": git_commit,
            "started_at": self._start_time,
        }
        self.run_meta_path.write_text(json.dumps(meta, indent=2, default=str))

    def write_episode(self, metrics: RunMetrics) -> None:
        with self.episodes_path.open("a") as f:
            f.write(json.dumps(metrics.to_dict()) + "\n")

    def finalize(self) -> None:
        if not self.run_meta_path.exists():
            return
        meta = json.loads(self.run_meta_path.read_text())
        meta["ended_at"] = time.time()
        meta["duration_seconds"] = meta["ended_at"] - meta["started_at"]
        self.run_meta_path.write_text(json.dumps(meta, indent=2, default=str))
