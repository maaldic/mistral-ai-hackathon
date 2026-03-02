from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

from .audio_utils import pcm_bytes_to_base64
from .config import WAKE_PHRASE_START, WAKE_PHRASE_STOP, MAX_TOOL_ITERATIONS
from .stt_client import STTClient
from .tts_client import TTSClient
from .llm_client import LLMClient
from .browser_agent import BrowserAgent

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, client_ws: WebSocket):
        self.client_ws = client_ws
        self.stt = STTClient()
        self.tts = TTSClient()
        self.llm = LLMClient()
        self.browser = BrowserAgent()

        self.is_awake: bool = False
        self.is_agent_speaking: bool = False
        self.browser_started: bool = False
        self.pending_llm_task: asyncio.Task | None = None

    async def start(self) -> None:
        # Connect STT
        self.stt.on_partial = self._on_stt_partial
        self.stt.on_committed = self._on_stt_committed
        await self.stt.connect()

        # Connect TTS
        self.tts.on_audio_chunk = self._on_tts_audio
        await self.tts.connect()

        # Pre-warm browser immediately so it's ready when user wakes it up
        await self._ensure_browser()
        logger.info("Session started and browser pre-warmed")

    async def handle_client_audio(self, pcm_bytes: bytes) -> None:
        """Handle binary audio from the React client."""
        b64 = pcm_bytes_to_base64(pcm_bytes)
        await self.stt.send_audio(b64)

    async def _ensure_browser(self) -> None:
        """Launch browser on first activation."""
        if not self.browser_started:
            logger.info("Launching browser...")
            await self.browser.start(headless=False)
            self.browser_started = True
            logger.info("Browser ready")

    async def handle_client_message(self, message: dict) -> None:
        """Handle JSON messages from the React client."""
        msg_type = message.get("type")

        if msg_type == "wake_command":
            action = message.get("action")
            if action == "start":
                await self._ensure_browser()
                self.is_awake = True
                await self._speak("Navigation active. How can I help?")
                await self._send_status("idle")
            elif action == "stop":
                self.is_awake = False
                await self._speak("Going to sleep. Say echo start to wake me.")
                await self._send_status("idle")

    # --- STT Callbacks ---

    async def _on_stt_partial(self, text: str) -> None:
        """Forward partial transcript to client UI."""
        await self._send_json({"type": "transcript_partial", "text": text})

    async def _on_stt_committed(self, text: str) -> None:
        """Handle finalized transcript - the main orchestration entry point."""
        logger.info("STT committed: %s", text)
        await self._send_json({"type": "transcript_final", "text": text})

        lower = text.lower().strip()

        # Wake word detection
        if WAKE_PHRASE_START in lower:
            await self._ensure_browser()
            self.is_awake = True
            await self._speak("I am listening. How can I help?")
            await self._send_status("idle")
            return

        if WAKE_PHRASE_STOP in lower:
            self.is_awake = False
            await self._interrupt()
            await self._speak("Going to sleep. Say echo start to wake me.")
            await self._send_status("idle")
            return

        if not self.is_awake:
            return

        # Interrupt if agent is currently speaking or processing
        if self.is_agent_speaking or (self.pending_llm_task and not self.pending_llm_task.done()):
            await self._interrupt()

        # Start new LLM interaction
        self.pending_llm_task = asyncio.create_task(self._run_tool_loop(text))

    # --- LLM Tool Loop ---

    async def _run_tool_loop(self, user_text: str) -> None:
        """The agentic loop: LLM -> tool calls -> execute -> repeat."""
        try:
            await self._send_status("thinking")

            # Update LLM with current page context
            url, title, interactive = await self.browser.get_page_markdown()
            self.llm.set_page_context(url, title, interactive)
            self.llm.add_user_message(user_text)

            for iteration in range(MAX_TOOL_ITERATIONS):
                # Check cancellation
                if asyncio.current_task().cancelling() > 0:
                    return

                # Non-streaming Mistral call (sync, in thread)
                response = await asyncio.to_thread(self.llm.get_response)

                assistant_msg = response.choices[0].message
                self.llm.add_assistant_message(assistant_msg)
                print(assistant_msg)

                if not assistant_msg.tool_calls:
                    # No tool calls - shouldn't happen with tool_choice="any"
                    if assistant_msg.content:
                        await self._speak(assistant_msg.content)
                    return

                has_browser_action = False
                has_answered = False

                # Separate answer_to_user from browser actions for concurrent execution
                answer_calls = []
                browser_call = None  # Only first browser action
                skipped_calls = []

                for tool_call in assistant_msg.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        self.llm.add_tool_result(
                            tool_call.id, fn_name,
                            "Error: invalid JSON arguments"
                        )
                        has_browser_action = True
                        continue

                    logger.info("Tool call: %s(%s)", fn_name, fn_args)

                    if fn_name == "answer_to_user":
                        answer_calls.append((tool_call, fn_args))
                    elif browser_call is None:
                        browser_call = (tool_call, fn_name, fn_args)
                    else:
                        # Safety net: skip extra browser actions
                        self.llm.add_tool_result(
                            tool_call.id, fn_name,
                            "Skipped: only one browser action per turn. Re-evaluate the page and try again."
                        )
                        logger.info("Skipped extra browser action: %s", fn_name)

                # Execute browser action and answer_to_user concurrently
                async def _run_browser_action():
                    tc, fn_name, fn_args = browser_call
                    await self._send_status("browsing")

                    if fn_name == "click_element":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        result = await self.browser.click_element(eid)
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Clicked \"{label}\"")
                        await self._send_browser_action("click", fn_name)

                    elif fn_name == "type_text":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        result = await self.browser.type_text(eid, fn_args["text"])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Typed '{fn_args['text']}' into \"{label}\"")
                        await self._send_browser_action("type", fn_name)

                    elif fn_name == "type_and_submit":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        result = await self.browser.type_and_submit(eid, fn_args["text"])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Searched '{fn_args['text']}' in \"{label}\"")
                        await self._send_browser_action("type_submit", fn_name)

                    elif fn_name == "select_option":
                        eid = fn_args["element_id"]
                        label = self.browser.get_element_label(eid)
                        result = await self.browser.select_option(eid, fn_args["value"])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Selected '{fn_args['value']}' from \"{label}\"")
                        await self._send_browser_action("select", fn_name)

                    elif fn_name == "scroll_down":
                        amount = fn_args.get("amount", 3)
                        result = await self.browser.scroll_down(amount)
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action("Scrolled down")
                        await self._send_browser_action("scroll_down", fn_name)

                    elif fn_name == "scroll_up":
                        amount = fn_args.get("amount", 3)
                        result = await self.browser.scroll_up(amount)
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action("Scrolled up")
                        await self._send_browser_action("scroll_up", fn_name)

                    elif fn_name == "go_to_url":
                        result = await self.browser.go_to_url(fn_args["url"])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Navigated to {fn_args['url']}")
                        await self._send_browser_action("navigate", fn_name)

                    elif fn_name == "get_iframe_content":
                        result = await self.browser.get_iframe_content(fn_args["iframe_id"])
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Read iframe {fn_args['iframe_id']} content")
                        await self._send_browser_action("iframe_read", fn_name)

                    elif fn_name == "click_iframe_element":
                        result = await self.browser.click_iframe_element(
                            fn_args["iframe_id"], fn_args["element_id"]
                        )
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Clicked element {fn_args['element_id']} in iframe {fn_args['iframe_id']}")
                        await self._send_browser_action("iframe_click", fn_name)

                    elif fn_name == "type_iframe_text":
                        result = await self.browser.type_iframe_text(
                            fn_args["iframe_id"], fn_args["element_id"], fn_args["text"]
                        )
                        self.llm.add_tool_result(tc.id, fn_name, result)
                        self.llm.add_action(f"Typed '{fn_args['text']}' in iframe {fn_args['iframe_id']}")
                        await self._send_browser_action("iframe_type", fn_name)

                    else:
                        self.llm.add_tool_result(tc.id, fn_name, f"Unknown tool: {fn_name}")

                async def _run_answers(fire_and_forget: bool = False):
                    for tc, fn_args in answer_calls:
                        text = fn_args.get("text", "")
                        if text:
                            if fire_and_forget:
                                # Non-blocking: play TTS in background while loop continues
                                self.is_agent_speaking = True
                                await self.tts.speak(text)
                            else:
                                # Blocking: wait for TTS to finish (final answer)
                                await self._speak(text)
                            await self._send_json({"type": "agent_text", "text": text})
                        self.llm.add_tool_result(tc.id, "answer_to_user", "Delivered to user.")

                if browser_call and answer_calls:
                    # Run both concurrently — narrate (fire-and-forget) while acting
                    has_browser_action = True
                    has_answered = True
                    await asyncio.gather(
                        _run_browser_action(),
                        _run_answers(fire_and_forget=True),
                    )
                elif browser_call:
                    has_browser_action = True
                    await _run_browser_action()
                elif answer_calls:
                    # Final answer — no browser action, wait for TTS to finish
                    has_answered = True
                    await _run_answers(fire_and_forget=False)

                if asyncio.current_task().cancelling() > 0:
                    return

                # If only answer_to_user was called (no browser actions), we're done
                if not has_browser_action:
                    await self._send_status("idle")
                    return

                # Browser actions were taken — refresh page context for next iteration
                url, title, interactive = await self.browser.get_page_markdown()
                self.llm.set_page_context(url, title, interactive)

            # Max iterations reached
            await self._speak("I've taken several actions but need more guidance. What would you like me to do next?")
            await self._send_status("idle")

        except asyncio.CancelledError:
            logger.info("Tool loop cancelled (interrupted)")
        except Exception:
            logger.exception("Tool loop error")
            await self._speak("Sorry, something went wrong. Please try again.")
            await self._send_status("idle")

    # --- TTS / Audio ---

    async def _speak(self, text: str) -> None:
        """Send text to TTS for speech synthesis."""
        self.is_agent_speaking = True
        try:
            await self._send_status("speaking")
            await self.tts.speak_and_wait(text)
        except asyncio.CancelledError:
            logger.info("[TTS] Speech cancelled by interrupt")
            raise
        finally:
            self.is_agent_speaking = False

    async def _on_tts_audio(self, audio_bytes: bytes) -> None:
        """Forward TTS audio to the client."""
        try:
            await self.client_ws.send_bytes(audio_bytes)
        except Exception:
            logger.warning("Failed to send audio to client")

    # --- Interruption ---

    async def _interrupt(self) -> None:
        """Cancel current speech and LLM processing."""
        logger.info("[INTERRUPT] Interrupting current work...")

        # Stop TTS FIRST for immediate silence — before awaiting the LLM task,
        # which could take time and would leave TTS streaming in the meantime.
        await self.tts.interrupt()
        await self._send_json({"type": "stop_audio"})
        self.is_agent_speaking = False

        # Cancel LLM task
        if self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()
            try:
                await self.pending_llm_task
            except asyncio.CancelledError:
                pass
            self.pending_llm_task = None

        self.llm.rollback_after_interrupt()
        logger.info("[INTERRUPT] Agent interrupted — state cleaned up")

    # --- Helpers ---

    async def _send_json(self, data: dict) -> None:
        try:
            await self.client_ws.send_json(data)
        except Exception:
            logger.warning("Failed to send JSON to client")

    async def _send_status(self, status: str) -> None:
        await self._send_json({"type": "agent_status", "status": status})

    async def _send_browser_action(self, action: str, tool_name: str) -> None:
        url = self.browser.page.url if self.browser.page else ""
        await self._send_json({
            "type": "browser_action",
            "action": action,
            "url": url,
        })

    async def shutdown(self) -> None:
        """Clean shutdown of all resources."""
        if self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()
        await self.stt.close()
        await self.tts.close()
        if self.browser_started:
            await self.browser.close()
        logger.info("Session shutdown complete")
