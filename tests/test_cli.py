"""CLI regression tests (torch-free)."""
from __future__ import annotations

import io
import sys

from pokeai.cli import _force_utf8_io


def test_force_utf8_io_survives_cp1252_stdout(monkeypatch):
    """Regression: watch mode crashed with UnicodeEncodeError because Windows
    redirected stdout uses cp1252, which can't encode the ε in DQN log lines.
    After _force_utf8_io, printing epsilon must not raise."""
    cp1252_out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    cp1252_err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", cp1252_out)
    monkeypatch.setattr(sys, "stderr", cp1252_err)

    # Before the fix this raises UnicodeEncodeError; sanity-check that premise.
    import pytest

    with pytest.raises(UnicodeEncodeError):
        cp1252_out.write("epsilon ε")
        cp1252_out.flush()

    _force_utf8_io()

    assert sys.stdout.encoding.lower() == "utf-8"
    assert sys.stderr.encoding.lower() == "utf-8"
    # The real failing line shape — must not raise now.
    print("[dqn] resumed from latest.pt: step 10, episode 5, ε=0.250")
    sys.stdout.flush()


def test_force_utf8_io_is_noop_without_reconfigure(monkeypatch):
    """Streams lacking .reconfigure (e.g. a plain buffer) are tolerated."""
    monkeypatch.setattr(sys, "stdout", io.BytesIO())
    monkeypatch.setattr(sys, "stderr", io.BytesIO())
    _force_utf8_io()  # must not raise
