"""Tests for the roots-driven Needs/Goal arbiter: loading the roots, scoring
drives into a decision, the inter-map router, and the Adventurer reasoning about
what to do (heal vs train vs explore)."""
from __future__ import annotations

from pokeai.agents import build_agent
from pokeai.agents.brain.gamesense import GameSense
from pokeai.agents.brain.needs import Decision, NeedsArbiter
from pokeai.agents.brain.world_model import Cell
from pokeai.agents.brain_agents import AdventurerAgent
from pokeai.config import Config
from pokeai.emulator.state_reader import ITEM_POTION, ITEM_SUPER_POTION, StateReader
from pokeai.env.action_controller import Action
from pokeai.env.pokemon_red_env import PokemonRedEnv
from pokeai.knowledge.roots import Roots, load_roots, parse_roots
from tests.mock_emulator import MockEmulator, encode_state

_INLINE_ROOTS = """
# heading
```yaml
drives:
  survive:
    priority: 100
    trigger: party_hp_fraction < 0.35
    critical: party_hp_fraction < 0.15
    resolves_to: heal
  explore:
    priority: 10
    trigger: always
    resolves_to: explore
```
text
```yaml
towns:
  - name: "Viridian City"
    has_center: true
    has_mart: true
gyms:
  - n: 1
    town: "Pewter City"
    leader: "Brock"
    recommended_level: 16
items:
  - name: "Potion"
    effect: heal_hp
```
"""


# --- roots loading ---


def test_parse_roots_inline():
    r = parse_roots(_INLINE_ROOTS)
    assert [d.name for d in r.drives] == ["survive", "explore"]   # sorted by priority
    assert r.drives[0].resolves_to == "heal"
    assert r.item_effect("potion") == "heal_hp"
    assert r.next_gym(0).leader == "Brock"
    assert r.center_town_names() == ["Viridian City"]


def test_real_roots_file_loads():
    r = load_roots()
    assert len(r.drives) >= 4
    assert r.next_gym(0) is not None            # there's a first gym
    assert "Viridian City" in r.center_town_names()


# --- arbiter scoring ---


def _arbiter():
    return NeedsArbiter(parse_roots(_INLINE_ROOTS))


def test_arbiter_picks_survive_when_hurt():
    d = _arbiter().decide({"party_hp_fraction": 0.2, "always": True})
    assert d.drive == "survive" and d.goal == "heal"
    assert "heal" in d.rationale.lower()
    assert d.critical is False                   # 0.2 is not below the 0.15 critical line


def test_arbiter_flags_critical_when_very_low():
    d = _arbiter().decide({"party_hp_fraction": 0.1, "always": True})
    assert d.drive == "survive" and d.critical is True


def test_arbiter_defaults_to_explore_when_healthy():
    d = _arbiter().decide({"party_hp_fraction": 1.0, "always": True})
    assert d.goal == "explore"


def test_arbiter_empty_roots_still_decides():
    d = NeedsArbiter(Roots()).decide({"always": True})
    assert d.goal == "explore"


# --- inter-map router ---


def test_route_toward_map_chains_across_warps():
    gs = GameSense()
    # map 0 --warp(5,5)--> map 1 --warp(3,3)--> map 2
    gs._warp_dest = {(0, 5, 5): 1, (1, 3, 3): 2}
    gs.world.mark_floor(0, 5, 4)
    gs.world.mark_warp(0, 5, 4, Action.DOWN)   # door at (5,5)
    # From map 0, the first hop toward distant map 2 is the door to map 1.
    assert gs.route_toward_map(0, 5, 4, 2) == Action.DOWN
    assert gs.route_toward_map(0, 5, 4, 0) is None      # already there
    assert gs.route_toward_map(0, 5, 4, 99) is None     # no known route


# --- heal-item reading ---


def test_best_heal_item_prefers_cheapest():
    reader = StateReader(MockEmulator([encode_state(
        bag_items=[(ITEM_SUPER_POTION, 2), (ITEM_POTION, 5)])]))
    assert reader.best_heal_item() == (ITEM_POTION, 1)
    assert reader.count_heal_items() == 7


def test_best_heal_item_none_when_no_heals():
    reader = StateReader(MockEmulator([encode_state(bag_items=[(0x99, 1)])]))
    assert reader.best_heal_item() is None
    assert reader.count_heal_items() == 0


# --- Adventurer reasoning ---


def _config(tmp_path) -> Config:
    rom = tmp_path / "rom.gb"
    state = tmp_path / "init.state"
    rom.write_bytes(b"\x00")
    state.write_bytes(b"\x00")
    return Config.model_validate({
        "emulator": {"rom_path": str(rom), "init_state_path": str(state)},
        "environment": {"max_steps": 50, "observation_mode": "ram+tiles"},
        "agent": {"type": "adventurer", "seed": 7},
        "logging": {"episodes": 1, "output_dir": str(tmp_path / "runs")},
    })


def _adventurer(tmp_path, snap):
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = PokemonRedEnv(config, emulator=MockEmulator([snap] * 4, collision_grid=open_grid))
    agent = AdventurerAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    return agent, obs


def test_factory_builds_adventurer(tmp_path):
    agent = build_agent(_config(tmp_path))
    assert agent.name == "adventurer"
    assert "Decision-making" in agent.capabilities


def test_adventurer_decides_to_heal_when_hurt(tmp_path):
    # Lead at 3/20 HP -> survive drive -> heal goal, and it won't chase wild mons.
    agent, obs = _adventurer(tmp_path, encode_state(
        party_count=1, party_hp=[3], party_max_hp=[20], party_levels=[5], current_map=0))
    action = agent.act(obs)
    assert agent._decision.goal == "heal"
    assert agent.auto_catch is False
    assert "heal" in agent.goal_text.lower() or "center" in agent.goal_text.lower()
    assert isinstance(action, int)              # still produces a valid move, never crashes


def test_adventurer_trains_when_underlevelled(tmp_path):
    # Healthy but Lv5 with the first gym wanting ~Lv16 -> grow -> train/catch on.
    agent, obs = _adventurer(tmp_path, encode_state(
        party_count=1, party_hp=[20], party_max_hp=[20], party_levels=[5], current_map=0))
    agent.act(obs)
    assert agent._decision.goal == "train_or_catch"
    assert agent.auto_catch is True
    assert "train" in agent.goal_text.lower()


def test_adventurer_flips_to_unblock_when_stalled(tmp_path):
    # Healthy and not under-levelled, but nothing changes for a long stretch ->
    # it stops idling and switches to working out the gate.
    agent, obs = _adventurer(tmp_path, encode_state(
        party_count=1, party_hp=[20], party_max_hp=[20], party_levels=[16], current_map=0))
    for _ in range(agent.STALL_LIMIT + 3):
        agent.act(obs)
    assert agent._decision.goal == "unblock_gate"


def test_unblock_travels_to_a_map_with_someone_unmet(tmp_path):
    # Nobody left to talk to here, but another known map has an unmet NPC -> the
    # unblock executor routes toward that map (this is what runs fetch-errands).
    agent, obs = _adventurer(tmp_path, encode_state(
        party_count=1, party_hp=[20], party_max_hp=[20], party_levels=[16],
        current_map=0, x_pos=5, y_pos=4))
    gs = agent.sense
    gs._visited_maps = {0, 1}
    gs._warp_dest = {(0, 5, 5): 1}
    gs.world.mark_floor(0, 5, 4)
    gs.world.mark_warp(0, 5, 4, Action.DOWN)   # door at (5,5) -> map 1
    gs.world._set(1, 3, 3, Cell.NPC)            # someone to talk to on map 1
    agent._decision = Decision("progress", "unblock_gate", "stuck")

    state = agent.env.state_reader.read()
    sem = agent.env.screen_reader.semantic_tiles()
    assert agent._go_unblock(state, sem) == int(Action.DOWN)  # heads for the door to map 1


def test_adventurer_stands_still_while_strategist_thinks(tmp_path):
    import threading

    from pokeai.knowledge.llm_advisor import LLMAdvisor

    agent, obs = _adventurer(tmp_path, encode_state(
        party_count=1, party_hp=[20], party_max_hp=[20], party_levels=[16], current_map=0))
    release = threading.Event()
    agent.advisor = LLMAdvisor(call_fn=lambda m: (release.wait(2), '{"goal": "explore"}')[1])
    agent.advisor.request("stuck", [])
    assert agent.advisor.pending
    # While thinking, it stands still and flags the dashboard animation.
    assert agent.act(obs) == int(Action.NOOP)
    assert agent.thinking is True
    release.set()
    agent.advisor._thread.join(timeout=2)


def test_adventurer_follows_strategist_destination(tmp_path):
    from pokeai.knowledge.llm_advisor import LLMAdvisor

    agent, obs = _adventurer(tmp_path, encode_state(
        party_count=1, party_hp=[20], party_max_hp=[20], party_levels=[16],
        current_map=0, x_pos=5, y_pos=4))
    gs = agent.sense
    gs._warp_dest = {(0, 5, 5): 1}          # a door on map 0 leads to map 1 (Viridian City)
    gs.world.mark_floor(0, 5, 4)
    gs.world.mark_warp(0, 5, 4, Action.DOWN)
    # The strategist says go to Viridian City (map id 1); the agent adopts it.
    agent.advisor = LLMAdvisor(
        call_fn=lambda m: '{"goal": "go_to", "target": "Viridian City", "reason": "the parcel"}')
    agent.advisor.request("stuck", ["Viridian City"])
    agent.advisor._thread.join(timeout=2)
    agent._consume_advice()
    assert agent._llm_target == 1

    state = agent.env.state_reader.read()
    sem = agent.env.screen_reader.semantic_tiles()
    assert agent._go_unblock(state, sem) == int(Action.DOWN)  # routes toward that map


def test_gamesense_unmet_npc_maps_and_forget():
    gs = GameSense()
    gs.world._set(0, 5, 5, Cell.NPC)
    gs.world._set(1, 3, 3, Cell.NPC)
    assert set(gs.maps_with_unmet_npcs()) == {0, 1}
    gs.mark_interacted(0, 5, 5)
    assert gs.maps_with_unmet_npcs() == [1]
    gs.forget_interactions()
    assert set(gs.maps_with_unmet_npcs()) == {0, 1}
