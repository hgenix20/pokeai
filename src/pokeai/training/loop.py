"""Episodic training/evaluation loop."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pokeai.agents import build_agent
from pokeai.config import Config
from pokeai.env.pokemon_red_env import PokemonRedEnv
from pokeai.evaluation.aggregate import aggregate
from pokeai.evaluation.logger import RunLogger
from pokeai.evaluation.metrics import RunMetrics, TerminationReason
from pokeai.utils.hashing import hash_config


@runtime_checkable
class StepMonitor(Protocol):
    """Hook interface for run observation and manual control (fail-safe).

    The dashboard implements this; tests can supply a stub. All hooks are
    called from the training loop's thread.
    """

    def attach(self, env: PokemonRedEnv, agent: Any = None) -> None:
        """Called once after the env is built, before the first episode."""

    def on_episode_start(self, episode: int, total_episodes: int) -> None:
        ...

    def pump(self, last_action: int | None, info: dict[str, Any]) -> None:
        """Called before each step. May block while paused. Must return
        promptly once running/stepping/stopped."""

    def on_episode_end(self, metrics: RunMetrics) -> None:
        ...

    @property
    def stop_requested(self) -> bool:
        ...

    def consume_restart_request(self) -> bool:
        """True exactly once when the user asked to restart the current episode."""
        ...

    def close(self) -> None:
        ...


def _generate_run_id() -> str:
    return f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def _termination_reason(
    terminated: bool, truncated: bool, badges: int, blackout: bool, manual: bool = False
) -> TerminationReason:
    if manual:
        return TerminationReason.MANUAL
    if terminated and badges >= 8:
        return TerminationReason.ALL_BADGES
    if terminated and blackout:
        return TerminationReason.BLACKOUT
    if truncated:
        return TerminationReason.MAX_STEPS
    # Fallback - shouldn't happen if env logic is consistent
    return TerminationReason.MANUAL


def _build_monitor(config: Config) -> "StepMonitor | None":
    """Build the dashboard monitor if the UI is enabled. Lazy import so
    headless runs never touch pygame."""
    if not config.ui.enabled:
        return None
    from pokeai.ui.dashboard import Dashboard

    return Dashboard(config.ui)


def run(config: Config, emulator=None, monitor: StepMonitor | None = None) -> Path:
    """Run config.logging.episodes episodes. Returns the run directory.

    `emulator` is an optional EmulatorWrapper-compatible object for testing or
    alternate backends. If None, a real PyBoy-backed emulator is built.

    `monitor` is an optional StepMonitor (e.g. the diagnostic dashboard). If
    None and config.ui.enabled, a Dashboard is created automatically.

    The run can always be stopped early:
      - via the monitor (STOP button / Esc in the dashboard), or
      - via Ctrl+C (KeyboardInterrupt).
    Both paths finalize logs and write the aggregate report for completed work.
    """
    config_dict = config.model_dump(mode="json")
    config_hash = hash_config(config_dict)
    run_id = config.logging.run_id or _generate_run_id()

    run_dir = Path(config.logging.output_dir) / run_id
    logger = RunLogger(run_dir)
    logger.write_run_metadata(
        run_id=run_id,
        agent_name=config.agent.type,
        config_snapshot=config_dict,
        config_hash=config_hash,
    )

    agent = build_agent(config)
    env = PokemonRedEnv(config, emulator=emulator)
    agent.attach_env(env)
    if monitor is None:
        monitor = _build_monitor(config)
    if monitor is not None:
        monitor.attach(env, agent)

    def write_episode(ep: int, ep_start: float, info: dict, *,
                      terminated: bool, truncated: bool, manual: bool) -> RunMetrics:
        metrics = RunMetrics(
            run_id=run_id,
            agent_name=agent.name,
            config_hash=config_hash,
            episode_index=ep,
            steps_taken=info["step_count"],
            badges_earned=info["badge_count"],
            events_triggered=info["events_set"],
            unique_maps_visited=info["unique_maps_visited"],
            total_party_level=info["party_total_level"],
            blackout_occurred=info["blackout_occurred"],
            terminated_reason=_termination_reason(
                terminated,
                truncated,
                info["badge_count"],
                info["blackout_occurred"],
                manual=manual,
            ),
            cumulative_reward=info["cumulative_reward"],
            wall_clock_seconds=time.time() - ep_start,
            # Skills-profile metrics
            unique_tiles_visited=info.get("unique_tiles_visited", 0),
            repeat_action_rate=info.get("repeat_action_rate", 0.0),
            total_steps_stuck=info.get("total_steps_stuck", 0),
            curiosity_reward_total=info.get("curiosity_reward_total", 0.0),
            recovered_from_low_hp=info.get("recovered_from_low_hp", False),
            battles_won=info.get("battles_won", 0),
            # Learner internals (None for non-RL agents)
            agent_epsilon=getattr(agent, "epsilon", None),
            agent_loss=getattr(agent, "mean_episode_loss", None),
        )
        logger.write_episode(metrics)
        print(
            f"[ep {ep+1}/{config.logging.episodes}] "
            f"reward={metrics.cumulative_reward:.2f} "
            f"badges={metrics.badges_earned} "
            f"maps={metrics.unique_maps_visited} "
            f"steps={metrics.steps_taken} "
            f"reason={metrics.terminated_reason.value}"
        )
        return metrics

    interrupted = False
    try:
        ep = 0
        full_reset_every = config.environment.full_reset_every
        title_reset_every = config.environment.title_reset_every
        title_state = config.emulator.title_state_path
        while ep < config.logging.episodes:
            ep_start = time.time()
            # Periodic complete reset: every N episodes, wipe the accumulated
            # run-level curiosity map so a long run can't settle into a rut.
            if full_reset_every and ep > 0 and ep % full_reset_every == 0:
                env.full_reset()
                agent.full_reset()  # also wipe the agent's run-scoped memory (world map)
                print(f"[ep {ep+1}/{config.logging.episodes}] full reset — curiosity memory cleared")
            # Periodic title-screen start: every N episodes, begin from the very
            # beginning so the agent plays the intro itself.
            reset_options = None
            if title_state and title_reset_every and ep > 0 and ep % title_reset_every == 0:
                reset_options = {"state_path": title_state}
                env.full_reset()  # fresh mind for a fresh game
                agent.full_reset()  # forget the remembered world too — new playthrough
                print(f"[ep {ep+1}/{config.logging.episodes}] starting from the TITLE SCREEN")
            obs, info = env.reset(options=reset_options)
            agent.reset()
            if monitor is not None:
                monitor.on_episode_start(ep, config.logging.episodes)
            terminated = False
            truncated = False
            manual_stop = False
            restarted = False
            last_action: int | None = None

            while not (terminated or truncated):
                if monitor is not None:
                    # Blocks while paused; returns on run/step/stop/restart.
                    monitor.pump(last_action, info)
                    if monitor.stop_requested:
                        manual_stop = True
                        break
                    if monitor.consume_restart_request():
                        restarted = True
                        break
                # The monitor may override action selection (manual takeover or a
                # live-switched strategy in the dashboard). Monitors that don't
                # implement select_action fall back to the configured agent.
                select = getattr(monitor, "select_action", None) if monitor is not None else None
                action = select(obs, agent) if select is not None else agent.act(obs)
                next_obs, reward, terminated, truncated, info = env.step(action)
                # Learning hook: scripted agents ignore this
                agent.observe(obs, action, reward, next_obs, terminated)
                obs = next_obs
                last_action = action

            if restarted:
                # Discard this episode and run the same episode index again
                print(
                    f"[ep {ep+1}/{config.logging.episodes}] "
                    "restarted by user — episode discarded"
                )
                continue

            # Only log episodes that ran at least one step
            if info["step_count"] > 0 or not manual_stop:
                metrics = write_episode(
                    ep, ep_start, info,
                    terminated=terminated, truncated=truncated, manual=manual_stop,
                )
                if monitor is not None:
                    monitor.on_episode_end(metrics)
                # Learning hook: checkpointing, schedule updates
                agent.end_episode(ep, run_dir)

            if manual_stop:
                print("Run stopped manually. Finalizing logs...")
                break

            ep += 1
    except KeyboardInterrupt:
        # Fail-safe: Ctrl+C ends the run gracefully instead of losing the log.
        interrupted = True
        print("\nInterrupted (Ctrl+C). Finalizing logs...")
    finally:
        env.close()
        logger.finalize()
        if monitor is not None:
            monitor.close()

    # Produce aggregate report for whatever episodes completed
    try:
        aggregate(run_dir)
    except (FileNotFoundError, ValueError):
        # No episodes written (e.g., stopped before the first step); skip report
        pass

    if interrupted:
        print(f"Partial results in: {run_dir}")

    return run_dir
