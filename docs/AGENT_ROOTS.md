# Agent "Roots" — the human priors the AI starts with

This is the knowledge you hand the agent so it plays like a person instead of a
mapper that bumps into story gates. Fill in the YAML blocks below; I build the
**Needs/Goal arbiter** that consumes them.

> **Status:** ported to Gen-3 Pokémon **FireRed** (ROM: FireRed/LeafGreen, Kanto
> remake) through ~Vermilion, plus the well-known later gates (Snorlax, Saffron
> guards), an **easy-difficulty** gym level curve, and a secrets/exploits/glitches
> section (§6). Rows marked `source: prior` are asserted facts; `source: learn`
> are guesses the agent confirms/overwrites in run memory. **Version: FireRed
> (Gen 3).** FRLG remakes the original Kanto map almost tile-for-tile, so most
> Gen-1 geography/story-gate knowledge carries over unchanged; what actually
> changed between generations is called out explicitly below (mostly battle
> mechanics in §6, plus a couple of new items/mechanics like Rock Smash and
> Abilities).

## How to think about what goes here

Two kinds of knowledge — only one of them is your job:

- **Priors / seed facts (author these):** genre judgment + a *small* seed of
  Pokémon specifics that would take the agent ages to discover on its own
  (where towns' services are, the handful of early story gates, rough level
  targets). Keep it to roughly the first 2–3 towns; that's enough to prove it.
- **Specifics (it learns these):** what each item *actually* does (use it, watch
  HP rise → "this heals"), exact tile locations, etc. It stores these in run
  memory. You don't have to fill everything — blanks mean "let it learn."

Every row has a `source:` so we're honest about which is which:
`prior` (you assert it) or `learn` (seed a guess, agent confirms/overwrites).

**You do NOT need to be exhaustive.** A few good rows per table beats a perfect
encyclopedia. Mark anything you're unsure of `source: learn` and move on.

---

## 1. Drives — what the agent wants, and in what order

Each step the arbiter scores these and acts on the most urgent. You set the
*thresholds* and the *priority order*. (Numbers are starting points — tune to
taste; higher `priority` wins ties.)

```yaml
drives:
  # Survive: don't let the team faint. Heal when the party is hurt.
  # The full locked heal rule (CORE_GAMEPLAY §9): aggregate HP low, OR anyone
  # fainted, OR at least half the party under half HP. fainted_count and
  # half_party_low became real context facts 2026-07-05 (FireRed
  # read_party_details); the FireRed context builder (agents/field_brain.py)
  # supplies them, the old Red _context simply never defines them (an unknown
  # name just means that clause doesn't fire).
  survive:
    priority: 100
    trigger: party_hp_fraction < 0.35 or fainted_count >= 1 or half_party_low
    critical: party_hp_fraction < 0.15  # below this, also flee battles
    resolves_to: heal                   # go to a Pokémon Center (or use items)

  # Restock balls: a catcher with an empty balls pocket is just a tourist.
  # ball_count reads the real bag (balls pocket, security-key XOR verified
  # 2026-07-05); 200 = one Poke Ball at the mart.
  restock_balls:
    priority: 90
    trigger: ball_count < 2 and money >= 200 and mart_known
    resolves_to: restock

  # Progress: when there's nothing left to explore, find the thing blocking me.
  progress:
    priority: 70
    trigger: exploration_exhausted      # mapped out + everyone talked to
    resolves_to: unblock_gate

  # Rest before a gym: walk in at full HP/PP, not chipped. (author-added pattern)
  rest_before_gym:
    priority: 60
    trigger: at_gym_town and next_gym_unbeaten and party_hp_fraction < 0.95
    resolves_to: heal

  # Prepare: stock up when I can afford it and I'm low on healing items.
  prepare:
    priority: 50
    trigger: money > 500 and healing_items < 3 and mart_known
    resolves_to: shop

  # Grow: be strong enough for the next gym before challenging it. (The agent
  # advances through the game while training — see the train_or_catch executor —
  # levelling off what it meets, rather than farming one grass patch forever.)
  grow:
    priority: 40
    trigger: party_top_level < next_gym_recommended_level
    resolves_to: train_or_catch

  # Fill the party: catch when the roster is below target, there is something
  # to catch here, and we have balls to throw. party_target / wild_available
  # come from the active strategy preset (CORE_GAMEPLAY §8).
  fill_party:
    priority: 30
    trigger: party_count < party_target and wild_available and ball_count > 0
    resolves_to: catch

  # Explore: the default when no stronger need is pressing.
  explore:
    priority: 10
    trigger: always
    resolves_to: explore
```

> Add/rename drives freely. If you want a "rest at full HP before a gym" drive
> (added above), or "avoid grass when the lead is weak," write it here in the
> same shape. `rest_before_gym` sits *below* survive/progress so it never
> overrides an emergency or a real blocker — it only fires in calm moments at a
> gym town.

---

## 2. Story gates — the blocks that aren't walls

The big one. For each early-game blocker: what blocks you, and what clears it.
`unlock` is what the agent must accomplish; `how` is the human hint for where to
go. Locations can be vague ("north exit of Viridian") — the arbiter pairs them
with the live map. FireRed's Kanto is essentially the same map as Red's, so
these gates are unchanged in substance from the Gen-1 roots; wording below is
just re-checked against FRLG specifically.

```yaml
story_gates:
  # 1 — the sleepy old man in Viridian. Blocks the whole game's first artery.
  - id: viridian_old_man
    where: "Viridian City, blocks the north exit toward Route 2"
    blocker: "old man lying down / 'needs his coffee'"
    unlock: "deliver Oak's Parcel to Prof. Oak, then return"
    how: >
      Pick up Oak's Parcel from the clerk at the Viridian Poké Mart, carry it
      south to Oak's lab in Pallet Town, then return north. The old man wakes,
      gives a catching demo, and the path to Route 2 opens.
    source: prior

  # 2 — Pewter → Route 3. Confirmed: hard-blocks until Brock is beaten.
  - id: pewter_route3_guard
    where: "Pewter City, the eastern exit toward Route 3"
    blocker: "a man stands in the gap to Route 3 and won't let you pass"
    unlock: "defeat Brock at the Pewter Gym (earn the Boulder Badge)"
    how: >
      Beat the Pewter Gym first; the man then steps aside and the east exit to
      Route 3 (→ Mt. Moon) opens. Until then, treat the east edge as a wall.
    source: prior

  # 3 — Mt. Moon: a dungeon, not a door. Cerulean is only reachable through it.
  - id: mt_moon_traverse
    where: "Route 3 north end → Mt. Moon cave → exits to Route 4 → Cerulean"
    blocker: "no overworld path east; the only route is through the cave"
    unlock: "navigate Mt. Moon and take a northeast exit"
    how: >
      Enter the cave, work through its levels (Team Rocket grunts + a fossil
      choice: Dome or Helix — either is fine), exit onto Route 4, walk east into
      Cerulean. Treat the cave as a maze to map, not a gate to unlock.
    source: prior

  # 4 — Nugget Bridge: a trainer gauntlet gating Route 25 / Bill.
  - id: nugget_bridge
    where: "Cerulean City north exit → Route 24 (the long bridge)"
    blocker: "5 trainers in a row, then a Team Rocket recruiter"
    unlock: "beat each trainer in sequence to cross north"
    how: >
      Walk north out of Cerulean and fight up the bridge one trainer at a time.
      At the top, refuse the Rocket's offer and beat him for a Nugget, then
      continue to Route 25.
    source: prior

  # 5 — Bill (Route 25) hands the S.S. Ticket: the key to Vermilion's ship.
  - id: bill_ss_ticket
    where: "Route 25, Bill's cottage at the far east end (past Nugget Bridge)"
    blocker: "no ship access in Vermilion without a ticket"
    unlock: "help Bill (he's stuck merged with a Pokémon) → he gives S.S. Ticket"
    how: >
      Reach Bill's house at the end of Route 25, trigger the teleporter event,
      separate him, and he gives the S.S. Ticket. Carry it south to Vermilion to
      board the S.S. Anne.
    source: prior

  # 6 — S.S. Anne → Cut (HM01) → Vermilion Gym. The classic "stuck" point.
  - id: ssanne_cut_gym
    where: "Vermilion City harbor (ship) and the tree blocking the Gym path"
    blocker: "a cuttable tree blocks the path to Lt. Surge's Gym"
    unlock: "board the S.S. Anne with the ticket, beat rival, get HM01 Cut from
             the Captain, teach it, cut the tree"
    how: >
      Use the S.S. Ticket to board, fight through trainers + the rival, heal the
      seasick Captain to receive HM01 Cut. Teach Cut to a party member, then cut
      the small tree outside the Gym to reach Lt. Surge. (Cut also opens many
      overworld trees afterward; Rock Smash — new in Gen 3 — separately clears
      cracked boulders on some routes and is worth teaching to a spare mon.)
    source: prior

  # 7 — Saffron City: thirsty guards on every entrance.
  - id: saffron_thirsty_guards
    where: "Saffron City — guards at all four city gates refuse passage"
    blocker: "guard 'is thirsty', won't let you through"
    unlock: "give him a drink (Fresh Water / Soda Pop / Lemonade)"
    how: >
      Buy a drink from the vending machines on the Celadon Dept. Store roof, then
      hand it to any Saffron gate guard. One drink opens the city. Unchanged from
      Gen 1 in FireRed.
    source: prior

  # 8 — Snorlax: sleeping roadblock, needs the Poké Flute. (later game)
  - id: snorlax_flute
    where: "Route 12 and Route 16 — a Snorlax sleeps across the road on each"
    blocker: "huge sleeping Pokémon fully blocks the route"
    unlock: "play the Poké Flute (from Mr. Fuji after Pokémon Tower, Lavender)"
    how: >
      Clear Pokémon Tower in Lavender, save Mr. Fuji → he gives the Poké Flute.
      Use it facing the Snorlax to wake it (it then battles; can be caught).
    source: prior

  # - id:
  #   where:
  #   blocker:
  #   unlock:
  #   how:
  #   source: prior
```

> Seeded through Cerulean/Vermilion plus the two most famous later walls
> (Saffron guards, Snorlax). A wrong/missing gate just means the agent treats
> that spot as a wall — same as today — so partial is fine. All eight gates are
> `prior`; FireRed's Kanto reuses the same map and event flow as Red for every
> one of them, so these transferred with only wording touch-ups.

---

## 3. Town services — where to heal and shop

Which maps have a Pokémon Center (free full heal) and a Poké Mart (buy items).
You can keep this coarse (town name); the agent learns the exact door. Note the
two **standalone route Centers** (Mt. Moon, Rock Tunnel) — Centers with no Mart.
FireRed keeps the same town layout as Red, so this list is unchanged.

```yaml
towns:
  - name: "Pallet Town"
    has_center: false       # Oak's lab full-heals; no Center/Mart building
    has_mart: false
    source: prior
  - name: "Viridian City"
    has_center: true
    has_mart: true
    source: prior
  - name: "Pewter City"
    has_center: true
    has_mart: true
    source: prior
  - name: "Route 4 (Mt. Moon Center)"
    has_center: true        # lone Center just outside Mt. Moon's east exit
    has_mart: false
    source: prior
  - name: "Cerulean City"
    has_center: true
    has_mart: true
    source: prior
  - name: "Vermilion City"
    has_center: true
    has_mart: true
    source: prior
  - name: "Lavender Town"
    has_center: true
    has_mart: true
    source: prior
  - name: "Celadon City"
    has_center: true
    has_mart: true          # also the multi-floor Dept. Store (best stock)
    source: prior
  - name: "Route 10 (Rock Tunnel Center)"
    has_center: true        # lone Center at the Rock Tunnel entrance
    has_mart: false
    source: prior
  - name: "Saffron City"
    has_center: true
    has_mart: true
    source: prior
  - name: "Fuchsia City"
    has_center: true
    has_mart: true
    source: prior
  - name: "Cinnabar Island"
    has_center: true
    has_mart: true
    source: prior

  # - name:
  #   has_center:
  #   has_mart:
  #   source: prior
```

---

## 4. Items — what they do and when they work

The agent will *learn* effects by using things, but seed the obvious early items
so it doesn't waste a battle finding out. `effect` is a category; `when` is the
usable context. The classic healing-item amounts below are the same numbers in
FireRed as they were in Red/Blue (Gen 3 did not change these); ball catch-rate
multipliers (Poké/Great/Ultra) are also unchanged.

- `effect`: `heal_hp` | `heal_status` | `revive` | `capture` | `repel` |
  `escape` | `key` | `boost` | `other`
- `when`: `battle` | `field` | `both`

```yaml
items:
  # --- HP healing (amounts match FireRed's in-game values) ---
  - name: "Potion"
    effect: heal_hp
    amount: 20
    when: both
    buy_priority: high
    source: prior
  - name: "Super Potion"
    effect: heal_hp
    amount: 50
    when: both
    buy_priority: high
    source: prior
  - name: "Hyper Potion"
    effect: heal_hp
    amount: 200          # 200 in FireRed, same as Gen 1 (later gens use 120)
    when: both
    buy_priority: high
    source: prior
  - name: "Max Potion"
    effect: heal_hp
    amount: full
    when: both
    buy_priority: high
    source: prior
  - name: "Full Restore"
    effect: heal_hp       # full HP AND clears status
    when: both
    buy_priority: high
    source: prior

  # --- status cures ---
  - name: "Antidote"
    effect: heal_status   # poison
    when: both
    buy_priority: medium
    source: prior
  - name: "Parlyz Heal"
    effect: heal_status   # paralysis
    when: both
    buy_priority: medium
    source: prior
  - name: "Awakening"
    effect: heal_status   # sleep
    when: both
    buy_priority: medium
    source: prior
  - name: "Burn Heal"
    effect: heal_status   # burn
    when: both
    buy_priority: low
    source: prior
  - name: "Ice Heal"
    effect: heal_status   # freeze
    when: both
    buy_priority: low
    source: prior
  - name: "Full Heal"
    effect: heal_status   # any status
    when: both
    buy_priority: medium
    source: prior

  # --- revives ---
  - name: "Revive"
    effect: revive        # restores a fainted mon to half HP
    when: both
    buy_priority: medium
    source: prior

  # --- capture ---
  - name: "Poké Ball"
    effect: capture
    when: battle          # wild only; fails vs trainer mons
    buy_priority: high
    source: prior
  - name: "Great Ball"
    effect: capture
    when: battle
    buy_priority: high
    source: prior
  - name: "Ultra Ball"
    effect: capture
    when: battle
    buy_priority: high
    source: prior
  - name: "Master Ball"
    effect: capture       # 100% catch; only one exists (Silph Co.) — save it
    when: battle
    buy_priority: never
    source: prior

  # --- field utility ---
  - name: "Repel"
    effect: repel
    when: field
    buy_priority: low
    source: prior
  - name: "Super Repel"
    effect: repel
    when: field
    buy_priority: low
    source: prior
  - name: "Escape Rope"
    effect: escape        # warp out of a cave to the last Center
    when: field
    buy_priority: medium
    source: prior

  # --- drinks: heal HP AND are the Saffron-guard key (see gate #7) ---
  - name: "Fresh Water"
    effect: heal_hp
    amount: 50
    when: both
    buy_priority: low     # buy for the Saffron guards, not for healing
    source: prior
  - name: "Soda Pop"
    effect: heal_hp
    amount: 60
    when: both
    buy_priority: low
    source: prior
  - name: "Lemonade"
    effect: heal_hp
    amount: 80
    when: both
    buy_priority: low
    source: prior

  # --- key / one-off ---
  - name: "Town Map"
    effect: key
    when: field
    source: prior
  - name: "Bicycle"
    effect: key           # fast overworld movement
    when: field
    source: prior
  - name: "Bike Voucher"
    effect: key           # redeem at the Cerulean Bike Shop for a free Bicycle
    when: field
    source: prior
  - name: "Poké Flute"
    effect: key           # wakes Snorlax (gate #8); also cures party sleep
    when: both
    source: prior
  - name: "S.S. Ticket"
    effect: key           # boards the S.S. Anne (gate #6)
    when: field
    source: prior
  - name: "Nugget"
    effect: other         # no use; sell for ₽5000
    when: field
    buy_priority: never
    source: prior
  - name: "Rare Candy"
    effect: boost         # +1 level instantly
    when: field
    buy_priority: never   # not sold; found
    source: prior

  # - name:
  #   effect:
  #   when:
  #   buy_priority:
  #   source: learn
```

---

## 5. Gym readiness — how strong before each badge

Rough "don't walk into this gym underleveled" targets. Vague is fine. I added
`weak_to` (offensive types that hit the leader's team hard) and `bring` so the
`grow`/`prepare` drives can pick *what* to train or catch, not just *how high*.
**Difficulty: easy** — each `recommended_level` sits a few levels above the
leader's ace so the agent walks in over-leveled (Sabrina, the traditional hard
gym, gets extra buffer). Treat it as a floor, not a ceiling. FireRed keeps the
same 8 Kanto leaders/badges in the same order as Red, but the ace levels are
FRLG's own (slightly different from the original Gen-1 numbers).

```yaml
gyms:
  - n: 1
    town: "Pewter City"
    leader: "Brock"
    type: "Rock"            # also part Ground on his team
    recommended_level: 16
    weak_to: [water, grass, fighting, ground]
    bring: "a Water or Grass mon trivializes this; otherwise level a strong
            physical attacker. Charmander-only starts are the hard case."
    source: prior
  - n: 2
    town: "Cerulean City"
    leader: "Misty"
    type: "Water"
    recommended_level: 24
    weak_to: [electric, grass]
    bring: "Pikachu/Grass coverage; watch her Starmie's high Special Attack."
    source: prior
  - n: 3
    town: "Vermilion City"
    leader: "Lt. Surge"
    type: "Electric"
    recommended_level: 28
    weak_to: [ground]
    bring: "any Ground type (Diglett/Dugtrio from Diglett's Cave nearby) is a
            hard counter — Electric can't touch it."
    source: prior
  - n: 4
    town: "Celadon City"
    leader: "Erika"
    type: "Grass"           # some Poison on her team
    recommended_level: 33
    weak_to: [fire, flying, psychic, ice, bug]
    bring: "Fire or Flying; Charizard/Pidgeotto shine here."
    source: prior
  - n: 5
    town: "Fuchsia City"
    leader: "Koga"
    type: "Poison"
    recommended_level: 42
    weak_to: [psychic, ground]
    bring: "Psychic coverage (Kadabra/Alakazam) still handles this well; Bug is
            NOT super effective vs Poison in Gen 3 (that was a Gen-1-only
            matchup — see §6a), so don't lean on Bug moves here."
    source: prior
  - n: 6
    town: "Saffron City"
    leader: "Sabrina"
    type: "Psychic"
    recommended_level: 47
    weak_to: [bug, ghost, dark]   # Gen 3 gives Psychic real weaknesses (§6a)
    bring: "Ghost coverage (Gastly line, available around Lavender Tower) is now
            a genuine counter — the Gen-1 'Ghost does nothing to Psychic' bug is
            fixed in Gen 3. Still worth over-levelling; Kanto's Dark-type
            options are thin before the Sevii Islands."
    source: prior
  - n: 7
    town: "Cinnabar Island"
    leader: "Blaine"
    type: "Fire"
    recommended_level: 50
    weak_to: [water, ground, rock]
    bring: "Water type ends this quickly."
    source: prior
  - n: 8
    town: "Viridian City"
    leader: "Giovanni"
    type: "Ground"
    recommended_level: 54
    weak_to: [water, grass, ice]
    bring: "Water/Grass/Ice coverage; his Ground/Rock/Poison team is slow."
    source: prior

  # - n:
  #   town:
  #   leader:
  #   type:
  #   recommended_level:
  #   weak_to:
  #   bring:
  #   source: prior
```

> The 8th gym (Giovanni, Viridian) is back where you started — the agent should
> not expect to clear it early; it unlocks only late, after Silph Co. The
> `weak_to`/`bring` fields are deliberately *offensive* advice (what beats the
> leader), which is what the prep/train decision needs — the BattleBrain already
> scores individual moves, so this is the strategic layer above it.

---

## 6. Secrets, exploits & glitches — how to make the game easier

Three tiers, ordered by risk. **6a/6b** are clean and feasible for the agent;
**6c** is powerful but risky and low-feasibility for autonomous play (gate it
behind an explicit opt-in — see the closing decision). This section changed the
most in the Gen-1 → Gen-3 port: several Red/Blue battle-engine bugs were fixed
in later generations (including FireRed), so the old "exploits" list doesn't
carry over as-is.

> **Integration:** `knowledge/type_chart.py` is currently still a **Gen-1**
> chart (its own docstring says so, and it hard-codes the Gen-1-only
> `(GHOST, PSYCHIC_T): 0.0` bug and the Gen-1-only Bug↔Poison mutual
> super-effectiveness). That module has not been ported to Gen 3 yet — that's a
> separate task from this doc — so the facts below are marked
> `modeled_by_scorer: false` wherever the current code still scores the old
> Gen-1 matchup instead of the correct Gen-3 one. Once type_chart.py is ported,
> flip those to `true`. `score_moves` is also still `power × type × STAB` only:
> it does not value accuracy, secondary effects, high-crit moves, or
> partial-trap lock, so §6a doubles as the move-scorer upgrade backlog.

### 6a. Battle-engine facts (Gen-1 vs Gen-3/FireRed quirks) — free, zero risk

```yaml
battle_exploits:
  - id: psychic_no_longer_untouchable
    fact: "The Gen-1 bug where Ghost does NOTHING to Psychic is FIXED in Gen 3:
            Ghost is now super effective vs Psychic, and Psychic also gained
            Dark as a second new weakness. Bug is no longer super effective vs
            Poison either (that was Gen-1 only) — it's not-very-effective now."
    use: "Alakazam/Kadabra are still strong, but no longer a near-unstoppable
           psychic sweeper; Ghost-type coverage (Gastly line near Lavender) is
           a real answer to Sabrina now (gym #6)."
    modeled_by_scorer: false   # type_chart.py still encodes the old Gen-1 chart
    source: prior
  - id: freeze_can_thaw
    fact: "Unlike Gen 1 (where freeze was permanent until a Fire hit), Gen 3
            gives a frozen Pokémon a chance to thaw naturally each turn."
    use: "Ice moves are still strong disables, but not a guaranteed permanent
           KO the way they were in Red — don't over-rely on a single freeze."
    modeled_by_scorer: false    # secondary effects not scored
    source: prior
  - id: blizzard_70_accuracy
    fact: "Blizzard is 70% accurate in Gen 3 (it was 90% in Gen 1)."
    use: "Less spammable than the Gen-1 roots assumed; pair with a more
           accurate STAB move rather than leaning on Blizzard alone."
    modeled_by_scorer: false    # accuracy ignored in the score
    source: prior
  - id: hyper_beam_always_recharges
    fact: "The Gen-1 quirk where Hyper Beam skipped its recharge turn on a KO
            is fixed from Gen 2 onward — in FireRed it always recharges."
    use: "Don't treat Hyper Beam as a free finisher; it costs a turn even after
           the kill, so time it for the last Pokémon in a fight."
    modeled_by_scorer: false
    source: prior
  - id: high_crit_moves_no_longer_speed_scaled
    fact: "Crit rate is no longer tied to base Speed (that was Gen 1 only);
            Gen 3 uses a fixed baseline crit chance with stages, and high-crit
            moves (Slash, Razor Leaf, Crabhammer, Karate Chop) raise the stage."
    use: "High-crit moves are still good, but a slow mon benefits from them
           about as much as a fast one now — the old Gen-1 speed logic is gone."
    modeled_by_scorer: false    # scorer uses flat power
    source: prior
  - id: partial_trap_lock
    fact: "Wrap / Fire Spin / Clamp / Bind (and Whirlpool, new in Gen 3) still
            stop the target acting while trapped and re-trap each turn for
            2-5 turns."
    use: "Low base power, huge control — the scorer undervalues them."
    modeled_by_scorer: false
    source: prior
  - id: status_control_shorter_sleep
    fact: "Sleep (Sleep Powder/Spore/Hypnosis/Sing/Lovely Kiss) and paralysis
            (Thunder Wave/Glare/Body Slam) still disable the foe, but Gen 3
            shortened sleep to roughly 1-3 turns (Gen 1 allowed up to 7)."
    use: "Status-first then attack still wins most fights, just don't expect a
           Gen-1-length sleep lock; follow up quickly."
    modeled_by_scorer: false    # status moves score 0
    source: prior
  - id: special_split_into_two_stats
    fact: "Special Attack and Special Defense were split into two separate
            stats starting Gen 2 (Gen 1 had one combined Special stat)."
    use: "A mon that looked balanced under the old combined Special (e.g.
           Jynx, Lapras) may now be lopsided between the two halves — check
           both before assuming it tanks special hits."
    modeled_by_scorer: false
    source: prior
  - id: accuracy_quirks_mostly_fixed
    fact: "The Gen-1 bug letting 100%-accuracy moves still miss 1/256 of the
            time is fixed. Focus Energy's Gen-1 bug (it QUARTERED crit rate
            instead of raising it) is also fixed — it now works as intended.
            Swift still never misses."
    use: "Focus Energy is safe to use again in Gen 3 (it wasn't in Gen 1).
           Swift remains reliable against evasion boosts."
    modeled_by_scorer: false
    source: prior
  - id: abilities_are_new
    fact: "Abilities are a brand-new Gen-3 mechanic with no Gen-1 equivalent
            (e.g. Static, Intimidate, Levitate) — every Pokémon has one."
    use: "Factor a mon's ability into matchups (a Levitate user shrugs off
           Ground moves entirely; Intimidate lowers the foe's Attack on
           switch-in). Not modeled at all yet."
    modeled_by_scorer: false
    source: prior
```

### 6b. Free / cheap power spikes (legit, high feasibility, no risk)

```yaml
power_spikes:
  - id: nidoking_early
    what: "Nidoran♂ (Routes 3/22) + a Moon Stone (Mt. Moon) → Nidoking."
    why: "Huge TM movepool (Earthquake/Blizzard/Thunderbolt); top in-game carry."
    source: prior
  - id: alakazam_line
    what: "Abra (Routes 24/25) → Kadabra @L16 → Alakazam (evolves on trade)."
    why: "Strong special attacker with wide TM coverage; no longer the
           near-unanswerable Gen-1 psychic sweeper (see §6a), but still one of
           the best in-game carries available this early."
    source: prior
  - id: traded_mon_exp
    what: "Traded Pokémon gain 1.5× EXP (level faster) — but obey only up to your
            badge cap, so a too-high traded mon can disobey."
    why: "Use in-game trades for fast levels within the obedience limit."
    source: prior
  - id: ingame_trades
    what: "Cerulean: Poliwhirl → Jynx ('Lola', Ice/Psychic, strong);
            Route 2 house: Abra → Mr. Mime; Vermilion: Spearow → Farfetch'd (weak)."
    why: "Free, often pre-leveled coverage Pokémon; same trades as the Gen-1
           original — FireRed kept them."
    source: prior
  - id: free_pokemon
    what: "Lapras (free from a Silph Co. employee, Saffron, after clearing Silph);
            Eevee (free, Celadon, a building near the Game Corner) → Vaporeon/Jolteon;
            Hitmonlee OR Hitmonchan (free pick, Saffron Fighting Dojo);
            a fossil (Dome/Helix/Old Amber) → Kabutops/Omastar/Aerodactyl (Cinnabar Lab)."
    why: "Elite party members at no catch cost. Lapras is a top Water/Ice."
    source: prior
  - id: game_corner_prizes
    what: "Celadon Game Corner coins → Dratini (→ Dragonite), Scyther/Pinsir, Abra, TMs."
    why: "Dratini is a strong long-term investment."
    source: prior
  - id: workhorse_tms
    what: "Body Slam (85 pwr, 30% paralysis, Normal STAB) is still a workhorse
            in FireRed; spread Blizzard / Thunderbolt / Surf / Earthquake
            across the team for coverage."
    why: "Body Slam on Tauros/Snorlax/Nidoking is a strong win condition."
    source: prior
  - id: late_sweepers
    what: "Tauros (Safari Zone, Fuchsia) with Body Slam/Hyper Beam/Earthquake/Blizzard;
            Snorlax (the two roadblocks are catchable)."
    why: "Tauros is a great in-game physical sweeper; Snorlax is a tank."
    source: prior
  - id: stock_up_balls
    what: "Buy lots of Poké/Great Balls before Mt. Moon and the Safari Zone
            (Safari uses bait/rock + a step limit — no normal balls or fighting)."
    why: "Avoids running dry at the only spots that gate good catches."
    source: prior
```

### 6c. Glitches (mostly patched in FireRed) — opt-in only, low value

```yaml
glitches:
  - id: gen1_dupe_and_mew_glitches_patched
    what: "The classic Gen-1 Red/Blue memory glitches this section used to list
            (the MissingNo. item-quantity duplication via the Viridian Old Man
            + Cinnabar coastal Surf, and the Trainer-Fly Mew glitch) rely on
            Gen-1-specific memory layout bugs. FireRed is a rebuilt GBA engine
            and does not reproduce them — they do not work in FireRed."
    use: "Do not expect these to work; treat §6c as informational only until a
           FireRed-specific glitch is verified and added here."
    risk: "n/a — not reproducible in this ROM"
    feasibility: not_applicable
    source: prior
  - id: walk_through_walls_gen1_only
    what: "Gen-1 'Glitch City' (bad Surf/escape sequences that corrupt map
            state) is also a Gen-1 engine bug; not confirmed to reproduce on
            FireRed's engine."
    use: "Do not rely on this for sequence-breaking in FireRed."
    risk: "unconfirmed — treat as unavailable rather than testing on a live run"
    feasibility: avoid
    source: prior
  - id: infinite_money_gen1_only
    what: "The old 'sell duplicated Nuggets/TMs' infinite-money trick depended
            entirely on the item-dupe glitch above, which does not work here."
    use: "No known FireRed equivalent yet; rely on trainer battles + selling
           genuinely-found items (Nuggets still sell for ₽5000 each)."
    risk: "n/a"
    feasibility: not_applicable
    source: prior
```

---

## What I'll build around this

- A **Needs/Goal arbiter** that reads these tables, scores the drives each step,
  and dispatches to executors: GameSense (navigate), BattleBrain (fight/catch),
  and new **heal** + **shop** menu drivers (same pattern as the catch menu).
- A **learned-knowledge store** in run memory: item effects confirmed by
  observation, discovered service locations, gates it figured out — so blanks
  here get filled in by playing, and persist across episodes.
- The agent's live "thought"/goal in the dashboard will show *which drive is
  winning and why* ("HP 18% → heading to the Viridian Center"), so you can watch
  it reason.

## Decisions locked in (from Kameron)

- **ROM = FireRed.** All priors are Gen-3 FireRed; the LeafGreen fork is
  identical in every way this doc cares about (same Kanto map/gates/gyms).
- **Pewter → Route 3 is a hard gate** (beat Brock to pass) — gate #2 is `prior`,
  unchanged from the Gen-1 confirmation (FireRed reuses the same event).
- **Difficulty = easy** — gym `recommended_level`s set a few levels above each
  leader's ace (FireRed's own ace levels, not Red's), with extra buffer on
  Sabrina, the traditional hard gym (though Gen 3 gave Psychic real weaknesses,
  see §6a).
- **Secrets/exploits/glitches added** as §6, re-audited for what actually
  carries over from Gen 1 to Gen 3/FireRed — most Gen-1 battle-engine bugs are
  fixed, and the Gen-1 memory-corruption glitches (§6c) do not reproduce on
  FireRed's engine at all.

## One open decision — glitch policy (§6c)

The §6a/§6b material is safe to wire in now. §6c is effectively **moot for
FireRed** as currently written: the Gen-1 duplication/Mew glitches it used to
document do not work on this ROM. Pick one:

- **(default) Document only** — keep §6c as reference/history; the agent never
  attempts any of it, and no FireRed-specific glitch has been verified to add.
- **Research a FireRed-specific glitch** — if a genuine low-risk Gen-3 glitch
  is later confirmed (e.g. a Ruby/Sapphire/Emerald-family bug that also exists
  in FireRed), add it here as its own `source: prior` row before wiring it in.
- **Full sequence-break research** — actively look for FireRed-specific
  sequence breaks (not recommended for autonomous streaming without a verified,
  low-risk target).

Say which and I'll wire the arbiter to consume this file accordingly.
