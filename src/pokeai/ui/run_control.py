"""Run control state machine — the manual fail-safe.

Pure logic, no UI dependency. The training loop polls this each step;
the dashboard (or any other frontend) mutates it from user input.

States:
    RUNNING  -> steps execute continuously
    PAUSED   -> loop blocks (UI keeps pumping); single steps may be requested
    STOPPED  -> loop exits gracefully, logs are finalized
"""
from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class RunControl:
    """Start/pause/step/stop control shared between the loop and the UI."""

    def __init__(self, start_paused: bool = False):
        self.state = RunState.PAUSED if start_paused else RunState.RUNNING
        self._step_requested = False
        self._restart_requested = False

    # --- Commands (called by the UI / signal handlers) ---

    def start(self) -> None:
        """Start or resume continuous execution."""
        if self.state != RunState.STOPPED:
            self.state = RunState.RUNNING

    def pause(self) -> None:
        if self.state == RunState.RUNNING:
            self.state = RunState.PAUSED

    def toggle_pause(self) -> None:
        if self.state == RunState.RUNNING:
            self.pause()
        elif self.state == RunState.PAUSED:
            self.start()

    def request_step(self) -> None:
        """Queue a single env step while paused."""
        if self.state == RunState.PAUSED:
            self._step_requested = True

    def request_restart(self) -> None:
        """Discard the current episode and start it over from the init state."""
        if self.state != RunState.STOPPED:
            self._restart_requested = True

    def stop(self) -> None:
        """Request a graceful stop. Irreversible for this run."""
        self.state = RunState.STOPPED
        self._step_requested = False
        self._restart_requested = False

    # --- Queries (called by the training loop) ---

    @property
    def stop_requested(self) -> bool:
        return self.state == RunState.STOPPED

    @property
    def paused(self) -> bool:
        return self.state == RunState.PAUSED

    @property
    def running(self) -> bool:
        return self.state == RunState.RUNNING

    def consume_step_request(self) -> bool:
        """True exactly once per requested single-step (clears the request)."""
        if self._step_requested:
            self._step_requested = False
            return True
        return False

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    def consume_restart_request(self) -> bool:
        """True exactly once per requested restart (clears the request)."""
        if self._restart_requested:
            self._restart_requested = False
            return True
        return False
