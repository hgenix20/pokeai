"""Finish the 'Get my first Pokémon' quest: advance 'CLAUDE received X!' and say
YES to the nickname prompt (reusing the verified intro keyboard), name the starter
CLAW (uppercase — the naming skill/keyboard is uppercase, matching CLAUDE/GROK),
confirm, and verify the nickname from RAM. Stops before the rival cutscene.
Resettable via slot 0."""
from __future__ import annotations

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import GPLAYER_PARTY, FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"
NICK = "CLAW"
NICK_OFF = 0x08   # nickname (10 bytes, plaintext) within a party slot


def decode_name(bs) -> str:
    out = []
    for x in bs:
        if x == 0xFF:
            break
        if 0xBB <= x <= 0xD4:
            out.append(chr(ord("A") + x - 0xBB))
        elif 0xD5 <= x <= 0xEE:
            out.append(chr(ord("a") + x - 0xD5))
        else:
            out.append("?")
    return "".join(out)


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)
    intro = ow.screen

    f = intro.grab()
    print(f"before: party={reader.read().party_count} keyboard={intro.is_keyboard(f)} "
          f"dialogue={ow.dialogue_open(f)}", flush=True)
    b.screenshot(OUT + r"\nick_before.png")

    # advance "received X!" + select YES on the nickname prompt -> naming keyboard
    if intro.advance_until(intro.is_keyboard) is None:
        print("never reached the nickname keyboard", flush=True)
        b.screenshot(OUT + r"\nick_nokbd.png")
        b.close()
        return 1

    print(f"at keyboard; typing {NICK}", flush=True)
    intro.type_name(NICK)
    intro.confirm()
    intro.wait_stable()

    nick_bytes = b.read_range(GPLAYER_PARTY + NICK_OFF, GPLAYER_PARTY + NICK_OFF + 10)
    after = intro.grab()
    print(f"after: party={reader.read().party_count} keyboard={intro.is_keyboard(after)} "
          f"nickname={decode_name(nick_bytes)!r} map={nav.current_map()} pos={ow.pos()}", flush=True)
    b.screenshot(OUT + r"\nick_after.png")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
