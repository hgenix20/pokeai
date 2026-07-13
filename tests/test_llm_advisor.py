"""Tests for the LLM advisor — threading, timing/estimate, prompt + parse, and
safe fallback — all with a fake model call (no network, no token)."""
from __future__ import annotations

import threading

from pokeai.knowledge.llm_advisor import DEFAULT_ESTIMATE_S, LLMAdvisor


def _advisor(response: str) -> LLMAdvisor:
    return LLMAdvisor(call_fn=lambda messages: response)


def test_disabled_without_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    a = LLMAdvisor()  # no injected call_fn and no token -> off
    assert a.available is False
    assert a.request("stuck", ["Viridian City"]) is False


def test_returns_parsed_suggestion_once():
    a = _advisor('{"goal": "go_to", "target": "Viridian Mart", "reason": "get the parcel"}')
    assert a.available is True
    assert a.request("stuck", ["Viridian Mart"]) is True
    a._thread.join(timeout=2)
    assert a.take_result() == {
        "goal": "go_to", "target": "Viridian Mart", "reason": "get the parcel",
    }
    assert a.take_result() is None  # consumed exactly once


def test_strips_reasoning_scratchpad():
    a = _advisor('<think>let me think...</think> {"goal": "heal", "target": "", "reason": "hurt"}')
    a.request("s", [])
    a._thread.join(timeout=2)
    assert a.take_result()["goal"] == "heal"


def test_bad_json_is_safe():
    a = _advisor("sorry, I cannot help")
    a.request("s", [])
    a._thread.join(timeout=2)
    assert a.take_result() is None  # no crash, no suggestion


def test_estimate_starts_default_then_tracks_calls():
    a = _advisor('{"goal": "explore"}')
    assert a.estimate == DEFAULT_ESTIMATE_S      # nothing measured yet
    a.request("s", [])
    a._thread.join(timeout=2)
    a.take_result()
    assert a.pending is False
    assert a.estimate >= 0.0                       # now reflects the measured call
    assert a.elapsed >= 0.0


def test_pending_blocks_a_second_request():
    release = threading.Event()
    a = LLMAdvisor(call_fn=lambda m: (release.wait(2), '{"goal": "explore"}')[1])
    assert a.request("s", []) is True
    assert a.pending is True
    assert a.request("s", []) is False            # busy -> refused
    release.set()
    a._thread.join(timeout=2)
