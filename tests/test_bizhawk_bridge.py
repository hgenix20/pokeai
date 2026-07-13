"""Protocol-level tests for BizHawkBridge — no BizHawk required.

A fake in-process peer plays the role of ai_bridge.lua: it CONNECTS to the
bridge's socket server and answers the same newline text protocol (R/M/I/T/P)
out of a scripted memory dict, recording the inputs it is sent. This pins the
exact wire contract the Lua script implements, so the drop-in swap onto the
bridge is verified on Windows without launching EmuHawk.
"""
from __future__ import annotations

import socket
import threading
import time

from pokeai.emulator.bizhawk_bridge import _ADDR_X, _ADDR_Y, BizHawkBridge

_DIRS = {"Up", "Down", "Left", "Right"}  # BizHawk casing (post-normalization)


class FakeBizHawk(threading.Thread):
    """Mimics ai_bridge.lua: connect, serve scripted memory, record inputs."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.mem: dict[int, int] = {}
        self.held: str | None = None
        self.taps: list[str] = []

    # memory writers (little-endian)
    def wbytes(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def w16(self, addr: int, v: int):
        self.wbytes(addr, (v & 0xFFFF).to_bytes(2, "little"))

    def w32(self, addr: int, v: int):
        self.wbytes(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def _read_val(self, addr: int, size: int) -> int:
        return int.from_bytes(bytes(self.mem.get(addr + i, 0) for i in range(size)), "little")

    def _handle(self, line: str) -> str:
        op = line[:1]
        if op == "R":
            toks = line.split()[1:]
            out = [str(self._read_val(int(toks[i]), int(toks[i + 1])))
                   for i in range(0, len(toks) - 1, 2)]
            return " ".join(out)
        if op == "M":
            _, addr, ln = line.split()
            addr, ln = int(addr), int(ln)
            return "".join("%02x" % self.mem.get(addr + k, 0) for k in range(ln))
        if op == "I":
            self.held = line[1:].strip()
            if self.held in _DIRS:  # simulate one tile of movement
                self.w16(_ADDR_Y, self._read_val(_ADDR_Y, 2) + 1)
            return "ok"
        if op == "T":
            self.taps.append(line[1:].strip())
            return "ok"
        if op == "P":
            return "pong"
        return "err"

    def run(self):
        s = socket.create_connection(("127.0.0.1", self.port))
        buf = b""
        try:
            while True:
                chunk = s.recv(8192)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    s.sendall((self._handle(line.decode().strip()) + "\n").encode())
        except OSError:
            pass
        finally:
            s.close()


def _connect() -> tuple[BizHawkBridge, FakeBizHawk]:
    bridge = BizHawkBridge(port=0, timeout=5.0)          # port 0 -> ephemeral
    port = bridge._srv.getsockname()[1]
    peer = FakeBizHawk(port)
    # seed some scripted memory + a player position
    peer.mem[0x100] = 0xAB
    peer.w16(0x200, 0xBEEF)
    peer.w32(0x300, 0xDEADBEEF)
    peer.wbytes(0x400, bytes([1, 2, 3, 4, 5]))
    peer.w16(_ADDR_X, 10)
    peer.w16(_ADDR_Y, 20)
    peer.start()
    bridge.wait_for_bizhawk()
    return bridge, peer


def test_reads_and_ping():
    bridge, peer = _connect()
    try:
        assert bridge.ping() is True
        assert bridge.read_byte(0x100) == 0xAB
        assert bridge.read_u16(0x200) == 0xBEEF
        assert bridge.read_u32(0x300) == 0xDEADBEEF
        assert bridge.read_range(0x400, 0x405) == [1, 2, 3, 4, 5]
        assert bridge.read_many([(0x100, 1), (0x200, 2), (0x300, 4)]) == [0xAB, 0xBEEF, 0xDEADBEEF]
    finally:
        bridge.close()


def test_button_name_normalization():
    """The brain's UPPERCASE names must reach BizHawk in its own casing."""
    bridge, peer = _connect()
    try:
        bridge.press_button("UP")     # -> tap "Up 4"
        bridge.press_button("START")  # -> tap "Start 4"
        time.sleep(0.05)
        assert peer.taps[0].startswith("Up ")
        assert peer.taps[1].startswith("Start ")
    finally:
        bridge.close()


def test_press_direction_settle_detects_movement():
    bridge, peer = _connect()
    try:
        # "UP" normalizes to "Up", which the peer treats as a one-tile step.
        assert bridge.press_direction_settle("UP", max_frames=48) is True
        # after settle the bridge released the dpad
        assert peer.held == ""
        # raw object-coord y advanced by one
        assert bridge.player_xy() == (10, 21)
    finally:
        bridge.close()


def test_tick_waits_real_time():
    bridge, peer = _connect()
    try:
        t0 = time.time()
        bridge.tick(12)   # ~12/59.7 ≈ 0.20s
        assert time.time() - t0 >= 0.1
    finally:
        bridge.close()
