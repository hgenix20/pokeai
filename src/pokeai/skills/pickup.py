"""Item-ball pickup skill (FIXLIST forest-item-steps-missing /
mt-moon-items-never-picked-up / fossil-grab-blind-and-one-shot).

FireRed ground items are ObjectEvents: a Poke Ball sprite you walk up to and
press A on, exactly like an NPC. `Overworld.interact` already owns the
walk-to-adjacent / face / A / advance-dialogue sequence; this module adds the
two things a *pickup* needs on top of it:

  1. finding the item objects (vision.object_tiles gives every ObjectEvent
     tile; we can't tell a ball from an NPC by tile alone, so a pickup is
     "interact, then check the bag grew"), and
  2. VERIFYING via a RAM bag-delta - the only honest proof a pickup worked
     (the pattern scripts/part4_run.py used for the fossil). A pickup that
     does not grow the bag is reported as a miss, never a silent success.

Two entry points:
  - `grab_at(target)`: interact with one known object tile, return the item
    id gained (or None). Used when the caller knows where the ball is.
  - `sweep(max_tiles, radius)`: interact with the nearest unvisited object
    tiles within `radius` until `max_tiles` pickups land or the candidates
    run out. Used to clear a floor/area's item balls opportunistically.

No emulator calls at import; every dependency is injected (bridge, reader,
nav, overworld), so the logic is unit-tested with fakes.
"""
from __future__ import annotations


class Pickup:
    def __init__(self, bridge, reader, nav, overworld):
        self.b = bridge
        self.reader = reader
        self.nav = nav
        self.ow = overworld
        self._grabbed: set[tuple[int, int]] = set()   # tiles already taken

    # --- bag snapshot (all three item pockets, id -> qty) ------------------
    def _bag(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for pocket in ("items", "balls", "key_items"):
            try:
                for item_id, qty in self.reader.read_bag_pocket(pocket):
                    out[item_id] = out.get(item_id, 0) + qty
            except Exception:
                pass
        return out

    @staticmethod
    def _delta(before: dict[int, int], after: dict[int, int]) -> int | None:
        """The first item id whose quantity grew, or None."""
        for item_id, qty in after.items():
            if qty > before.get(item_id, 0):
                return item_id
        return None

    # --- one known object --------------------------------------------------
    def grab_at(self, target: tuple[int, int], rounds: int = 4) -> int | None:
        """Interact with the object at `target`; return the item id gained
        (bag-delta verified) or None if nothing was picked up."""
        before = self._bag()
        self.ow.interact(target, rounds=rounds)
        item = self._delta(before, self._bag())
        if item is not None:
            self._grabbed.add(target)
        return item

    # --- opportunistic area sweep -----------------------------------------
    def sweep(self, max_tiles: int = 8, radius: int = 8,
              narrate=None) -> list[int]:
        """Interact with the nearest unvisited object tiles within `radius`
        (Manhattan) until `max_tiles` pickups land or candidates run out.
        Returns the list of item ids gained. Object tiles that yield nothing
        are remembered so an NPC is not poked twice."""
        say = narrate or (lambda m: None)
        got: list[int] = []
        for _ in range(max_tiles):
            px, py = self.nav.vision.player_xy()
            cands = sorted(
                (t for t in self.nav.vision.object_tiles()
                 if t not in self._grabbed
                 and abs(t[0] - px) + abs(t[1] - py) <= radius),
                key=lambda t: abs(t[0] - px) + abs(t[1] - py))
            if not cands:
                break
            target = cands[0]
            item = self.grab_at(target)
            # mark visited either way: a non-item object (NPC/sign) must not
            # be re-poked every sweep (the try_fossil 10-min sink lesson)
            self._grabbed.add(target)
            if item is not None:
                got.append(item)
                say(f"  picked up item {item} at {target}")
        return got
