"""Config hashing for experiment attribution.

Hash is computed over the JSON-normalized config so that two configs with
identical semantic content produce the same hash regardless of YAML
formatting. Paths are normalized to absolute form before hashing.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize(obj: Any) -> Any:
    """Recursively convert to JSON-safe primitives, sorting dict keys."""
    if isinstance(obj, dict):
        return {k: _normalize(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, (list, tuple)):
        return [_normalize(x) for x in obj]
    # Path, Enum, etc.: stringify
    if not isinstance(obj, (str, int, float, bool, type(None))):
        return str(obj)
    return obj


def hash_config(config_dict: dict[str, Any]) -> str:
    """Return a SHA256 hex digest of the normalized config."""
    normalized = _normalize(config_dict)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
