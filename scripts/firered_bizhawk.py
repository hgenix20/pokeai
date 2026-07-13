"""Run the FireRed story brain on BizHawk (EmuHawk).

This is the BizHawk-era replacement for the discarded Docker server
`firered_live.py`. BizHawk plays FireRed natively and IS the game window
(smooth video + audio, and the surface CrowdControl plugs into), so there is no
frame/audio streaming here — only the AI brain talking to the running game over
the socket bridge.

Setup (coexists with CrowdControl):
  1. In the already-running CrowdControl EmuHawk, open Tools > Lua Console and
     load `bizhawk/ai_bridge.lua` (it connects to this script on port 51055;
     CrowdControl's connector uses 23884, so the two do not conflict).
     Do NOT launch a second EmuHawk — BizHawk is single-instance and a new one
     takes over the running game.
  2. Run this:  C:/pokeai-venv/Scripts/python.exe scripts/firered_bizhawk.py

The whole nav stack (FireRedStateReader, FireRedVision, Navigator, NavigateTo,
StoryAgent/Explorer) is wired onto BizHawkBridge unchanged — the verified
FireRed addresses are ROM-specific, not emulator-specific.
"""
from __future__ import annotations

import argparse
import sys
import time

from pokeai.agents.firered_story import Explorer, StoryAgent, vision_ascii
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.navigate_to import NavigateTo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", choices=["story", "explore"], default="story")
    ap.add_argument("--port", type=int, default=51055)
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="seconds to wait for ai_bridge.lua to connect")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="extra sleep between brain steps (s)")
    args = ap.parse_args()

    def log(msg: str) -> None:
        print(f"  · {msg}", flush=True)

    bridge = BizHawkBridge(port=args.port, timeout=args.timeout)
    print(f"listening on 127.0.0.1:{args.port} — load bizhawk/ai_bridge.lua in "
          f"the running EmuHawk's Lua Console…", flush=True)
    try:
        bridge.wait_for_bizhawk()
    except Exception as e:
        print(f"FAIL: BizHawk never connected ({type(e).__name__}: {e})")
        return 2
    print("connected. ping:", bridge.ping(), flush=True)

    nav = Navigator(bridge)
    reader = FireRedStateReader(bridge)
    skill = NavigateTo(bridge, nav)
    story = StoryAgent(bridge, nav, skill, log)
    explorer = Explorer(bridge, nav, log)

    last_map = None
    try:
        while True:
            # Drive one brain step (fall back to exploring once the story is done).
            if args.strategy == "explore":
                explorer.step()
                thought = explorer.thought
            else:
                story.step()
                thought = story.thought
                if story.idx >= len(story.objs):
                    explorer.step()
                    thought = explorer.thought

            # On a map change, dump the collision grid for review.
            try:
                cur = nav.current_map()
            except Exception:
                cur = None
            if cur is not None and cur != last_map:
                last_map = cur
                print(f"=== entered map {cur} ===", flush=True)
                for row in vision_ascii(nav.vision, nav):
                    print("    " + row, flush=True)

            # Compact live state line.
            try:
                s = reader.read()
                print(f"map={cur} pos=({s.x_pos},{s.y_pos}) money={s.money} "
                      f"party={s.party_count} badges={s.badge_count} | {thought}",
                      flush=True)
            except Exception as e:
                print(f"[state read failed: {type(e).__name__}] | {thought}", flush=True)

            if args.delay:
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nstopping (Ctrl+C).", flush=True)
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
