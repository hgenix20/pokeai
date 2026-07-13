"""G3: LIVE-VERIFY the event-flag region against known flag ids.

Method: diff the SaveBlock1 flags region between slot 2 (post-rival, NO Pokedex)
and slot 6 (parcel delivered, Pokedex received). Ground truth expectations
(pokefirered flag ids):
  * FLAG_SYS_POKEMON_GET  0x828 - SET in both (we own CLAW in both states)
  * FLAG_SYS_POKEDEX_GET  0x829 - CLEAR in slot 2, SET in slot 6
  * badges 0x820-0x827    - CLEAR in both (no gym beaten)
A pass proves SB1_FLAGS_OFF (0x0EE0) resolves real flags by id, upgrading the
region from CANDIDATE to VERIFIED. Also prints every flipped flag id for the
record. stream.py STOPPED.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import (
    EVENT_FLAGS_BYTES,
    SB1_FLAGS_OFF,
    FireRedStateReader,
)

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
FLAG_SYS_POKEMON_GET = 0x828
FLAG_SYS_POKEDEX_GET = 0x829


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def flags_dump(b) -> bytes:
    p = b.read_u32(0x03005008)
    return bytes(b.read_range(p + SB1_FLAGS_OFF, p + SB1_FLAGS_OFF + EVENT_FLAGS_BYTES))


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    r = FireRedStateReader(b)

    dumps = {}
    checks = {}
    for slot in (2, 6):
        if not b.load_state(SLOTS + rf"\slot_{slot}.state"):
            say(f"FAIL slot {slot} load")
            return 1
        time.sleep(1.0)
        dumps[slot] = flags_dump(b)
        checks[slot] = {
            "pokemon_get": r.read_flag(FLAG_SYS_POKEMON_GET),
            "pokedex_get": r.read_flag(FLAG_SYS_POKEDEX_GET),
            "badges": r.read_badges(),
        }
        say(f"slot {slot}: pokemon_get={checks[slot]['pokemon_get']} "
            f"pokedex_get={checks[slot]['pokedex_get']} badges={checks[slot]['badges']}")

    flipped = []
    for i in range(EVENT_FLAGS_BYTES):
        if dumps[2][i] != dumps[6][i]:
            for bit in range(8):
                b2, b6 = dumps[2][i] >> bit & 1, dumps[6][i] >> bit & 1
                if b2 != b6:
                    flipped.append((i * 8 + bit, b2, b6))
    say(f"{len(flipped)} flags differ between slot 2 and slot 6:")
    for fid, was, now in flipped[:40]:
        say(f"  flag {fid:#05x}: {was} -> {now}")

    ok = (checks[2]["pokemon_get"] and checks[6]["pokemon_get"]
          and not checks[2]["pokedex_get"] and checks[6]["pokedex_get"]
          and checks[2]["badges"] == 0 and checks[6]["badges"] == 0)
    say("PASS - flags region VERIFIED (dex flag 0x829 behaves exactly as expected)"
        if ok else "FAIL - expectations not met; region base may be wrong")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
