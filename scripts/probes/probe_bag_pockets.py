"""Live verification of the formalized FireRedStateReader bag/party/move reads.

Loads slot 8 (Route 1, 5 Poke Balls, CLAW the Squirtle lv6) and checks every
new reader API against known ground truth:
  * balls pocket   -> exactly [(4, 5)]  (Poke Ball x5, delivered by Oak 7/3)
  * read_moves(0)  -> Tackle (33) and Tail Whip (39) among the 4 slots
                      (first live proof of the Attacks-substruct decode)
  * read_party_details / party_fainted_count -> CLAW 22/22 lv6, 0 fainted
  * ball_count() == 5, count_heal_items() sane (>= 0)

Run with stream.py STOPPED (single bridge owner).
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    r = FireRedStateReader(b)

    say("loading slot 8…")
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL: slot load")
        return 1
    time.sleep(1.0)

    s = r.read()
    say(f"map ({s.current_map >> 8},{s.current_map & 0xFF}) pos ({s.x_pos},{s.y_pos}) "
        f"money {s.money} party {s.party_count}")

    ok = True

    balls = r.read_bag_pocket("balls")
    say(f"balls pocket: {balls}")
    if balls != [(4, 5)]:
        say("FAIL: expected [(4, 5)] in balls pocket")
        ok = False

    items = r.read_bag_pocket("items")
    key_items = r.read_bag_pocket("key_items")
    say(f"items pocket: {items}")
    say(f"key items pocket: {key_items}")
    if any(q < 1 or q > 99 for _, q in items):
        say("FAIL: implausible quantity in items pocket (bad offset or key?)")
        ok = False

    say(f"ball_count()={r.ball_count()}  count_heal_items()={r.count_heal_items()}")
    if r.ball_count() != 5:
        say("FAIL: ball_count != 5")
        ok = False

    party = r.read_party_details()
    say(f"party details: {party}")
    say(f"fainted count: {r.party_fainted_count()}")
    if not party or party[0]["max_hp"] <= 0 or party[0]["level"] != 6:
        say("FAIL: party slot 0 should be lv6 with hp>0")
        ok = False
    if r.party_fainted_count() != 0:
        say("FAIL: fainted count should be 0")
        ok = False

    moves = r.read_moves(0)
    say(f"slot 0 moves (id, pp): {moves}")
    ids = [m for m, _ in moves]
    if 33 not in ids or 39 not in ids:
        say("FAIL: expected Tackle(33) + Tail Whip(39) in CLAW's moves")
        ok = False
    if any(pp > 64 for _, pp in moves):
        say("FAIL: implausible PP (>64) — decode off?")
        ok = False

    say("PASS — bag pockets, party details, and move decode all verified live"
        if ok else "PROBE FAILED — see FAIL lines above")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
