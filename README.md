# pokeai — a long-horizon autonomous agent that plays Pokémon FireRed

`pokeai` is a symbolic, long-horizon decision-making agent that plays **Pokémon FireRed end-to-end through the BizHawk emulator with no game API** — it perceives the game the way a human does (from live memory-mapped state), plans, navigates, battles, catches, and drives the storyline, all as one continuous agent loop. It is built as much as an **instrumented, reproducible evaluation environment** as it is an agent: every capability is checked against ground-truth game state and covered by an automated test suite.

> Status: **actively developed (work in progress).** The agent plays multi-hour, unattended stretches and completes large sections of the game; full-playthrough coverage is an ongoing roadmap (see `docs/ROADMAP.md` and `docs/FIXLIST.md`). This repo is published as an engineering portfolio piece; a demo clip will be added.

## What makes it interesting

- **No game API.** Perception is deterministic, read live from emulator RAM (party, position, battle state, menu cursors, bag, story flags) — a real grounding/perception problem, not a scripted bot.
- **Long-horizon, sparse-reward decision making.** Hierarchical planning and navigation (`walk_to` / warp handling), battle and capture strategy, and a **fact-gated storyline dispatcher** that resumes correct play from any save state and sustains hours of unattended progression.
- **Pluggable strategies.** Random, heuristic, and deliberative "brain" strategies are swappable and operator/viewer-selectable (see `configs/`).
- **Built to be measured.** Ground-truth verifiers on real game state, save-state checkpointing for reproducible runs, and a **large automated test suite (~765 tests across the full project)** exercising perception, planning, battle logic, pathing, and the story dispatcher.
- **Observable.** An operator/viewer web dashboard streams live state and allows strategy switching during a run.

## Architecture

The design docs are the best entry point:
- `docs/ARCHITECTURE.md` — full system manual (perception → cognition → action loop).
- `docs/CORE_GAMEPLAY.md` — the "born knowing the mechanics, learns the content" design.
- `docs/FIRERED_REDESIGN.md` — the FireRed walker/warp and storyline-dispatcher redesign.
- `docs/AGENT_ROOTS.md`, `docs/ROADMAP.md`, `docs/FIXLIST.md` — agent taxonomy, roadmap, and the live fix backlog.

## Repository layout

```
src/pokeai/     agent core: perception, planning/navigation, battle & capture, story dispatcher, CLI, UI
scripts/        runnable entry points (route/battle/story runs, streaming)
tests/          ~agent test suite (perception, planning, battle, pathing, story)
configs/        agent-strategy configs (random / heuristic / deliberative / dashboard)
bizhawk/        ai_bridge.lua — the emulator-side bridge
docs/           architecture, core-gameplay design, roadmap, walkthrough knowledge
```

## Getting started

Requires Python 3.12+ and the **BizHawk** emulator. You must supply your **own legally-obtained Pokémon ROM** — no ROM is included in this repository.

```bash
python -m pip install -e .
python -m pytest        # run the test suite
python scripts/firered_bizhawk.py   # run the agent against BizHawk (configure your ROM path)
```

## Not included (intentionally)

- **ROMs** (`roms/`) — copyrighted; supply your own.
- **Save states / captures** and the local `.venv` (kept out of version control).
- The **Twitch streaming bot** and its secrets — out of scope for this portfolio repo.

## License

MIT — see `LICENSE`. © Kameron M. Green.
