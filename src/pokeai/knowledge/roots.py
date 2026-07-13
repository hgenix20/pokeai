"""Agent "roots": the human priors loaded from docs/AGENT_ROOTS.md.

The roots file is human-authored markdown with fenced ```yaml blocks (drives,
story gates, town services, items, gyms). This module pulls those blocks out and
turns them into typed records the Needs/Goal arbiter consumes, so the markdown
stays the single source of truth — edit the doc, the agent's priors change.

Pure logic, no emulator/UI dependency. Loads lazily and degrades to empty roots
if the file is missing, so the agent still runs without it (just less wise)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

# docs/AGENT_ROOTS.md lives at the project root (……/pokeai/docs/), three parents
# up from this file (……/pokeai/src/pokeai/knowledge/roots.py).
DEFAULT_ROOTS_PATH = Path(__file__).resolve().parents[3] / "docs" / "AGENT_ROOTS.md"

_YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class Drive:
    name: str
    priority: int
    trigger: str
    resolves_to: str
    critical: str | None = None


@dataclass(frozen=True)
class StoryGate:
    id: str
    where: str = ""
    blocker: str = ""
    unlock: str = ""
    how: str = ""


@dataclass(frozen=True)
class Town:
    name: str
    has_center: bool = False
    has_mart: bool = False


@dataclass(frozen=True)
class Item:
    name: str
    effect: str = "other"
    when: str = "both"
    amount: object = None
    buy_priority: str = "low"


@dataclass(frozen=True)
class Gym:
    n: int
    town: str = ""
    leader: str = ""
    type: str = ""
    recommended_level: int = 0
    weak_to: tuple[str, ...] = ()
    bring: str = ""


@dataclass
class Roots:
    drives: list[Drive] = field(default_factory=list)
    gates: list[StoryGate] = field(default_factory=list)
    towns: list[Town] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    gyms: list[Gym] = field(default_factory=list)

    # --- lookups the arbiter needs ---

    def item_effect(self, name: str) -> str | None:
        n = name.strip().lower()
        for it in self.items:
            if it.name.strip().lower() == n:
                return it.effect
        return None

    def next_gym(self, badge_count: int) -> Gym | None:
        """The next unbeaten gym = the one numbered badge_count + 1."""
        target = badge_count + 1
        for g in self.gyms:
            if g.n == target:
                return g
        return None

    def town(self, name: str) -> Town | None:
        n = (name or "").strip().lower()
        for t in self.towns:
            if t.name.strip().lower() == n:
                return t
        return None

    def center_town_names(self) -> list[str]:
        return [t.name for t in self.towns if t.has_center]

    def mart_town_names(self) -> list[str]:
        return [t.name for t in self.towns if t.has_mart]


def _merge_yaml_blocks(text: str) -> dict:
    """Parse every ```yaml block and merge their top-level keys into one dict."""
    merged: dict = {}
    for block in _YAML_BLOCK.findall(text):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            for key, value in data.items():
                if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                    merged[key].extend(value)
                else:
                    merged[key] = value
    return merged


def parse_roots(text: str) -> Roots:
    raw = _merge_yaml_blocks(text)
    roots = Roots()

    drives = raw.get("drives") or {}
    if isinstance(drives, dict):
        for name, d in drives.items():
            if not isinstance(d, dict):
                continue
            roots.drives.append(
                Drive(
                    name=name,
                    priority=int(d.get("priority", 0)),
                    trigger=str(d.get("trigger", "")),
                    resolves_to=str(d.get("resolves_to", "explore")),
                    critical=d.get("critical"),
                )
            )
    # Highest priority first — the arbiter takes the first satisfied drive.
    roots.drives.sort(key=lambda d: d.priority, reverse=True)

    for g in raw.get("story_gates") or []:
        if isinstance(g, dict) and g.get("id"):
            roots.gates.append(
                StoryGate(
                    id=str(g["id"]),
                    where=str(g.get("where", "")),
                    blocker=str(g.get("blocker", "")),
                    unlock=str(g.get("unlock", "")),
                    how=str(g.get("how", "")),
                )
            )

    for t in raw.get("towns") or []:
        if isinstance(t, dict) and t.get("name"):
            roots.towns.append(
                Town(
                    name=str(t["name"]),
                    has_center=bool(t.get("has_center", False)),
                    has_mart=bool(t.get("has_mart", False)),
                )
            )

    for it in raw.get("items") or []:
        if isinstance(it, dict) and it.get("name"):
            roots.items.append(
                Item(
                    name=str(it["name"]),
                    effect=str(it.get("effect", "other")),
                    when=str(it.get("when", "both")),
                    amount=it.get("amount"),
                    buy_priority=str(it.get("buy_priority", "low")),
                )
            )

    for gy in raw.get("gyms") or []:
        if isinstance(gy, dict) and gy.get("n") is not None:
            weak = gy.get("weak_to") or []
            roots.gyms.append(
                Gym(
                    n=int(gy["n"]),
                    town=str(gy.get("town", "")),
                    leader=str(gy.get("leader", "")),
                    type=str(gy.get("type", "")),
                    recommended_level=int(gy.get("recommended_level", 0)),
                    weak_to=tuple(str(w) for w in weak),
                    bring=str(gy.get("bring", "")),
                )
            )

    return roots


@lru_cache(maxsize=1)
def load_roots(path: str | None = None) -> Roots:
    """Load + cache the roots. Missing file -> empty roots (agent still runs)."""
    p = Path(path) if path else DEFAULT_ROOTS_PATH
    try:
        return parse_roots(p.read_text(encoding="utf-8"))
    except OSError:
        return Roots()
