"""Live smoke test for the viewer-driven Nuzlocke feature.

Run `scripts/stream.py` (with a ROM + BizHawk connected) first, then run this
against the local control process. It drives the SAME seam the Twitch bot uses
(`POST /api/directive` -> `set_nuzlocke`) and reads back `GET /api/nuzlocke`
and `GET /state`, so you can confirm the ruleset is live and the viewer board
would render the NUZLOCKE section.

Usage:
    C:/pokeai-venv/Scripts/python.exe scripts/smoke_nuzlocke.py            # random roll
    C:/pokeai-venv/Scripts/python.exe scripts/smoke_nuzlocke.py permadeath # add one rule
    C:/pokeai-venv/Scripts/python.exe scripts/smoke_nuzlocke.py clear      # wipe

The nickname-on-catch path (Catch.attempt(nickname=...)) is the only genuinely
new emulator interaction and CANNOT be verified from here: trigger a wild
encounter in-game under an active ruleset with `nickname_all` and confirm the
AI answers the "give a nickname?" prompt YES and types the name, then re-run
this script to see the death/encounter tracker move.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8777"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # 400 still carries a JSON body
        return json.loads(e.read().decode("utf-8"))


def main() -> int:
    rule = sys.argv[1] if len(sys.argv) > 1 else "random"
    print(f"-> POST /api/directive set_nuzlocke(rule={rule!r})")
    resp = _post("/api/directive", {"directive": "set_nuzlocke", "args": {"rule": rule}})
    print("   response:", resp)
    if not resp.get("ok"):
        print("   directive refused; is set_nuzlocke on the whitelist?")
        return 1

    # the worker consumes at its safe-point cadence; give it a beat by polling.
    import time
    time.sleep(1.5)

    nuz = _get("/api/nuzlocke")
    active = nuz.get("active", [])
    print(f"\nGET /api/nuzlocke: {len(nuz.get('catalog', []))} rules in catalog, "
          f"{len(active)} active")
    for r in active:
        flag = "enforced" if r.get("enforced") else "display-only"
        print(f"   - {r['name']} ({flag})")
    print("   tracker:", nuz.get("tracker"))

    state = _get("/state")
    snap = state.get("nuzlocke")
    print("\nGET /state nuzlocke snapshot:", "present" if snap else "None (section hidden)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
