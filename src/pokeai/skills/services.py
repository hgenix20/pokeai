"""Town services skills — heal at a Pokemon Center, buy at a Mart, receive
story items. Built on the overworld arsenal (interact/wait_control) + Navigator
(warps) + FireRedStateReader (RAM ground truth for verification).

LANDMARKS are the (map-id, city-side door) pairs discovered live; the heal/shop
skills route to the door, enter, and drive the counter NPC. Add a row per town
as the story reaches it (verified in-game, never guessed).
"""
from __future__ import annotations

import time

# Viridian City (map 3,1) building IDs — CORRECTED 2026-07-03 with operator
# ground truth (roof colors + which door is what). Interiors entered live:
#   door (25,11) -> map (5,0) = a HOUSE (an NPC, NOT the nurse)
#   door (36,10) -> map (5,1) = the GYM (yellow roof) — BLOCKED by the old man
#                    early game; its approach tile is unreachable, correctly.
#   door (25,18) -> map (5,2) = the Trainer School (blackboard), NOT a shop
#   door (36,19) -> map (5,3) = the POKE MART (blue roof); the clerk here says
#                    "You know PROF. OAK, right?" and hands over Oak's Parcel.
#   door (26,26) -> map (5,4) = the POKEMON CENTER (red roof). The 7/3 session
#                    mis-labeled this "HOUSE (TV)"; the FRLG reference map
#                    (docs/pokemon-red-fire-map.png) shows the P.C. at the
#                    city's bottom-center, and the 2026-07-05 probe confirmed
#                    live: interior 15x10, nurse (7,2), counter-talk from (7,4).
MARTS = {
    # route: waypoint hops for the city walk to the door — a single long BFS
    # plan across the fenced city fails where local hops succeed (the pattern
    # part2_parcel.py proved on this exact walk).
    # Counter geometry LIVE-CORRECTED 2026-07-05: clerk (2,3) behind the WEST
    # counter, counter tile (3,3), customer stands at (4,3) facing LEFT. The
    # old clerk (6,2) was never interaction-verified (the parcel scene
    # auto-fired on entry).
    (3, 1): {"map": (5, 3), "door": (36, 19), "clerk": (2, 3), "stand": (4, 3),
             "face": "LEFT", "route": [(24, 32), (36, 32), (36, 20)]},
    # Pewter: warp-table-verified 2026-07-06 - door (28,18) -> interior
    # (6,3). (The stitch measurement said (29,18); the live warp table
    # corrected it one tile west.) Counter geometry = the FRLG cookie-cutter
    # mart layout live-verified at Viridian.
    (3, 2): {"map": (6, 3), "door": (28, 18), "clerk": (2, 3), "stand": (4, 3),
             "face": "LEFT", "route": [(29, 22)]},
}
CENTERS = {
    (3, 1): {"map": (5, 4), "door": (26, 26), "nurse": (7, 2), "stand": (7, 4)},
    # Pewter + Route 4: discovered live 2026-07-05 (forest_run / part4_run)
    (3, 2): {"map": (6, 5), "door": (17, 25), "nurse": (7, 2), "stand": (7, 4)},
    (3, 22): {"map": (16, 0), "door": (12, 5), "nurse": (7, 2), "stand": (7, 4)},
    # Cerulean: discovered live 2026-07-06 (part4_run stage F, G11)
    (3, 3): {"map": (7, 3), "door": (22, 19), "nurse": (7, 2), "stand": (7, 4)},
}


class Services:
    def __init__(self, bridge, navigator, overworld, reader):
        self.b = bridge
        self.nav = navigator
        self.ow = overworld
        self.reader = reader

    def _ride_out_dialogue(self, step="DOWN", cap=30, button="A") -> bool:
        """Close any lingering dialogue until MOVEMENT returns — the
        unfakeable control signal (2026-07-02 lesson). dialogue_open()'s
        brightness heuristic false-negatives on bright interiors (the nurse's
        closing box stranded the player at the counter, live 2026-07-05), so
        advance_dialogue alone is not enough after a counter conversation.
        button='B' for shop/menu contexts: an A there SELECTS things (it
        re-opened the buy list live 2026-07-05), while B only backs out.
        Side effect: one step in `step` direction when control returns."""
        for _ in range(cap):
            p0 = self.b.player_xy()
            self.b.press_direction_settle(step)
            if self.b.player_xy() != p0:
                return True
            self.b.tap(button, 6)
            time.sleep(0.4)
        return False

    # --- healing ---
    def party_full(self) -> bool:
        s = self.reader.read()
        return s.party_total_hp == s.party_total_max_hp and s.party_count > 0

    def heal_here(self, nurse_tile: tuple[int, int],
                  stand: tuple[int, int] | None = None) -> bool:
        """Assuming we're standing inside a Pokemon Center, talk the nurse
        through the heal. Verifies party HP is full afterward via RAM. The
        A-mash rides: greeting -> YES (default cursor) -> heal jingle -> closing
        line. Returns True only if the party actually came out full.

        The nurse is BEHIND a counter (no walkable neighbour), so when `stand`
        is given we use Gen-3 counter-talk: stand there, face the nurse, A."""
        self.ow.wait_control(15)
        for _ in range(3):
            if stand:
                if not self.nav.go_to(stand):
                    self._ride_out_dialogue()   # a lingering box blocks go_to
                    continue
                self.b.press_button_held("UP", 12)
                time.sleep(0.3)
                self.b.tap("A", 6)
                time.sleep(0.6)
                self.ow.advance_dialogue(cap=40)
            else:
                self.ow.interact(nurse_tile, rounds=4)
                self.ow.advance_dialogue(cap=40)
            # the closing box survives advance_dialogue on bright interiors;
            # close it with the movement-verified ride-out before reading HP
            self._ride_out_dialogue()
            if self.party_full():
                return True
        return self.party_full()

    def heal_at_center(self, city_map: tuple[int, int] | None = None) -> bool:
        """From anywhere in a known town, route to its Center, enter, and heal.
        No-op success if the party is already full."""
        if self.party_full():
            return True
        city = city_map or self.nav.current_map()
        info = CENTERS.get(city)
        if not info:
            return False
        # walk to the door and enter (unless we're already in the Center)
        if self.nav.current_map() != info["map"]:
            self.nav.go_to((info["door"][0], info["door"][1] + 1))
            if self.nav.take_warp(info["door"]) != info["map"]:
                # fallback: step up into the door tile
                self.b.press_button_held("UP", 32)
                time.sleep(1.0)
            if self.nav.current_map() != info["map"]:
                return False
        return self.heal_here(info["nurse"], stand=info.get("stand"))

    # --- shopping ---
    def _enter(self, info) -> bool:
        """info["map"] is None for marts whose interior id is not yet
        recorded: any map change through the door counts as entered (the
        caller's purchase is RAM-verified anyway)."""
        outside = self.nav.current_map()
        if info["map"] is not None and outside == info["map"]:
            return True
        for wp in info.get("route", ()):
            self.nav.go_to(wp, attempts=8)
        self.nav.go_to((info["door"][0], info["door"][1] + 1))
        if self.nav.take_warp(info["door"]) != info["map"]:
            self.b.press_button_held("UP", 32)
            time.sleep(1.0)
        if info["map"] is None:
            return self.nav.current_map() != outside
        return self.nav.current_map() == info["map"]

    def buy_at_mart(self, qty: int = 5, slot: int = 0,
                    city_map: tuple[int, int] | None = None) -> dict:
        """Buy `qty` of the shop-list item at `slot` (0-based; Viridian slot 0 =
        Poke Ball) from the town Mart. Menu driving is open-loop taps; the
        VERIFICATION is RAM ground truth: money delta + bag pocket deltas.

        Deliberately does NOT use Overworld.interact on the clerk: its dialogue
        A-mash would blind-select shop menu entries. We stand at the customer
        side of the counter, face up, and drive the menu explicitly:
        A (greet -> BUY/SELL/QUIT with the greeting box) -> A (BUY) ->
        DOWN x slot -> A -> UP x (qty-1) -> A -> A (confirm YES) -> B ride/exit.
        Returns {'ok', 'spent', 'balls_added', 'item_deltas', 'reason'?}."""
        city = city_map or self.nav.current_map()
        info = MARTS.get(city)
        if not info:
            return {"ok": False, "reason": "unknown_mart"}
        if not self._enter(info):
            return {"ok": False, "reason": "no_entry"}
        self.ow.wait_control(10)
        money0 = self.reader.read_money()
        balls0 = self.reader.ball_count()
        items0 = dict(self.reader.read_bag_pocket("items"))

        cx, cy = info["clerk"]
        stand = info.get("stand", (cx, cy + 2))
        face = info.get("face", "UP")
        if not self.nav.go_to(stand):
            return {"ok": False, "reason": "no_counter_path"}
        self.b.press_button_held(face, 12); time.sleep(0.3)

        def settle(extra=0.3):
            # SETTLE-BASED pacing (the intro lesson): fixed sleeps race the
            # text printer — the qty prompt ate our UP presses live 2026-07-05
            self.ow.wait_settle()
            time.sleep(extra)

        self.b.tap("A", 6); settle(0.6)          # greet -> BUY/SELL/SEE YA
        self.b.tap("A", 6); settle(1.0)          # BUY -> item list (slow open)
        for _ in range(slot):
            self.b.tap("DOWN", 5); time.sleep(0.35)
        # SINGLE-UNIT ROUNDS with per-round money verification: the qty box
        # defaults to x1, so four settle-paced As buy exactly one unit from
        # either the list or the qty box (any 4-A window crosses exactly one
        # YES), and the money delta is the per-round ground truth. Quantity
        # UP-presses proved unverifiable open-loop: when the item-select A got
        # eaten by the list animation they wrapped the LIST cursor instead
        # (live 2026-07-05, cursor ended on ANTIDOTE).
        bought = 0
        attempts = 0
        while bought < qty and attempts < qty * 2 + 2:
            attempts += 1
            m0 = self.reader.read_money()
            self.b.tap("A", 6); settle(0.5)      # select item -> qty x1
            self.b.tap("A", 6); settle(0.5)      # lock qty -> confirm prompt
            self.b.tap("A", 6); settle(0.7)      # YES -> purchase
            self.b.tap("A", 6); settle(0.5)      # "Here you are!" -> list
            if self.reader.read_money() < m0:
                bought += 1
            else:
                self.b.tap("B", 5); settle(0.4)  # realign toward the list
        for _ in range(3):                       # back out: list -> menu -> SEE YA
            self.b.tap("B", 5); settle(0.2)
        # a lingering farewell box would strand us like the nurse's did —
        # B-based ride-out (an A here re-opens the shop)
        self._ride_out_dialogue(step="DOWN", button="B")

        spent = money0 - self.reader.read_money()
        balls_added = self.reader.ball_count() - balls0
        items1 = dict(self.reader.read_bag_pocket("items"))
        deltas = {i: items1.get(i, 0) - items0.get(i, 0)
                  for i in set(items0) | set(items1)
                  if items1.get(i, 0) != items0.get(i, 0)}
        ok = spent > 0 and (balls_added > 0 or bool(deltas))
        return {"ok": ok, "spent": spent, "balls_added": balls_added,
                "item_deltas": deltas}
