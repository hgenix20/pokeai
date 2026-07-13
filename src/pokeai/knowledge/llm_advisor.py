"""LLM advisor — an occasional 'strategist' the agent consults when it's stuck.

A reasoning LLM can't run every step at real time (a call takes seconds), so it
sits *above* the symbolic agent: when the agent stalls at a gate, it sends a short
situation summary + the list of places it could go, and the model replies with a
concrete next sub-goal (e.g. "go_to: Viridian Mart"). The arbiter then executes
it. The call runs on a background thread so the game keeps rendering a "thinking"
animation, and we track call durations to estimate how long thinking will take.

Security: the API token is read from the HF_TOKEN environment variable at
runtime — never stored in the repo. If it's unset, the advisor is simply disabled
and the agent falls back to its own judgement.

Network/HTTP is isolated in `_http_call` (injectable) so the logic is testable
without a network or a token.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from collections.abc import Callable

# Hugging Face's OpenAI-compatible router (chat completions).
HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
# A large reasoning-capable instruct model; override with the HF_MODEL env var.
DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
# Until we've timed a real call, assume a big model takes roughly this long.
DEFAULT_ESTIMATE_S = 12.0
# Abandon a call that runs longer than this (the agent resumes on its own).
REQUEST_TIMEOUT_S = 40.0
# Where advisor activity is logged (JSON lines) so it can be reviewed/tailed.
LOG_PATH = os.environ.get("ADVISOR_LOG", "runs/advisor.jsonl")


def _log(**fields) -> None:
    """Best-effort append of one advisor event to the log file."""
    try:
        import os as _os

        _os.makedirs(_os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"), **fields}) + "\n")
    except Exception:
        pass

_SYSTEM_PROMPT = (
    "You are an expert Pokémon Red player advising a bot that is STUCK and can't "
    "find the way forward. Think about what unblocks progress (often an errand: "
    "talk to a specific person, fetch/deliver an item, beat a gym), then reply "
    "with ONLY a single JSON object and nothing else:\n"
    '{"goal": "go_to" | "heal" | "shop" | "explore", '
    '"target": "<one of the listed places, or empty>", '
    '"reason": "<one short sentence>"}'
)


def _strip_think(text: str) -> str:
    """Reasoning models emit <think>…</think> scratchpads — drop them."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)


class LLMAdvisor:
    """Background, best-effort strategist. Disabled (no-op) without HF_TOKEN."""

    def __init__(
        self,
        model: str | None = None,
        call_fn: Callable[[list[dict]], str] | None = None,
        token_env: str = "HF_TOKEN",
        timeout: float = REQUEST_TIMEOUT_S,
    ):
        self.model = model or os.environ.get("HF_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self._token = os.environ.get(token_env)
        self._injected = call_fn is not None        # a fake call (tests) counts as available
        self._call_fn = call_fn or self._http_call  # injectable for tests
        self._thread: threading.Thread | None = None
        self._pending = False
        self._result: dict | None = None
        self._error: str | None = None
        self._started = 0.0
        self._last_elapsed = 0.0
        self._durations: list[float] = []
        self._error_logged = False

    # --- status (read by the agent + dashboard) ---

    @property
    def available(self) -> bool:
        """True if a token is present (or a fake call_fn was injected for tests)."""
        return bool(self._token) or self._injected

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started if self._pending else self._last_elapsed

    @property
    def estimate(self) -> float:
        """Best guess at how long the current/next call takes (rolling average)."""
        if self._durations:
            return sum(self._durations) / len(self._durations)
        return DEFAULT_ESTIMATE_S

    @property
    def progress(self) -> float:
        """0..1 fraction of the estimated thinking time elapsed (for a bar)."""
        est = self.estimate or DEFAULT_ESTIMATE_S
        return max(0.0, min(self.elapsed / est, 1.0)) if self._pending else 0.0

    # --- ask / collect ---

    def request(self, summary: str, options: list[str]) -> bool:
        """Kick off a background call. Returns False if unavailable or already busy."""
        if not self.available or self._pending:
            return False
        self._pending = True
        self._result = None
        self._error = None
        self._started = time.monotonic()
        _log(event="request", summary=summary, options=options)
        self._thread = threading.Thread(
            target=self._run, args=(summary, list(options)), daemon=True
        )
        self._thread.start()
        return True

    def take_result(self) -> dict | None:
        """Return a finished suggestion once (then clear it). None while pending
        or if there's nothing new."""
        if self._pending or self._result is None:
            return None
        out, self._result = self._result, None
        return out

    def expired(self) -> bool:
        """True if a pending call has overrun its timeout (agent should move on)."""
        return self._pending and (time.monotonic() - self._started) > self.timeout

    # --- internals ---

    def _run(self, summary: str, options: list[str]) -> None:
        try:
            text = self._call_fn(self._build_messages(summary, options))
            self._result = self._parse(text)
            _log(event="result", suggestion=self._result,
                 elapsed=round(time.monotonic() - self._started, 1))
        except Exception as exc:  # network, auth, parse — all non-fatal
            self._error = str(exc)
            self._result = None
            _log(event="error", error=f"{type(exc).__name__}: {exc}", model=self.model)
            if not self._error_logged:  # surface the first failure for debugging
                self._error_logged = True
                print(f"[advisor] LLM call failed ({type(exc).__name__}): {exc} "
                      f"— falling back to built-in judgement. "
                      f"(model={self.model}; set HF_MODEL to change it)")
        finally:
            elapsed = time.monotonic() - self._started
            self._last_elapsed = elapsed
            self._durations.append(elapsed)
            self._durations = self._durations[-10:]  # rolling window
            self._pending = False

    def _build_messages(self, summary: str, options: list[str]) -> list[dict]:
        opts = ", ".join(options) if options else "(none known yet)"
        user = f"Situation:\n{summary}\n\nPlaces I can go: {opts}\n\nWhat should I do next?"
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _parse(text: str) -> dict | None:
        match = re.search(r"\{.*\}", _strip_think(text), flags=re.DOTALL)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return {
            "goal": str(obj.get("goal", "")).strip(),
            "target": str(obj.get("target", "")).strip(),
            "reason": str(obj.get("reason", "")).strip(),
        }

    def _http_call(self, messages: list[dict]) -> str:
        """POST to the HF router (OpenAI-compatible). NOT exercised in tests."""
        if not self._token:
            raise RuntimeError("HF_TOKEN not set")
        body = json.dumps(
            {"model": self.model, "messages": messages, "max_tokens": 400, "temperature": 0.4}
        ).encode("utf-8")
        req = urllib.request.Request(
            HF_ROUTER_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (fixed HTTPS host)
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
