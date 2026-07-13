"""BizHawk emulator backend for the pokeai brain.

BizHawk (EmuHawk) runs FireRed natively (smooth video + audio, and the surface
CrowdControl plugs into). This bridge is the Python end of a tiny socket link to
`bizhawk/ai_bridge.lua` (loaded in BizHawk): Python requests RAM reads and button
inputs; BizHawk serves them. It exposes the SAME read/input surface the rest of
pokeai already uses (read_byte/read_u16/read_u32/read_range + presses), so the
verified state reader, vision, pathing, navigator, and planner work unchanged.

Unlike the tick-based mGBA wrapper, BizHawk free-runs at real time, so inputs are
reactive: hold a direction and poll position, rather than tick frame-by-frame.
"""
from __future__ import annotations

import socket
import time

# GBA refresh rate. BizHawk free-runs at this; we use it to translate the mGBA
# path's frame counts into real-time waits.
GBA_FPS = 59.7275

# FireRed (BPRE) live player coords (gObjectEvents[0]); same addresses the mGBA
# path verified — they're ROM-specific, not emulator-specific.
_ADDR_X = 0x02036E48
_ADDR_Y = 0x02036E4A

# The rest of pokeai (Navigator, StoryAgent, NavigateTo, the env) speaks the
# canonical UPPERCASE button names the mGBA wrapper used ("UP", "START", ...).
# BizHawk's joypad.set wants its own casing ("Up", "Start", ...), so normalize
# here — this is what makes the brain a true drop-in onto the bridge.
_BIZHAWK_BUTTONS = {
    "A": "A", "B": "B",
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "START": "Start", "SELECT": "Select", "L": "L", "R": "R",
}


def _bh(button: str) -> str:
    """Canonical button name -> BizHawk joypad name (pass-through if unknown)."""
    return _BIZHAWK_BUTTONS.get(button.upper(), button)


class BizHawkBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 51055, timeout: float = 60.0):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(1)
        self._srv.settimeout(timeout)
        self.conn: socket.socket | None = None
        self._rx = b""

    # --- connection ---

    def wait_for_bizhawk(self) -> None:
        """Block until ai_bridge.lua connects (it retries every ~1s)."""
        self.conn, _ = self._srv.accept()
        self.conn.settimeout(5.0)

    @property
    def connected(self) -> bool:
        return self.conn is not None

    def reaccept(self) -> None:
        """Drop the current connection and wait for a fresh one (e.g. ai_bridge.lua
        was reloaded or toggled off/on). Blocks until a new connection arrives."""
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.conn = None
        self._rx = b""
        self.conn, _ = self._srv.accept()
        self.conn.settimeout(5.0)

    # --- low-level request/response (newline-delimited text) ---

    def _request(self, line: str, _retries: int = 2) -> str:
        """Send one command, return its reply line. Resilient to a transient
        socket abort (WinError 10053/10054, seen when EmuHawk is still warming up
        or the OS blips): ai_bridge.lua auto-reconnects (~1s), so on a dropped
        link we reaccept a fresh connection and re-send. The request is
        idempotent for reads; writes (I/T/S/K/L) re-applying once is harmless."""
        for attempt in range(_retries + 1):
            try:
                if self.conn is None:
                    raise ConnectionError("BizHawk not connected")
                self.conn.sendall((line + "\n").encode())
                while b"\n" not in self._rx:
                    chunk = self.conn.recv(8192)
                    if not chunk:
                        raise ConnectionError("BizHawk closed")
                    self._rx += chunk
                out, _, self._rx = self._rx.partition(b"\n")
                return out.decode().strip()
            except (ConnectionError, OSError) as e:
                if attempt >= _retries:
                    raise
                # drop the half-open link and wait for the Lua to reconnect
                try:
                    self.reaccept()
                except OSError:
                    raise e

    # --- memory reads (the EmulatorWrapper surface) ---

    def read_many(self, pairs: list[tuple[int, int]]) -> list[int]:
        req = "R " + " ".join(f"{a} {s}" for a, s in pairs)
        reply = self._request(req)
        return [int(v) for v in reply.split()] if reply else []

    def read_byte(self, addr: int) -> int:
        return self.read_many([(addr, 1)])[0]

    def read_u16(self, addr: int) -> int:
        return self.read_many([(addr, 2)])[0]

    def read_u32(self, addr: int) -> int:
        return self.read_many([(addr, 4)])[0]

    def read_range(self, start: int, end: int) -> list[int]:
        reply = self._request(f"M {start} {end - start}")
        return list(bytes.fromhex(reply))

    # --- input (reactive) ---

    def set_held(self, buttons: list[str]) -> None:
        self._request("I " + ",".join(_bh(b) for b in buttons))

    def release(self) -> None:
        self._request("I ")

    def tap(self, button: str, frames: int = 8) -> None:
        self._request(f"T {_bh(button)} {frames}")

    def tick(self, frames: int = 1) -> None:
        """Let ~`frames` of real time elapse. BizHawk free-runs (the Lua loop
        frameadvances on its own), so there is no frame to step here: callers
        ported from the tick-based mGBA path (Navigator's warp wait, Explorer's
        idle) just need real time to pass while the game advances on its own.
        This is what keeps Navigator/Explorer a drop-in onto the bridge."""
        time.sleep(frames / GBA_FPS)

    # Accepts the canonical pokeai names ("A","B","UP","DOWN","LEFT","RIGHT",
    # "START","SELECT","L","R","NOOP"); set_held/tap normalize to BizHawk casing.
    def press_button(self, button: str) -> None:
        if button != "NOOP":
            self.tap(button, 4)

    def press_button_pulse(self, button: str, frames: int = 16, hold: int = 8) -> None:
        if button == "NOOP":
            time.sleep(frames / GBA_FPS)
            return
        self.tap(button, min(hold, frames))
        time.sleep(frames / GBA_FPS)

    def press_button_held(self, button: str, frames: int = 16) -> None:
        if button == "NOOP":
            time.sleep(frames / GBA_FPS)
            return
        self.tap(button, frames)
        time.sleep(frames / GBA_FPS)

    def player_xy(self) -> tuple[int, int]:
        v = self.read_many([(_ADDR_X, 2), (_ADDR_Y, 2)])
        return v[0], v[1]

    def press_direction_settle(self, button: str, max_frames: int = 48, settle: int = 8) -> bool:
        """Hold a direction until the player advances one tile (reactive), then
        release. Returns True if it moved."""
        start = self.player_xy()
        self.set_held([button])
        deadline = time.time() + max_frames / GBA_FPS
        moved = False
        while time.time() < deadline:
            if self.player_xy() != start:
                moved = True
                break
            time.sleep(0.01)
        self.release()
        time.sleep(settle / GBA_FPS)
        return moved

    def screenshot(self, path: str, wait: float = 1.0) -> str:
        """Have BizHawk save a PNG of the current frame to `path` (so the AI can
        actually SEE the screen — BizHawk is the only display). Creates the parent
        dir, blocks until the file appears (up to `wait` s), returns the path."""
        import os

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        before = os.path.getmtime(path) if os.path.exists(path) else -1
        self._request(f"S {path}")
        deadline = time.time() + wait
        while time.time() < deadline:
            if os.path.exists(path) and os.path.getmtime(path) != before:
                break
            time.sleep(0.02)
        return path

    def reboot(self) -> bool:
        """Power-cycle the core back to the title screen (lua op 'B',
        client.reboot_core). FIXLIST FL-1: 'New Game' must never run the
        intro script against a loaded save."""
        return self._request("B") == "ok"

    def save_state(self, path: str) -> bool:
        """Save the game state to a file (BizHawk savestate.save)."""
        return self._request(f"K {path}") == "ok"

    def load_state(self, path: str) -> bool:
        """Load the game state from a file (BizHawk savestate.load).

        HYDRATE FIRST: our save slots live in OneDrive, which dehydrates them to
        Files-On-Demand placeholders (ReparsePoint) over time. BizHawk's
        savestate.load then silently fails on the cold placeholder (returns, but
        the game doesn't change; player_xy stays (0,0)). Reading the bytes here
        forces Windows to materialize the file before we ask BizHawk to load it.
        """
        try:
            with open(path, "rb") as fh:
                fh.read()
        except OSError:
            pass
        return self._request(f"L {path}") == "ok"

    def ping(self) -> bool:
        return self._request("P") == "pong"

    def close(self) -> None:
        try:
            if self.conn:
                self.conn.close()
        finally:
            self._srv.close()
