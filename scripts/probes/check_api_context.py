"""G0 acceptance: GET /api/context serves live RAM during a session.

Run with stream.py already up and EmuHawk launched with ai_bridge.lua.
Waits for the bridge, loads save slot 2 (post-rival: CLAW lv6, $3080, lab),
then asserts the context endpoint reflects the real game state.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"


def get_ctx() -> dict:
    with urllib.request.urlopen(BASE + "/api/context", timeout=3) as r:
        return json.load(r)


def post(cmd: str, **kw) -> None:
    data = json.dumps({"cmd": cmd, **kw}).encode()
    req = urllib.request.Request(BASE + "/cmd", data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3).read()


def main() -> int:
    deadline = time.time() + 120
    ctx = None
    while time.time() < deadline:
        try:
            ctx = get_ctx()
            if ctx.get("connected"):
                break
        except Exception:
            pass
        time.sleep(1.5)
    if not (ctx and ctx.get("connected")):
        print(f"FAIL: bridge never connected: {ctx}")
        return 1
    print("connected; loading slot 2 ...")
    post("load_slot", n=2)
    time.sleep(8)
    ctx = get_ctx()
    print(json.dumps(ctx, indent=1))
    checks = {
        "money==3080": ctx.get("money") == 3080,
        "party[0] CLAW": bool(ctx.get("party")) and ctx["party"][0].get("name") == "CLAW",
        "level 6": bool(ctx.get("party")) and ctx["party"][0].get("level") == 6,
        "state PALLET_TOWN": ctx.get("stream_state") == "PALLET_TOWN",
        "fresh": time.time() - ctx.get("updated_at", 0) < 5,
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print("G0 ACCEPTANCE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
