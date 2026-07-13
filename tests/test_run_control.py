"""Tests for the run-control fail-safe: state machine, manual stop through the
training loop, and the per-Pokemon party reader used by the dashboard HUD.

No pygame window is opened — the dashboard's logic core (RunControl) and the
loop's StepMonitor protocol are exercised with stubs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pokeai.config import Config
from pokeai.env.pokemon_red_env import PokemonRedEnv
from pokeai.training.loop import run as run_training
from pokeai.ui.run_control import RunControl, RunState

from tests.mock_emulator import MockEmulator, encode_state


# --- RunControl state machine ---


def test_starts_running_by_default():
    control = RunControl()
    assert control.running
    assert not control.paused
    assert not control.stop_requested


def test_start_paused():
    control = RunControl(start_paused=True)
    assert control.paused
    assert not control.running


def test_pause_resume_toggle():
    control = RunControl()
    control.pause()
    assert control.paused
    control.toggle_pause()
    assert control.running
    control.toggle_pause()
    assert control.paused


def test_stop_is_terminal():
    control = RunControl()
    control.stop()
    assert control.stop_requested
    # start/pause after stop must not revive the run
    control.start()
    assert control.stop_requested
    assert control.state == RunState.STOPPED
    control.pause()
    assert control.state == RunState.STOPPED


def test_step_request_only_while_paused():
    control = RunControl()
    # Running: step requests are ignored
    control.request_step()
    assert not control.consume_step_request()
    # Paused: step request is honored exactly once
    control.pause()
    control.request_step()
    assert control.consume_step_request()
    assert not control.consume_step_request()


def test_stop_clears_pending_step():
    control = RunControl(start_paused=True)
    control.request_step()
    control.stop()
    assert not control.consume_step_request()


def test_restart_request_consumed_once():
    control = RunControl()
    control.request_restart()
    assert control.restart_requested
    assert control.consume_restart_request()
    assert not control.consume_restart_request()
    assert not control.restart_requested


def test_stop_clears_pending_restart():
    control = RunControl()
    control.request_restart()
    control.stop()
    assert not control.consume_restart_request()


def test_restart_ignored_after_stop():
    control = RunControl()
    control.stop()
    control.request_restart()
    assert not control.consume_restart_request()


# --- Manual stop through the training loop (StepMonitor protocol) ---


class StubMonitor:
    """StepMonitor that requests a stop after a fixed number of steps, and can
    optionally request one restart at a given pump count."""

    def __init__(self, stop_after_steps: int, restart_at_pump: int | None = None):
        self.stop_after_steps = stop_after_steps
        self.restart_at_pump = restart_at_pump
        self.pump_count = 0
        self.attached_env = None
        self.attached_agent = None
        self.episodes_started: list[int] = []
        self.episodes_ended: list[Any] = []
        self.closed = False

    def attach(self, env, agent=None) -> None:
        self.attached_env = env
        self.attached_agent = agent

    def on_episode_start(self, episode: int, total_episodes: int) -> None:
        self.episodes_started.append(episode)

    def pump(self, last_action, info) -> None:
        self.pump_count += 1

    def on_episode_end(self, metrics) -> None:
        self.episodes_ended.append(metrics)

    @property
    def stop_requested(self) -> bool:
        return self.pump_count > self.stop_after_steps

    def consume_restart_request(self) -> bool:
        if self.restart_at_pump is not None and self.pump_count == self.restart_at_pump:
            self.restart_at_pump = None  # only once
            return True
        return False

    def close(self) -> None:
        self.closed = True


def _make_config(tmp_path: Path, episodes: int = 5, max_steps: int = 10) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rom = tmp_path / "rom.gb"
    rom.write_bytes(b"\x00")
    state = tmp_path / "init.gb_state"
    state.write_bytes(b"\x00")
    return Config.model_validate(
        {
            "emulator": {
                "rom_path": str(rom),
                "init_state_path": str(state),
                "render": False,
                "sound": False,
                "emulation_speed": 0,
            },
            "environment": {"max_steps": max_steps, "frame_skip": 1, "observation_mode": "ram"},
            "agent": {"type": "random", "seed": 1},
            "logging": {
                "run_id": "test_manual_stop",
                "output_dir": str(tmp_path / "runs"),
                "episodes": episodes,
            },
        }
    )


def _steady_snapshots() -> list[dict[int, int]]:
    """Snapshots that never terminate (no blackout, no badges) so only
    max_steps or a manual stop can end an episode."""
    return [
        encode_state(current_map=0, party_levels=[5], party_hp=[20], party_max_hp=[20]),
        encode_state(current_map=0, party_levels=[5], party_hp=[20], party_max_hp=[20]),
    ]


def test_manual_stop_ends_run_gracefully(tmp_path):
    config = _make_config(tmp_path, episodes=5, max_steps=10)
    monitor = StubMonitor(stop_after_steps=3)
    emu = MockEmulator(_steady_snapshots())

    run_dir = run_training(config, emulator=emu, monitor=monitor)

    # Monitor lifecycle honored
    assert monitor.attached_env is not None
    assert monitor.closed
    assert monitor.episodes_started == [0]  # stopped during the first episode

    # Partial episode written with MANUAL termination
    lines = (run_dir / "episodes.jsonl").read_text().splitlines()
    lines = [ln for ln in lines if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["terminated_reason"] == "MANUAL"
    assert 0 < rec["steps_taken"] < config.environment.max_steps

    # run.json finalized (fail-safe wrote everything before exiting)
    meta = json.loads((run_dir / "run.json").read_text())
    assert "ended_at" in meta

    # Aggregate report still produced for the partial run
    assert (run_dir / "eval_report.json").exists()

    # Emulator was closed
    assert emu.closed


def test_restart_discards_episode_and_reruns(tmp_path):
    """RESTART: current episode is discarded (not logged) and rerun fresh."""
    config = _make_config(tmp_path, episodes=2, max_steps=5)
    # Restart on the 3rd pump (mid-episode 0); never stop
    monitor = StubMonitor(stop_after_steps=10_000, restart_at_pump=3)
    emu = MockEmulator(_steady_snapshots())

    run_dir = run_training(config, emulator=emu, monitor=monitor)

    # Episode 0 was started twice (original + restarted), then episode 1 once
    assert monitor.episodes_started == [0, 0, 1]

    # Exactly 2 episodes logged — the discarded attempt is not in the log
    lines = [ln for ln in (run_dir / "episodes.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    records = [json.loads(ln) for ln in lines]
    assert [r["episode_index"] for r in records] == [0, 1]
    for rec in records:
        assert rec["terminated_reason"] == "MAX_STEPS"
        assert rec["steps_taken"] == config.environment.max_steps


class SelectMonitor(StubMonitor):
    """Monitor that overrides action selection (manual takeover / live strategy).

    Returns a fixed action from select_action so we can assert the loop honors
    the override instead of calling agent.act().
    """

    def __init__(self, forced_action: int, stop_after_steps: int):
        super().__init__(stop_after_steps=stop_after_steps)
        self.forced_action = forced_action
        self.select_calls = 0

    def select_action(self, obs, agent) -> int:
        self.select_calls += 1
        return self.forced_action


def test_select_action_override_is_used(tmp_path):
    """A monitor's select_action replaces the agent's chosen action each step."""
    from pokeai.env.action_controller import ACTION_TO_BUTTON, Action

    config = _make_config(tmp_path, episodes=1, max_steps=4)
    monitor = SelectMonitor(forced_action=int(Action.UP), stop_after_steps=10_000)
    emu = MockEmulator(_steady_snapshots())

    run_training(config, emulator=emu, monitor=monitor)

    # Every executed step pressed the overridden button, not a random one.
    assert monitor.select_calls >= 1
    pressed = [b for b in emu.button_log if b != "NOOP"]
    assert pressed, "expected at least one button press"
    assert set(emu.button_log) == {ACTION_TO_BUTTON[int(Action.UP)]}


def test_run_without_monitor_unchanged(tmp_path):
    """No monitor + UI disabled: loop behaves exactly as before."""
    config = _make_config(tmp_path, episodes=2, max_steps=5)
    emu = MockEmulator(_steady_snapshots())
    run_dir = run_training(config, emulator=emu)

    lines = (run_dir / "episodes.jsonl").read_text().splitlines()
    lines = [ln for ln in lines if ln.strip()]
    assert len(lines) == 2
    for line in lines:
        assert json.loads(line)["terminated_reason"] == "MAX_STEPS"


# --- Party detail reader (dashboard HUD data) ---


def test_read_party_details(tmp_path):
    config = _make_config(tmp_path)
    snap = encode_state(
        party_count=2,
        party_hp=[18, 30],
        party_max_hp=[19, 35],
        party_levels=[5, 8],
        party_species=[0xB0, 0x99],          # Charmander, Bulbasaur
        party_types=[(0x14, 0x14), (0x16, 0x03)],  # Fire/Fire, Grass/Poison
        party_dvs=[(0xAB, 0xCD), (0x12, 0x34)],
    )
    emu = MockEmulator([snap])
    env = PokemonRedEnv(config, emulator=emu)
    party = env.state_reader.read_party_details()

    assert len(party) == 2

    charmander = party[0]
    assert charmander.species_id == 0xB0
    assert charmander.level == 5
    assert charmander.hp == 18
    assert charmander.max_hp == 19
    assert charmander.type1 == 0x14
    # DV byte 1 = 0xAB -> attack 0xA, defense 0xB; byte 2 = 0xCD -> speed 0xC, special 0xD
    assert charmander.dv_attack == 0xA
    assert charmander.dv_defense == 0xB
    assert charmander.dv_speed == 0xC
    assert charmander.dv_special == 0xD
    # HP DV from LSBs: atk(0) def(1) spd(0) spc(1) -> 0b0101
    assert charmander.dv_hp == 0b0101

    bulbasaur = party[1]
    assert bulbasaur.species_id == 0x99
    assert bulbasaur.type1 == 0x16
    assert bulbasaur.type2 == 0x03
    env.close()


def test_game_data_lookups():
    from pokeai.knowledge.game_data import map_name, species_name, status_text, type_name

    assert species_name(0xB0) == "Charmander"
    assert species_name(0x99) == "Bulbasaur"
    assert species_name(0xFF) == "#FF"  # unknown -> hex fallback
    assert type_name(0x14) == "Fire"
    assert map_name(0x00) == "Pallet Town"
    assert map_name(0x28) == "Oak's Lab"
    assert status_text(0) == "OK"
    assert status_text(0b0000_1000) == "PSN"
    assert status_text(0b0100_0000) == "PAR"
