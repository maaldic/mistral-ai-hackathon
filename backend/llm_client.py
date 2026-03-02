from __future__ import annotations

import json
import logging

from mistralai import Mistral

from .config import MISTRAL_API_KEY, MISTRAL_MODEL, MAX_CONVERSATION_MESSAGES
from .tools import TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are Echo, a voice-controlled web browsing assistant. You help users navigate the web by taking browser actions and speaking to them.

CURRENT PAGE:
URL: {url}
Title: {title}

INTERACTIVE ELEMENTS:
{interactive}
{action_history}
AVAILABLE TOOLS:
- click_element(element_id) — click on an interactive element (auto-scrolls into view)
- type_text(element_id, text) — type into form fields (instant fill)
- type_and_submit(element_id, text) — type into search bars / autocomplete inputs then press Enter
- select_option(element_id, value) — pick from dropdowns
- scroll_down(amount) / scroll_up(amount) — scroll the page (1=small, 3=one viewport, 5=large)
- go_to_url(url) — navigate to a URL
- get_iframe_content(iframe_id) — read elements inside an iframe
- click_iframe_element(iframe_id, element_id) / type_iframe_text(iframe_id, element_id, text) — interact inside iframes
- answer_to_user(text) — speak to the user

TOOL CALLING RULES:
- Each turn, call EXACTLY ONE browser action tool. You may ALSO call answer_to_user in the same turn to briefly narrate what you are doing.
- NEVER call multiple browser actions in the same turn (e.g. click + type, type + click, click + scroll). Element IDs change after each action, so batching causes wrong element clicks. Do ONE browser action per turn.
- ONLY call answer_to_user WITHOUT a browser action when the user's ENTIRE request is fully completed and you are delivering the final answer or when you need to ask for clarification.

MULTI-STEP TASKS:
- When the user gives a request with multiple steps (e.g. "go to Amazon, search for books, sort by price, pick the first one"), you MUST keep going until ALL steps are done.
- After each browser action, you will see the updated page. Determine what the NEXT step is and take it immediately.
- Do NOT stop after completing just one step to report partial progress. Keep acting.
- Narrate briefly as you go (e.g. "Searching for Python books now") but ALWAYS pair narration with the next browser action.
- Only call answer_to_user alone when every part of the user's request is fulfilled.

RESPONSE STYLE:
- Keep spoken responses concise (1-2 short sentences)
- Briefly narrate what you are doing, do not over-explain"""


class LLMClient:
    def __init__(self):
        self.client = Mistral(api_key=MISTRAL_API_KEY)
        self.messages: list[dict] = []
        self._system_prompt = "You are Echo, a voice assistant. Use answer_to_user to speak."
        self._action_history: list[str] = []

    def add_action(self, description: str) -> None:
        """Record an action taken by the agent for context."""
        self._action_history.append(description)
        # Keep only last 10 actions to avoid prompt bloat
        if len(self._action_history) > 10:
            self._action_history = self._action_history[-10:]

    def set_page_context(self, url: str, title: str, interactive: str) -> None:
        history_block = ""
        if self._action_history:
            history_block = "\nRECENT ACTIONS:\n" + "\n".join(f"- {a}" for a in self._action_history) + "\n"
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            url=url,
            title=title,
            interactive=interactive,
            action_history=history_block,
        )

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self._truncate()

    def add_assistant_message(self, message) -> None:
        """Add raw assistant message from Mistral response."""
        msg = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        self.messages.append({
            "role": "tool",
            "name": name,
            "content": result,
            "tool_call_id": tool_call_id,
        })

    def get_response(self):
        """Synchronous Mistral call. Wrap in asyncio.to_thread for async usage."""
        all_messages = [{"role": "system", "content": self._system_prompt}] + self.messages

        logger.info("LLM request: %d messages, %d chars system prompt",
                     len(all_messages), len(self._system_prompt))
        
        # Log the full system prompt for debugging purposes
        logger.debug("LLM System Prompt Details:\n%s\n--- END PROMPT ---", self._system_prompt)

        response = self.client.chat.complete(
            model=MISTRAL_MODEL,
            messages=all_messages,
            tools=TOOLS,
            tool_choice="any",
            parallel_tool_calls=True,
        )

        logger.info("LLM response: %s", response.choices[0].finish_reason)
        return response

    def rollback_after_interrupt(self) -> None:
        """Remove trailing messages that leave tool calls unresolved.

        After an interrupted tool loop, the conversation may contain an
        assistant message with tool_calls followed by zero or more tool
        results (but fewer than the tool_calls requested).  This leaves
        the history in a state that the Mistral API rejects.

        Walk backwards: remove any trailing tool results AND the
        incomplete assistant message that triggered them.
        """
        while self.messages:
            last = self.messages[-1]
            if last["role"] == "tool":
                self.messages.pop()
            elif last["role"] == "assistant" and last.get("tool_calls"):
                self.messages.pop()
                break
            else:
                break
        logger.info(
            "[LLM] Rolled back conversation after interrupt (%d messages remain)",
            len(self.messages),
        )

    def _truncate(self) -> None:
        if len(self.messages) > MAX_CONVERSATION_MESSAGES:
            # Keep the most recent messages
            self.messages = self.messages[-MAX_CONVERSATION_MESSAGES:]
            # Ensure the conversation doesn't start with an orphaned 'tool'
            # message or an 'assistant' with tool_calls whose results were
            # truncated away.  Either would produce an invalid role sequence
            # when the system prompt is prepended (system → tool is rejected
            # by the Mistral API).
            while self.messages:
                first = self.messages[0]
                if first["role"] == "tool":
                    self.messages.pop(0)
                elif first["role"] == "assistant" and first.get("tool_calls"):
                    # This assistant message expects tool results that may
                    # have been truncated — drop it to avoid an incomplete
                    # exchange.
                    self.messages.pop(0)
                else:
                    break
