from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from elevenlabs.client import AsyncElevenLabs

from .config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, TTS_SAMPLE_RATE

logger = logging.getLogger(__name__)


class TTSClient:
    def __init__(self):
        self._client = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)
        self.on_audio_chunk: Callable[[bytes], Awaitable[None]] | None = None
        self._current_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """No persistent connection needed – the SDK handles it per-call."""
        logger.info("TTS client ready (using ElevenLabs SDK)")

    async def speak(self, text: str) -> None:
        """Stream text-to-speech audio. Spawns a background task so it doesn't block."""
        # Cancel any previous stream still running
        await self._cancel_current()
        self._current_task = asyncio.create_task(self._stream(text))

    async def speak_and_wait(self, text: str) -> None:
        """Stream TTS and wait until all audio has been played."""
        await self._cancel_current()
        self._current_task = asyncio.create_task(self._stream(text))
        try:
            await self._current_task
        except asyncio.CancelledError:
            # The parent task was cancelled, but _current_task is independently
            # scheduled via create_task — we must explicitly cancel it too,
            # otherwise it keeps streaming audio in the background.
            await self._cancel_current()
            raise  # propagate so the caller knows speech was interrupted

    async def _stream(self, text: str) -> None:
        """Internal: call the SDK streaming endpoint and forward chunks."""
        logger.info("TTS speaking: %s", text[:80])
        try:
            response = self._client.text_to_speech.stream(
                voice_id=ELEVENLABS_VOICE_ID,
                text=text,
                model_id="eleven_flash_v2_5",
                output_format=f"pcm_{TTS_SAMPLE_RATE}",
            )
            async for chunk in response:
                if chunk and self.on_audio_chunk:
                    await self.on_audio_chunk(chunk)
        except asyncio.CancelledError:
            logger.info("TTS stream cancelled (interrupted)")
            raise
        except Exception:
            logger.exception("TTS stream error")

    async def interrupt(self) -> None:
        """Stop current speech by cancelling the streaming task."""
        await self._cancel_current()
        logger.info("TTS interrupted")

    async def _cancel_current(self) -> None:
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
            self._current_task = None

    async def close(self) -> None:
        await self._cancel_current()
        logger.info("TTS client closed")
