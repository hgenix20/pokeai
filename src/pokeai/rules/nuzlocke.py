"""Nuzlocke ruleset — the SSOT for the viewer-driven Nuzlocke challenge.

This module is PURE LOGIC (no bridge, no I/O, no emulator reads): every
Nuzlocke decision lives here so it can be unit-tested without a ROM, and so
`scripts/stream.py`'s `Control` keeps only thin glue that reads live RAM and
calls into these methods. `tests/test_nuzlocke_rules.py` exercises the whole
surface the same way `tests/test_stream_state.py` tests `classify`.

Two structures:

  * `NUZLOCKE_RULES` — the researched rule catalog (Bulbapedia + Nuzlocke
    University core/optional pages), the single list viewers choose from. Each
    entry is a `NuzRule`. Served to the bot verbatim via `GET /api/nuzlocke`.

  * `NuzlockeRuleset` — the live state: the `active` rule set plus a `tracker`
    (deaths, areas used, species owned, encounters). The enforcement seams in
    the game AI call its pure query methods; the worker calls `observe_party`
    each tick to detect deaths and `apply_directive` to add/randomize/clear.

Strict-objectivity: every rule declares `enforced`. Rules with no decision
seam in the current AI (shiny clause, legendaries, mono-type) ship as
display/tracking-only with `enforced=False`; the boards dim them so viewers
are not told the AI enforces something it does not. Nothing here claims an
enforcement the code does not deliver.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

# Area key: (map_group, map_num). Kept as a plain tuple so it is hashable and
# JSON-friendly once listed.
Area = tuple[int, int]


@dataclass(frozen=True)
class NuzRule:
    """One catalog entry. `mandatory` rules are auto-added whenever any
    ruleset is active (the Nuzlocke core). `enforced` is the honest flag: True
    means an existing AI decision seam actually applies it; False means it is
    tracked/displayed only (no seam in v1)."""

    key: str
    name: str
    category: str  # "core" | "optional" | "difficulty"
    description: str
    mandatory: bool = False
    enforced: bool = True


def _rules() -> dict[str, NuzRule]:
    catalog = (
        # --- core (mandatory whenever any ruleset is active) ---
        NuzRule(
            key="permadeath",
            name="Permadeath",
            category="core",
            description="A fainted Pokemon is dead: boxed/unusable for the rest of the run.",
            mandatory=True,
            enforced=True,
        ),
        NuzRule(
            key="first_encounter",
            name="First encounter only",
            category="core",
            description="Only the first wild Pokemon per area may be caught.",
            mandatory=True,
            enforced=True,
        ),
        NuzRule(
            key="nickname_all",
            name="Nickname all",
            category="core",
            description="Every caught Pokemon is nicknamed.",
            mandatory=True,
            enforced=True,
        ),
        # --- optional clauses ---
        NuzRule(
            key="dupes_clause",
            name="Dupes clause",
            category="optional",
            description="Skip a first encounter whose species you already own.",
            enforced=True,
        ),
        NuzRule(
            key="species_clause",
            name="Species clause",
            category="optional",
            description="At most one of each species on the team.",
            enforced=True,
        ),
        NuzRule(
            key="shiny_clause",
            name="Shiny clause",
            category="optional",
            description="Shinies may always be caught and never die.",
            enforced=False,  # no shiny read in the AI yet
        ),
        # --- difficulty options ---
        NuzRule(
            key="set_mode",
            name="Set mode",
            category="difficulty",
            description="No free switches (inherent: the AI has no voluntary switch).",
            enforced=True,  # enforced-by-design
        ),
        NuzRule(
            key="level_cap",
            name="Level cap",
            category="difficulty",
            description="Team may not exceed the next gym leader's ace level.",
            enforced=True,  # enforced where a grind seam exists
        ),
        NuzRule(
            key="no_battle_items",
            name="No battle items",
            category="difficulty",
            description="No healing items mid-battle.",
            enforced=True,
        ),
        NuzRule(
            key="no_pokemon_centers",
            name="No Pokemon Centers",
            category="difficulty",
            description="No Center healing.",
            enforced=True,
        ),
        NuzRule(
            key="no_legendaries",
            name="No legendaries",
            category="difficulty",
            description="Legendaries may not be used.",
            enforced=False,  # display-only v1
        ),
        NuzRule(
            key="mono_type",
            name="Monolocke",
            category="difficulty",
            description="Only one type on the team.",
            enforced=False,  # display-only v1
        ),
    )
    return {r.key: r for r in catalog}


# SSOT catalog. Defined once here; the bot receives it via GET /api/nuzlocke.
NUZLOCKE_RULES: dict[str, NuzRule] = _rules()

# The mandatory core, auto-added whenever a ruleset is active.
CORE_KEYS: tuple[str, ...] = tuple(k for k, r in NUZLOCKE_RULES.items() if r.mandatory)

# The pool a random roll draws its optional/difficulty picks from.
_OPTIONAL_KEYS: tuple[str, ...] = tuple(
    k for k, r in NUZLOCKE_RULES.items() if not r.mandatory
)

# A default team level cap when `level_cap` is active but no specific gym ace
# level has been supplied (Brock's Onix is Lv14 in FireRed).
DEFAULT_LEVEL_CAP = 14

# Nickname pool: uppercase-A-Z only so `Intro.type_name`'s verified keyboard
# (GRID has no digits) can type them. Indexed deterministically by species id.
_NICK_POOL: tuple[str, ...] = (
    "ACE", "BOLT", "CLAW", "DUSK", "EMBER", "FANG", "GALE", "HEX", "IVY",
    "JET", "KILO", "LUX", "MOSS", "NOVA", "ONYX", "PIXEL", "QUARTZ", "RUNE",
    "SOL", "TALON", "UMBRA", "VOLT", "WISP", "XENO", "YONDER", "ZEN",
)


@dataclass
class NuzTracker:
    """The live challenge tally the boards render. All counts are honest,
    derived from what actually happened (deaths observed on RAM, catches
    recorded through the catch seam)."""

    deaths: list[dict] = field(default_factory=list)
    areas_used: set[Area] = field(default_factory=set)
    species_owned: set[int] = field(default_factory=set)
    dead_species: set[int] = field(default_factory=set)
    encounters: int = 0


class NuzlockeRuleset:
    """The live ruleset: which rules are active, plus the tracker. The worker
    is the single owner (`Control.nuzlocke`); the enforcement seams call the
    pure query methods, and the worker calls `observe_party` / `apply_directive`.
    """

    def __init__(self, level_cap: int = DEFAULT_LEVEL_CAP) -> None:
        self.active: set[str] = set()
        self.tracker = NuzTracker()
        self.level_cap = level_cap
        # slots ever seen alive (hp>0): a death only counts as a transition
        # from alive -> fainted, never a slot that was already down when we
        # first looked (e.g. a boxed dead mon re-observed).
        self._ever_alive: set[int] = set()
        # (slot, species) pairs already recorded as dead — idempotency.
        self._death_keys: set[tuple[int, int]] = set()

    # --- rule membership -------------------------------------------------
    def is_active(self) -> bool:
        return bool(self.active)

    def _add_core(self) -> None:
        self.active.update(CORE_KEYS)

    def add_rule(self, key: str) -> bool:
        """Add one rule (and the core). True if `key` is a real rule."""
        if key not in NUZLOCKE_RULES:
            return False
        self.active.add(key)
        self._add_core()
        return True

    def clear(self) -> None:
        """Drop all rules AND reset the tracker — a fresh, un-challenged run."""
        self.active = set()
        self.tracker = NuzTracker()
        self._ever_alive = set()
        self._death_keys = set()

    def randomize(self, rng: Random, n: int | None = None) -> None:
        """Roll a random ruleset: the core plus `n` random optional/difficulty
        rules (default 2-4). `rng` is injectable so tests seed it."""
        self.active = set(CORE_KEYS)
        pool = list(_OPTIONAL_KEYS)
        if n is None:
            n = rng.randint(2, 4)
        n = max(0, min(n, len(pool)))
        self.active.update(rng.sample(pool, n))

    def apply_directive(self, rule: str | None, rng: Random) -> str:
        """The `set_nuzlocke` seam. `rule` is one of:
          * "random"  -> roll the core + N random rules
          * "clear"   -> drop everything (reset the challenge)
          * <rulekey> -> add that rule (and the core)
        Returns a short status string for the worker log. An unknown rule is a
        no-op ("unknown:<rule>") rather than a crash — honest, not silent."""
        rule = (rule or "").strip().lower()
        if rule == "clear":
            self.clear()
            return "cleared"
        if rule == "random":
            self.randomize(rng)
            return "randomized"
        if self.add_rule(rule):
            return f"added:{rule}"
        return f"unknown:{rule}"

    # --- catch decision (first-encounter + dupes + species clauses) ------
    def should_catch(
        self, area: Area, party_species, enc_species: int
    ) -> bool:
        """Whether the AI should attempt to catch this wild encounter under
        the active rules. Under a live ruleset the Nuzlocke default is to catch
        the FIRST encounter in each new area; the dupes/species clauses veto
        it. Returns False when no ruleset is active (the caller falls back to
        its own catch policy)."""
        if not self.active:
            return False
        party = set(party_species or ())
        if "first_encounter" in self.active and self._area_key(area) in self.tracker.areas_used:
            return False
        if "dupes_clause" in self.active and enc_species in (party | self.tracker.species_owned):
            return False
        if "species_clause" in self.active and enc_species in party:
            return False
        return True

    def on_caught(self, area: Area, species: int) -> None:
        """Record a successful catch: this area is now used (its first
        encounter is spent), the species is owned, and the encounter tally
        ticks up."""
        self.tracker.areas_used.add(self._area_key(area))
        if species:
            self.tracker.species_owned.add(int(species))
        self.tracker.encounters += 1

    def nickname_for(self, species: int) -> str | None:
        """The nickname to give a fresh catch, or None when `nickname_all` is
        not active (the caller then declines the nickname prompt as usual).
        Deterministic per species, uppercase-only so the verified keyboard can
        type it."""
        if "nickname_all" not in self.active:
            return None
        return _NICK_POOL[int(species) % len(_NICK_POOL)]

    # --- permadeath (death detection + dead-mon exclusion) ---------------
    def observe_party(self, party_details, area: Area | None = None) -> None:
        """Called each worker tick with the live party (list of dicts with at
        least `species`, `hp`, `max_hp`). When `permadeath` is active, records
        a death the first time a slot transitions from alive (hp>0, seen
        earlier) to fainted (hp==0). Idempotent per (slot, species): re-calling
        with the same fainted slot never double-counts."""
        if "permadeath" not in self.active:
            # still track alive-ness so a later toggle-on has transition history
            for i, mon in enumerate(party_details or ()):
                if (mon.get("hp") or 0) > 0:
                    self._ever_alive.add(i)
            return
        for i, mon in enumerate(party_details or ()):
            species = int(mon.get("species") or 0)
            hp = int(mon.get("hp") or 0)
            max_hp = int(mon.get("max_hp") or 0)
            if hp > 0:
                self._ever_alive.add(i)
                continue
            if max_hp <= 0 or species == 0:
                continue  # empty/placeholder slot
            if i not in self._ever_alive:
                continue  # was never seen alive here — not a transition
            key = (i, species)
            if key in self._death_keys:
                continue
            self._death_keys.add(key)
            self.tracker.dead_species.add(species)
            self.tracker.deaths.append(
                {"slot": i, "species": species, "level": int(mon.get("level") or 0)}
            )

    def is_dead(self, species: int) -> bool:
        """Whether this species is a permadeath casualty (excluded from battle
        participation). False when permadeath is off."""
        if "permadeath" not in self.active:
            return False
        return int(species) in self.tracker.dead_species

    # --- difficulty gates ------------------------------------------------
    def level_cap_ok(self, top_level: int) -> bool:
        """True if the team's top level is within the cap (or the cap is off)."""
        if "level_cap" not in self.active:
            return True
        return int(top_level) <= self.level_cap

    def allow_battle_item(self) -> bool:
        """False when `no_battle_items` is active (suppress mid-battle heals)."""
        return "no_battle_items" not in self.active

    def allow_center(self) -> bool:
        """False when `no_pokemon_centers` is active (suppress Center healing)."""
        return "no_pokemon_centers" not in self.active

    # --- public snapshot for the boards ----------------------------------
    def to_public(self) -> dict:
        """The board/context payload: the active rules (with names + the honest
        `enforced` flag) and the tracker counts. Rules are ordered by the
        catalog so the display is stable."""
        rules = [
            {
                "key": r.key,
                "name": r.name,
                "category": r.category,
                "enforced": r.enforced,
                "mandatory": r.mandatory,
            }
            for r in NUZLOCKE_RULES.values()
            if r.key in self.active
        ]
        return {
            "active": bool(self.active),
            "rules": rules,
            "tracker": {
                "deaths": list(self.tracker.deaths),
                "death_count": len(self.tracker.deaths),
                "encounters": self.tracker.encounters,
                "areas_used": len(self.tracker.areas_used),
                "species_owned": len(self.tracker.species_owned),
            },
        }

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _area_key(area: Area | None) -> Area:
        if area is None:
            return (-1, -1)
        return (int(area[0]), int(area[1]))
