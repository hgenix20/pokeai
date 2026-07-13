"""Catcher strategy: FILL THE PARTY TO 6 of anything (docs/CORE_GAMEPLAY.md §8,
locked 2026-07-03). The first concrete strategy and the template for the rest.

It drives the deterministic skills (hunt grass -> Catch skill) and yields control
back with a status the NeedsArbiter can act on: when balls run low it returns
`out_of_balls` (arbiter fires the restock drive -> mart), when the lead faints it
returns `party_hurt` (arbiter fires heal -> center). The strategy owns the WHAT
(fill the party); it does not press buttons itself beyond hunting grass.

v2: weakens each foe to ~30% HP before throwing (Catch.attempt(weaken_to=...))
and reads the REAL ball count from the bag (FireRedStateReader.ball_count) each
loop instead of decrementing a caller-supplied budget.
"""
from __future__ import annotations

import time

from pokeai.agents.field_brain import flee_or_fight
from pokeai.emulator.firered_state_reader import (
    FireRedStateReader,
    GPLAYER_PARTY_COUNT,
)

# grass-pacing walk pattern; a real wild battle is active AND movement-locked
# (plain gEnemyParty check false-positives on a stale post-battle enemy).
_PACE = ["LEFT", "LEFT", "UP", "RIGHT", "DOWN", "LEFT", "UP", "RIGHT"]


class CatcherStrategy:
    name = "catch_fill6"
    goal = "Fill the party to 6"

    def __init__(self, bridge, nav, battle, catch, target_party=6, reader=None,
                 ruleset=None):
        self.b = bridge
        self.nav = nav
        self.battle = battle
        self.catch = catch
        self.target = target_party
        self.reader = reader or FireRedStateReader(bridge)
        # Optional Nuzlocke ruleset: gates catches (first-encounter/dupes/
        # species clauses) and supplies nicknames. None = catch everything.
        self.ruleset = ruleset

    def party_count(self) -> int:
        return self.b.read_byte(GPLAYER_PARTY_COUNT)

    def _in_real_battle(self) -> bool:
        # the STRONG three-signal test (enemy + movement lock + menu responds);
        # a stale gEnemyParty otherwise false-positives after any flee/catch
        return self.catch.confirm_real_battle()

    def _nearest_grass(self, grass, walk) -> tuple[int, int] | None:
        """BFS from the player over walkable tiles to the closest grass tile."""
        from collections import deque
        start = self.nav.vision.player_xy()
        seen = {start}
        q = deque([start])
        while q:
            x, y = q.popleft()
            if (x, y) in grass and (x, y) != start:
                return (x, y)
            for nb in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
                if nb in walk and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        return None

    def hunt_grass(self, max_steps=80) -> bool:
        """Pace INSIDE tall grass until a REAL wild battle starts. Grass-aware:
        encounters only fire on steps in grass (Route 1 lesson), and a blind
        pacing pattern drifts out of the patch, so every step targets a grass
        neighbour; if we're outside, BFS to the nearest reachable grass first."""
        steps = 0
        while steps < max_steps:
            if self.battle.active() and self._in_real_battle():
                return True
            grid = self.nav.vision.nav_grid()
            npcs = self.nav.vision.object_tiles()
            grass = grid["grass"] - npcs
            walk = grid["walk"] - npcs
            pos = self.nav.vision.player_xy()
            if pos not in grass:
                target = self._nearest_grass(grass, walk)
                if not target:
                    return False
                path = self.nav.plan(target)
                if not path:
                    return False
                self.nav.walk_path(path)   # a battle interrupt surfaces next loop
                steps += len(path)
                continue
            dirs = [("LEFT", (-1, 0)), ("UP", (0, -1)),
                    ("RIGHT", (1, 0)), ("DOWN", (0, 1))]
            n = len(dirs)
            moved = False
            for k in range(n):
                dname, (dx, dy) = dirs[(steps + k) % n]
                if (pos[0] + dx, pos[1] + dy) in grass:
                    self.b.press_direction_settle(dname)
                    moved = True
                    break
            if not moved:
                # isolated grass tile: hop to any walkable neighbour and back next loop
                for dname, (dx, dy) in dirs:
                    if (pos[0] + dx, pos[1] + dy) in walk:
                        self.b.press_direction_settle(dname)
                        break
            steps += 1
            time.sleep(0.05)
        return False

    def run(self, ball_budget=None, max_encounters=20, low_ball_floor=0,
            weaken_to=0.30, narrate=None):
        """Hunt + catch until the party is full, balls run out, the lead faints,
        or the encounter cap is hit. Returns a result dict; `status` is one of
        'party_full' | 'out_of_balls' | 'party_hurt' | 'no_encounters' | 'cap'.

        Ball accounting is RAM-honest: the bag's balls pocket is re-read every
        loop. `ball_budget` (optional) additionally caps how many balls this run
        may consume, for callers that want to reserve some."""
        caught = 0
        spent = 0
        start = self.party_count()

        def say(m):
            if narrate:
                narrate(m)

        def balls_now() -> int:
            n = self.reader.ball_count()
            if ball_budget is not None:
                n = min(n, ball_budget - spent)
            return n

        for enc in range(max_encounters):
            balls = balls_now()
            if self.party_count() >= self.target:
                return self._result("party_full", start, caught, balls, enc)
            if balls <= low_ball_floor:
                return self._result("out_of_balls", start, caught, balls, enc)
            if not self.hunt_grass():
                return self._result("no_encounters", start, caught, balls, enc)

            say(f"encounter {enc + 1}: wild lv{self.battle.enemy_stats()[0]} "
                f"(party {self.party_count()}/{self.target}, {balls} balls)")
            # Nuzlocke gate: when a ruleset is active, only the first encounter
            # per area (minus dupes/species clauses) may be caught; a skipped
            # encounter is fled so the hunt continues.
            enc_species = self.battle.enemy_species()
            area = self.nav.current_map()
            nickname = None
            if self.ruleset is not None and self.ruleset.is_active():
                if not self.ruleset.should_catch(
                        area, self.catch.party_species(), enc_species):
                    say("nuzlocke: rules say skip this one - fleeing")
                    flee_or_fight(self.b, self.battle, self.catch)
                    continue
                nickname = self.ruleset.nickname_for(enc_species)
            res = self.catch.attempt(max_balls=min(balls, 5), narrate=narrate,
                                     weaken_to=weaken_to, nickname=nickname)
            spent += self.catch.balls_thrown
            if res == "caught":
                caught += 1
                if self.ruleset is not None and self.ruleset.is_active():
                    self.ruleset.on_caught(area, enc_species)
                say(f"caught #{caught}; party now {self.party_count()}")
            elif res == "fainted_target":
                say("weakening KO'd the foe; hunting the next one")
            elif res == "lost":
                return self._result("party_hurt", start, caught, balls_now(), enc)
            elif res == "no_menu":
                say("menu never came up; ending run")
                return self._result("no_encounters", start, caught, balls_now(), enc)
            # 'out_of_balls' from a single encounter just means unlucky this fight;
            # the loop's balls check handles the real empty-bag case.

        return self._result("cap", start, caught, balls_now(), max_encounters)

    def _result(self, status, start, caught, balls, encounters):
        return {
            "status": status,
            "caught": caught,
            "party_start": start,
            "party_now": self.party_count(),
            "balls_left": max(balls, 0),
            "encounters": encounters,
        }
