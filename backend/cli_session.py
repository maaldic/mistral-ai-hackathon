"""
CLI Session Manager — runs the full STT → LLM → Browser → TTS pipeline
without any WebSocket / frontend dependency.

Audio is captured via PyAudio and played back via PyAudio output stream.
All events are logged comprehensively to file + console.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import wave
from typing import Callable, Awaitable

import pyaudio

from .config import (
    WAKE_PHRASE_START,
    WAKE_PHRASE_STOP,
    MAX_TOOL_ITERATIONS,
    PCM_SAMPLE_RATE,
    TTS_SAMPLE_RATE,
)
from .stt_client import STTClient
from .tts_client import TTSClient
from .llm_client import LLMClient
from .browser_agent import BrowserAgent
from .audio_utils import pcm_bytes_to_base64

logger = logging.getLogger(__name__)

# Mic capture settings
CHUNK_FRAMES = 2048  # ~128 ms at 16 kHz


class CLISession:
    """Standalone session: mic → STT → LLM → browser → TTS → speaker."""

    def __init__(self):
        self.stt = STTClient()
        self.tts = TTSClient()
        self.llm = LLMClient()
        self.browser = BrowserAgent()

        self.is_awake: bool = False
        self.is_agent_speaking: bool = False
        self.pending_llm_task: asyncio.Task | None = None

        # PyAudio handles
        self._pa: pyaudio.PyAudio | None = None
        self._mic_stream = None
        self._speaker_stream = None
        self._running = False

        # Debug audio WAV file
        self._debug_wav: wave.Wave_write | None = None
        self._debug_wav_path: str | None = None

        # Counters for logging
        self._audio_chunks_sent = 0
        self._tts_chunks_received = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot everything: browser, STT, TTS, mic, speaker."""
        t0 = time.monotonic()

        # Browser
        logger.info("=" * 60)
        logger.info("SESSION START")
        logger.info("=" * 60)

        logger.info("[BROWSER] Launching Playwright (headless=False)...")
        await self.browser.start(headless=False)
        logger.info("[BROWSER] Ready — standing by on about:blank")

        # STT
        logger.info("[STT] Connecting to ElevenLabs Scribe...")
        self.stt.on_partial = self._on_stt_partial
        self.stt.on_committed = self._on_stt_committed
        await self.stt.connect()
        logger.info("[STT] Connected")

        # TTS
        logger.info("[TTS] Initialising ElevenLabs TTS client...")
        self.tts.on_audio_chunk = self._on_tts_audio
        await self.tts.connect()
        logger.info("[TTS] Ready")

        # PyAudio — mic input + speaker output
        self._pa = pyaudio.PyAudio()
        self._mic_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=PCM_SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_FRAMES,
        )
        self._speaker_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=TTS_SAMPLE_RATE,
            output=True,
            frames_per_buffer=4096,
        )
        logger.info("[AUDIO] Mic opened (rate=%d, chunk=%d)", PCM_SAMPLE_RATE, CHUNK_FRAMES)
        logger.info("[AUDIO] Speaker opened (rate=%d)", TTS_SAMPLE_RATE)

        # Debug WAV file — save all captured audio for debugging
        from pathlib import Path
        log_dir = Path(os.environ.get("YANKI_LOG_DIR", "logs"))
        log_dir.mkdir(exist_ok=True)
        from datetime import datetime
        wav_name = f"debug_audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        self._debug_wav_path = str(log_dir / wav_name)
        self._debug_wav = wave.open(self._debug_wav_path, "wb")
        self._debug_wav.setnchannels(1)
        self._debug_wav.setsampwidth(2)  # 16-bit
        self._debug_wav.setframerate(PCM_SAMPLE_RATE)
        logger.info("[AUDIO] Debug WAV: %s", self._debug_wav_path)

        elapsed = time.monotonic() - t0
        logger.info("[STARTUP] All systems ready in %.2fs", elapsed)
        print("\n" + "=" * 60)
        print("  🎙️  YANKI CLI – Voice Web Navigator")
        print("  Say 'echo start' to wake, 'echo stop' to sleep")
        print("  Press Ctrl+C to quit")
        print("=" * 60 + "\n")

    async def run_mic_loop(self) -> None:
        """Continuously read mic and stream to STT. Runs until cancelled."""
        self._running = True
        loop = asyncio.get_event_loop()

        logger.info("[MIC] Starting mic capture loop")
        while self._running:
            try:
                pcm_bytes = await loop.run_in_executor(
                    None, self._mic_stream.read, CHUNK_FRAMES, False
                )

                # Save to debug WAV
                if self._debug_wav:
                    self._debug_wav.writeframes(pcm_bytes)

                # Send to STT — fire-and-forget so we don't slow the mic loop
                b64 = base64.b64encode(pcm_bytes).decode("utf-8")
                asyncio.create_task(self.stt.send_audio(b64))
                self._audio_chunks_sent += 1

                # Log chunk count periodically
                if self._audio_chunks_sent % 200 == 0:
                    logger.debug(
                        "[MIC] Audio chunks sent so far: %d (~%.1fs of audio)",
                        self._audio_chunks_sent,
                        self._audio_chunks_sent * CHUNK_FRAMES / PCM_SAMPLE_RATE,
                    )
            except Exception:
                logger.exception("[MIC] Error reading/sending audio chunk")
                await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # STT callbacks
    # ------------------------------------------------------------------

    async def _on_stt_partial(self, text: str, speaker: str) -> None:
        logger.debug("[STT] Partial [%s]: %s", speaker, text)
        print(f"  💬 [{speaker}] {text}", end="\r", flush=True)
        
        # Immediate interruption: If the agent is currently speaking, stop it immediately
        # when we hear *anything* from the user.
        if self.is_agent_speaking and text.strip():
            logger.info("[INTERRUPT] User started speaking (partial transcript received) — stopping TTS")
            await self._interrupt()

    async def _on_stt_committed(self, text: str, speaker: str) -> None:
        logger.info("[STT] ✅ Committed transcript [%s]: \"%s\"", speaker, text)
        print(f"\n  ✅ You said [{speaker}]: {text}")

        lower = text.lower().strip()

        # Wake / sleep
        if WAKE_PHRASE_START in lower:
            self.is_awake = True
            logger.info("[WAKE] Activated by wake phrase")
            print("  🟢 AWAKE — listening for commands")
            await self._speak("I am listening. How can I help?")
            return

        if WAKE_PHRASE_STOP in lower:
            self.is_awake = False
            await self._interrupt()
            logger.info("[WAKE] Deactivated by stop phrase")
            print("  🔴 ASLEEP — say 'echo start' to wake")
            await self._speak("Going to sleep. Say echo start to wake me.")
            return

        if not self.is_awake:
            logger.debug("[STT] Ignoring (not awake): \"%s\"", text)
            return

        # Interrupt current work if needed
        if self.is_agent_speaking or (self.pending_llm_task and not self.pending_llm_task.done()):
            logger.info("[INTERRUPT] New input while agent busy — cancelling current work")
            await self._interrupt()

        # Run tool loop
        self.pending_llm_task = asyncio.create_task(self._run_tool_loop(text))

    # ------------------------------------------------------------------
    # LLM Tool Loop (core agent logic)
    # ------------------------------------------------------------------

    async def _run_tool_loop(self, user_text: str) -> None:
        """Agentic loop: LLM → tool calls → execute → repeat."""
        try:
            loop_t0 = time.monotonic()
            logger.info("=" * 40)
            logger.info("[AGENT] Starting tool loop for: \"%s\"", user_text)
            print(f"  🤖 Processing: {user_text}")

            # Get current page context
            ctx_t0 = time.monotonic()
            url, title, interactive = await self.browser.get_page_markdown()
            logger.info(
                "[BROWSER] Page context fetched in %.2fs — URL: %s | Title: %s | Interactive elements: %d chars",
                time.monotonic() - ctx_t0, url, title, len(interactive),
            )
            self.llm.set_page_context(url, title, interactive)
            self.llm.add_user_message(user_text)

            for iteration in range(MAX_TOOL_ITERATIONS):
                if asyncio.current_task().cancelling() > 0:
                    return

                logger.info("[LLM] Iteration %d/%d — calling Mistral...", iteration + 1, MAX_TOOL_ITERATIONS)
                llm_t0 = time.monotonic()
                response = await asyncio.to_thread(self.llm.get_response)
                llm_elapsed = time.monotonic() - llm_t0

                assistant_msg = response.choices[0].message
                finish_reason = response.choices[0].finish_reason
                logger.info(
                    "[LLM] Response in %.2fs — finish_reason: %s | has_content: %s | tool_calls: %d",
                    llm_elapsed,
                    finish_reason,
                    bool(assistant_msg.content),
                    len(assistant_msg.tool_calls) if assistant_msg.tool_calls else 0,
                )

                if assistant_msg.content:
                    logger.info("[LLM] Content: %s", assistant_msg.content[:200])

                self.llm.add_assistant_message(assistant_msg)

                if not assistant_msg.tool_calls:
                    if assistant_msg.content:
                        await self._speak(assistant_msg.content)
                    logger.info("[AGENT] No tool calls — loop complete")
                    return

                has_browser_action = False

                # --- Separate tool calls by type ---
                answer_calls = []
                browser_call = None  # only first browser action

                for tc_idx, tool_call in enumerate(assistant_msg.tool_calls):
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        logger.error("[TOOL] Invalid JSON args for %s: %s", fn_name, e)
                        self.llm.add_tool_result(
                            tool_call.id, fn_name, "Error: invalid JSON arguments"
                        )
                        has_browser_action = True
                        continue

                    logger.info(
                        "[TOOL] Call %d: %s(%s)",
                        tc_idx + 1, fn_name, json.dumps(fn_args, ensure_ascii=False),
                    )

                    if fn_name == "answer_to_user":
                        answer_calls.append((tool_call, fn_args))
                    elif browser_call is None:
                        browser_call = (tool_call, fn_name, fn_args)
                    else:
                        # Safety: skip extra browser actions (element IDs change)
                        self.llm.add_tool_result(
                            tool_call.id, fn_name,
                            "Skipped: only one browser action per turn. Re-evaluate the page and try again."
                        )
                        logger.info("[TOOL] Skipped extra browser action: %s", fn_name)

                # --- Browser action coroutine ---
                async def _run_browser_action():
                    tc, fn_name, fn_args = browser_call
                    action_t0 = time.monotonic()

                    if fn_name == "click_element":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        logger.info("[BROWSER] Clicking element %d (\"%s\")", eid, label)
                        result = await self.browser.click_element(eid)
                        logger.info("[BROWSER] Click result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Clicked {label}")
                        print(f"  🖱️  Clicked {label}")

                    elif fn_name == "type_text":
                        eid = fn_args["element_id"]
                        text = fn_args["text"]
                        label = self.browser.get_element_label(eid)
                        logger.info("[BROWSER] Typing into element %d (\"%s\"): \"%s\"", eid, label, text)
                        result = await self.browser.type_text(eid, text)
                        logger.info("[BROWSER] Type result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Typed '{text}' into {label}")
                        print(f"  ⌨️  Typed '{text}' into {label}")

                    elif fn_name == "type_and_submit":
                        eid = fn_args["element_id"]
                        text = fn_args["text"]
                        label = self.browser.get_element_label(eid)
                        logger.info("[BROWSER] Type and submit element %d (\"%s\"): \"%s\"", eid, label, text)
                        result = await self.browser.type_and_submit(eid, text)
                        logger.info("[BROWSER] Type result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Searched '{text}' in {label}")
                        print(f"  🔍  Searched '{text}' in {label}")

                    elif fn_name == "hover_element":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        logger.info("[BROWSER] Hovering over element %d (\"%s\")", eid, label)
                        result = await self.browser.hover_element(eid)
                        logger.info("[BROWSER] Hover result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Hovered over {label}")
                        print(f"  👆  Hovered over {label}")

                    elif fn_name == "select_option":
                        eid = fn_args["element_id"]
                        value = fn_args["value"]
                        label = self.browser.get_element_label(eid)
                        logger.info("[BROWSER] Selecting option '%s' in element %d (\"%s\")", value, eid, label)
                        result = await self.browser.select_option(eid, value)
                        logger.info("[BROWSER] Select result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Selected '{value}' from {label}")
                        print(f"  ✅  Selected '{value}' from {label}")

                    elif fn_name == "scroll_to_element":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        logger.info("[BROWSER] Scrolling to element %d (\"%s\")", eid, label)
                        result = await self.browser.scroll_to_element(eid)
                        logger.info("[BROWSER] Scroll to result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Scrolled to {label}")
                        print(f"  📜  Scrolled to {label}")

                    elif fn_name == "scroll_down":
                        logger.info("[BROWSER] Scrolling down")
                        result = await self.browser.scroll_down()
                        logger.info("[BROWSER] Scroll down result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action("Scrolled down")
                        print("  ⬇️  Scrolled down")

                    elif fn_name == "scroll_up":
                        logger.info("[BROWSER] Scrolling up")
                        result = await self.browser.scroll_up()
                        logger.info("[BROWSER] Scroll up result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action("Scrolled up")
                        print("  ⬆️  Scrolled up")

                    elif fn_name == "go_to_url":
                        target_url = fn_args["url"]
                        logger.info("[BROWSER] Navigating to: %s", target_url)
                        result = await self.browser.go_to_url(target_url)
                        logger.info("[BROWSER] Navigation result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Navigated to {target_url}")
                        print(f"  🌐 Navigated to {target_url}")

                    elif fn_name == "get_iframe_content":
                        iframe_id = fn_args["iframe_id"]
                        logger.info("[BROWSER] Getting iframe content for iframe %d", iframe_id)
                        result = await self.browser.get_iframe_content(iframe_id)
                        logger.info("[BROWSER] Iframe content result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Read iframe {iframe_id} content")
                        print(f"  🔎 Read iframe {iframe_id} content")

                    elif fn_name == "click_iframe_element":
                        iframe_id = fn_args["iframe_id"]
                        eid = fn_args["element_id"]
                        logger.info("[BROWSER] Clicking element %d in iframe %d", eid, iframe_id)
                        result = await self.browser.click_iframe_element(iframe_id, eid)
                        logger.info("[BROWSER] Iframe click result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Clicked element {eid} in iframe {iframe_id}")
                        print(f"  🖱️  Clicked element {eid} in iframe {iframe_id}")

                    elif fn_name == "type_iframe_text":
                        iframe_id = fn_args["iframe_id"]
                        eid = fn_args["element_id"]
                        text = fn_args["text"]
                        logger.info("[BROWSER] Typing '%s' into element %d in iframe %d", text, eid, iframe_id)
                        result = await self.browser.type_iframe_text(iframe_id, eid, text)
                        logger.info("[BROWSER] Iframe type result (%.2fs): %s", time.monotonic() - action_t0, result[:300])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Typed '{text}' in iframe {iframe_id}")
                        print(f"  ⌨️  Typed '{text}' in iframe {iframe_id}")

                    else:
                        logger.warning("[TOOL] Unknown tool: %s", fn_name)
                        self.llm.add_tool_result(tc.id, fn_name, f"Unknown tool: {fn_name}")

                # --- Answer coroutine ---
                async def _run_answers(fire_and_forget: bool = False):
                    for tc, fn_args in answer_calls:
                        text = fn_args.get("text", "")
                        if text:
                            logger.info("[AGENT→USER] \"%s\"", text)
                            print(f"  🗣️  Agent: {text}")
                            if fire_and_forget:
                                # Non-blocking: play TTS in background while loop continues
                                self.is_agent_speaking = True
                                await self.tts.speak(text)
                            else:
                                # Blocking: wait for TTS to finish (final answer)
                                await self._speak(text)
                        self.llm.add_tool_result(tc.id, "answer_to_user", "Delivered to user.")

                # --- Execute concurrently ---
                if browser_call and answer_calls:
                    # Run both concurrently — narrate (fire-and-forget) while acting
                    has_browser_action = True
                    await asyncio.gather(
                        _run_browser_action(),
                        _run_answers(fire_and_forget=True),
                    )
                elif browser_call:
                    has_browser_action = True
                    await _run_browser_action()
                elif answer_calls:
                    # Final answer — no browser action, wait for TTS to finish
                    await _run_answers(fire_and_forget=False)

                if asyncio.current_task().cancelling() > 0:
                    return

                # Only exit when NO browser action was taken (task complete)
                if not has_browser_action:
                    logger.info("[AGENT] Only answer_to_user called — task complete")
                    return

                # Browser action taken — refresh page context for next iteration
                # Safety net: ensure page is stable before extracting DOM
                await self.browser._wait_for_page_stable()
                ctx_t0 = time.monotonic()
                url, title, interactive = await self.browser.get_page_markdown()
                logger.info(
                    "[BROWSER] Page context refreshed in %.2fs — URL: %s | Title: %s",
                    time.monotonic() - ctx_t0, url, title,
                )
                self.llm.set_page_context(url, title, interactive)

            # Max iterations
            logger.warning("[AGENT] Max iterations (%d) reached", MAX_TOOL_ITERATIONS)
            await self._speak(
                "I've taken several actions but need more guidance. What would you like me to do next?"
            )

        except asyncio.CancelledError:
            logger.info("[AGENT] Tool loop cancelled (interrupted)")
        except Exception:
            logger.exception("[AGENT] Tool loop error")
            await self._speak("Sorry, something went wrong. Please try again.")
        finally:
            total_elapsed = time.monotonic() - loop_t0
            logger.info("[AGENT] Tool loop finished in %.2fs", total_elapsed)
            logger.info("=" * 40)

    # ------------------------------------------------------------------
    # TTS / Audio playback
    # ------------------------------------------------------------------

    async def _speak(self, text: str) -> None:
        """Send text to TTS and play result through speakers."""
        self.is_agent_speaking = True
        try:
            self._tts_chunks_received = 0
            logger.info("[TTS] Speaking: \"%s\"", text)
            await self.tts.speak_and_wait(text)
            logger.info("[TTS] Finished speaking (%d chunks)", self._tts_chunks_received)
        except asyncio.CancelledError:
            logger.info("[TTS] Speech cancelled by interrupt")
            raise
        finally:
            self.is_agent_speaking = False

    async def _on_tts_audio(self, audio_bytes: bytes) -> None:
        """Play TTS audio chunk through PyAudio speaker.

        IMPORTANT: The write is offloaded to a thread so it doesn't block the
        asyncio event loop.  A blocking write would prevent STT callbacks and
        interrupt tasks from being scheduled — the primary cause of the
        intermittent interruption bug.
        """
        try:
            if self._speaker_stream and self._speaker_stream.is_active():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, self._speaker_stream.write, audio_bytes
                )
                self._tts_chunks_received += 1
                if self._tts_chunks_received % 20 == 1:
                    logger.debug(
                        "[TTS] Audio chunk #%d (%d bytes)",
                        self._tts_chunks_received, len(audio_bytes),
                    )
        except Exception:
            logger.exception("[TTS] Failed to play audio chunk")

    # ------------------------------------------------------------------
    # Interruption
    # ------------------------------------------------------------------

    async def _interrupt(self) -> None:
        logger.info("[INTERRUPT] Interrupting current work...")

        # Stop TTS FIRST for immediate silence — before awaiting the LLM task,
        # which could take time and would leave TTS streaming in the meantime.
        await self.tts.interrupt()
        self.is_agent_speaking = False

        if self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()
            try:
                await self.pending_llm_task
            except asyncio.CancelledError:
                pass
            self.pending_llm_task = None

        self.llm.rollback_after_interrupt()
        logger.info("[INTERRUPT] Agent interrupted — state cleaned up")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        logger.info("[SHUTDOWN] Cleaning up...")
        self._running = False

        if self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()

        await self.stt.close()
        await self.tts.close()
        await self.browser.close()

        if self._debug_wav:
            self._debug_wav.close()
            logger.info("[AUDIO] Debug WAV saved: %s", self._debug_wav_path)

        if self._mic_stream:
            self._mic_stream.stop_stream()
            self._mic_stream.close()
        if self._speaker_stream:
            self._speaker_stream.stop_stream()
            self._speaker_stream.close()
        if self._pa:
            self._pa.terminate()

        logger.info("[SHUTDOWN] All resources released")
        logger.info(
            "[STATS] Total audio chunks sent to STT: %d (~%.1fs of audio)",
            self._audio_chunks_sent,
            self._audio_chunks_sent * CHUNK_FRAMES / PCM_SAMPLE_RATE,
        )
        logger.info("=" * 60)
        logger.info("SESSION END")
        logger.info("=" * 60)
