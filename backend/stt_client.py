from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from elevenlabs.client import AsyncElevenLabs
from elevenlabs.realtime.scribe import AudioFormat, CommitStrategy, RealtimeAudioOptions
from elevenlabs.realtime.connection import RealtimeEvents

from .config import ELEVENLABS_API_KEY, PCM_SAMPLE_RATE

import wave
import base64
import os

logger = logging.getLogger(__name__)


class STTClient:
    def __init__(self):
        self._client = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)
        self._connection = None
        self.on_partial: Callable[[str, str], Awaitable[None]] | None = None
        self.on_committed: Callable[[str, str], Awaitable[None]] | None = None

    async def connect(self) -> None:
        options: RealtimeAudioOptions = {
            "model_id": "scribe_v2_realtime",
            "audio_format": AudioFormat.PCM_16000,
            "sample_rate": PCM_SAMPLE_RATE,
            "commit_strategy": CommitStrategy.VAD,
            "vad_silence_threshold_secs": 1.0,
            "vad_threshold": 0.65,
            "diarize": True,
            # Note: Hardcoded to English right now, can be parameterized if needed.
            "language_code": "en",
        }

        self._connection = await self._client.speech_to_text.realtime.connect(options)

        # Register event handlers (SDK callbacks are sync, so we schedule the
        # async session callbacks via asyncio.create_task).
        self._connection.on(RealtimeEvents.SESSION_STARTED, self._on_session_started)
        self._connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, self._on_partial)
        self._connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, self._on_committed)
        self._connection.on(RealtimeEvents.ERROR, self._on_error)
        self._connection.on(RealtimeEvents.CLOSE, self._on_close)

        logger.info("STT WebSocket connected (via SDK)")

    # ---- event handlers (sync, called by SDK) ----

    def _on_session_started(self, data):
        logger.info("STT session started: %s", data)

    def _on_partial(self, data):
        text = data.get("text", "").strip()
        # Filter ghost transcripts: short noise, audio event tags, and TTS echo
        if len(text) < 3 or text.startswith("(") and text.endswith(")") or text.lower() in ("thank you.", "thank you"):
            text = ""
        speaker = data.get("speaker", "unknown")
        if text and self.on_partial:
            asyncio.create_task(self.on_partial(text, speaker))

    def _on_committed(self, data):
        text = data.get("text", "").strip()
        speaker = data.get("speaker", "unknown")
        if text and self.on_committed:
            asyncio.create_task(self.on_committed(text, speaker))

    def _on_error(self, data):
        logger.error("STT error: %s", data)

    def _on_close(self):
        logger.info("STT WebSocket connection closed")

    # ---- public API ----

    async def send_audio(self, pcm_base64: str) -> None:
        if self._connection is None:
            return

        try:
            await self._connection.send({"audio_base_64": pcm_base64})
        except Exception as e:
            logger.error("STT: failed to send audio chunk: %s", e)

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
        logger.info("STT client closed")
