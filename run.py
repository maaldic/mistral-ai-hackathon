#!/usr/bin/env python3
"""
YANKI CLI — Voice-controlled web browser via Playwright.

Captures mic audio directly with PyAudio, streams to ElevenLabs STT,
runs Mistral LLM agent loop, and plays TTS through speakers.

Usage:
    python run.py

Logs are written to logs/session_YYYYMMDD_HHMMSS.log
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------
# Logging setup — BEFORE any backend imports so all modules inherit it
# ------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILENAME = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
LOG_FILEPATH = LOG_DIR / LOG_FILENAME

# File handler — DEBUG (everything)
file_handler = logging.FileHandler(LOG_FILEPATH, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

# Console handler — INFO (readable)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Configure root logger
logging.root.setLevel(logging.DEBUG)
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logging.root.addHandler(file_handler)
logging.root.addHandler(console_handler)

# Silence noisy libs
logging.getLogger("websockets.client").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("yanki.cli")

# ------------------------------------------------------------------
# Now import backend (logging is already configured)
# ------------------------------------------------------------------
from backend.cli_session import CLISession  # noqa: E402


async def main():
    logger.info("Log file: %s", LOG_FILEPATH)
    print(f"  📝 Log file: {LOG_FILEPATH}\n")

    session = CLISession()

    try:
        await session.start()

        # Run the mic capture loop (blocks until cancelled)
        await session.run_mic_loop()

    except KeyboardInterrupt:
        print("\n\n  ⏹  Shutting down...")
        logger.info("KeyboardInterrupt — shutting down")
    except Exception:
        logger.exception("Fatal error")
    finally:
        await session.shutdown()
        print(f"\n  📝 Session log saved to: {LOG_FILEPATH}")
        print("  👋 Goodbye!\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
