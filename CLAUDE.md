# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Real-time bidirectional voice agent ("Echo") that browses the web via voice commands. Uses Mistral Large for reasoning/tool-calling, ElevenLabs for STT/TTS, and Playwright for browser automation.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
python3 -m playwright install chromium

# Run (primary mode — CLI with local mic/speaker)
python3 run.py

# Run (alternative — WebSocket backend + React frontend, frontend is WIP)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev  # port 3000, proxies /ws to :8000
```

There are no automated tests or linting configured.

## Environment

- Python 3.9.6 — use `python3` (not `python`)
- All Python files must use `from __future__ import annotations` for modern type hints
- Requires `.env` with `ELEVENLABS_API_KEY`, `MISTRAL_API_KEY` (optional: `ELEVENLABS_VOICE_ID`)

## Architecture

Two operational modes share the same core modules:

**CLI mode** (`run.py` → `backend/cli_session.py`): PyAudio captures mic → STT → LLM tool loop → browser actions + TTS → PyAudio speaker output. This is the primary working mode.

**WebSocket mode** (`backend/main.py` → `backend/session.py`): FastAPI WebSocket replaces PyAudio for audio I/O. React frontend at `frontend/`. Currently a WIP placeholder.

From now on only update CLI MODE unless I say otherwise.

### Core modules

- `backend/cli_session.py` / `backend/session.py` — Session orchestrators (CLI and WebSocket respectively). Contain the agentic tool loop (`_run_tool_loop`).
- `backend/llm_client.py` — Mistral `chat.complete` wrapper with message history management and rollback-on-interrupt logic.
- `backend/browser_agent.py` — Playwright browser controller + DOM extraction via `dom_extractor.js` injection.
- `backend/tools.py` — Mistral tool definitions (JSON schemas for all tools).
- `backend/stt_client.py` — ElevenLabs Scribe real-time STT WebSocket wrapper.
- `backend/tts_client.py` — ElevenLabs streaming TTS client (PCM 24kHz).
- `backend/config.py` — All constants and env var loading.

### Key design patterns

**DOM element addressing**: `dom_extractor.js` is injected into pages, assigns sequential `data-agent-id` attributes to visible interactive elements, and returns a text list like `[42] "Search" (text input)`. The LLM uses these numeric IDs in tool calls. IDs are re-assigned on every page evaluation.

**Tool loop rules**: Only ONE browser action per LLM turn (extras get a "Skipped" result). `answer_to_user` can co-occur with a browser action (run concurrently via `asyncio.gather`). `answer_to_user` alone = final answer = loop exits. Max 10 iterations.

**Interruption**: User speech cancels the current tool loop task, immediately stops TTS, and `LLMClient.rollback_after_interrupt()` removes incomplete tool call/result pairs from history to keep Mistral API happy.

**Async pattern**: All I/O is async. Mistral SDK is synchronous, so calls go through `asyncio.to_thread()`.

**Conversation truncation**: History is capped at 30 messages with cleanup to never leave orphaned tool/assistant+tool_calls messages at the head.
