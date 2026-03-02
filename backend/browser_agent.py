from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Browser, Page, Dialog

logger = logging.getLogger(__name__)

DOM_EXTRACTOR_JS = (Path(__file__).parent / "dom_extractor.js").read_text()
LOG_DIR = Path(os.environ.get("YANKI_LOG_DIR", "logs"))


class BrowserAgent:
    def __init__(self):
        self._playwright = None
        self.browser: Browser | None = None
        self.context = None
        self.page: Page | None = None
        self._element_labels: dict[str, str] = {}
        self._last_dialog: dict | None = None  # stores info about last JS dialog
        self._iframe_selectors: dict[str, str] = {}  # iframe_id -> CSS selector

    async def start(self, headless: bool = False) -> None:
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
        )
        self.context.on("page", self._on_new_page)
        self.page = await self.context.new_page()
        self.page.on("dialog", self._on_dialog)
        await self.page.goto("about:blank", wait_until="domcontentloaded")
        logger.info("Browser started, standing by on about:blank")

    # --- JS Dialog Auto-Handler ---

    async def _on_dialog(self, dialog: Dialog) -> None:
        """Auto-handle JS alert/confirm/prompt dialogs so they don't block."""
        info = {
            "type": dialog.type,
            "message": dialog.message,
            "default_value": dialog.default_value,
        }
        self._last_dialog = info
        logger.info("JS dialog intercepted: %s — %s", dialog.type, dialog.message)
        # Accept immediately to unblock. For 'prompt' dialogs we send empty string.
        await dialog.accept()

    async def get_page_markdown(self) -> str:
        """Inject DOM extractor and return formatted page markdown."""
        try:
            result = await self.page.evaluate(DOM_EXTRACTOR_JS)
        except Exception as e:
            logger.error("DOM extraction failed: %s", e)
            return f"Error extracting page content: {e}"

        url = result.get("url", "")
        title = result.get("title", "")
        interactive = result.get("interactive", "")
        iframes = result.get("iframes", "")
        self._element_labels = result.get("elementLabels", {})
        self._iframe_selectors = result.get("iframeSelectors", {})

        # Append iframe section if any iframes detected
        if iframes:
            interactive += f"\n\nIFRAMES ON PAGE:\n{iframes}"

        # Append dialog info if one was recently dismissed
        if self._last_dialog:
            d = self._last_dialog
            interactive += (
                f"\n\n⚠️ JS DIALOG (auto-dismissed): "
                f"type={d['type']}, message=\"{d['message']}\""
            )
            self._last_dialog = None  # Clear after reporting

        return url, title, interactive

    def _on_new_page(self, page: Page) -> None:
        """Handle new tabs/windows by automatically switching the active page."""
        logger.info("New page/tab opened, switching context to it.")
        self.page = page
        # Attach dialog handler to new page too
        self.page.on("dialog", self._on_dialog)

    def get_element_label(self, element_id: int) -> str:
        """Get the label for an element by its agent ID."""
        return self._element_labels.get(str(element_id), f"element {element_id}")

    # --- Wait Helpers ---

    async def _wait_for_page_stable(self, timeout: int = 5000) -> None:
        """Wait until the DOM stops mutating and network is idle.

        Uses a MutationObserver inside the page: resolves once no DOM
        changes have happened for 500ms, OR when the timeout is hit.
        This properly handles lazy-loaded content, page reloads triggered
        by JS, and scroll-triggered rendering — unlike hardcoded sleeps.
        """
        try:
            await self.page.wait_for_function(
                """() => new Promise(resolve => {
                    // If the page is still loading, wait for that first
                    if (document.readyState !== 'complete') {
                        window.addEventListener('load', () => resolve(true), {once: true});
                        // But don't wait forever for load
                        setTimeout(() => resolve(true), 3000);
                        return;
                    }
                    let timer = setTimeout(() => { obs.disconnect(); resolve(true); }, 500);
                    const obs = new MutationObserver(() => {
                        clearTimeout(timer);
                        timer = setTimeout(() => { obs.disconnect(); resolve(true); }, 500);
                    });
                    obs.observe(document.body, {childList: true, subtree: true, attributes: true});
                })""",
                timeout=timeout,
            )
        except Exception:
            pass  # Timeout is fine — we gave the page enough time

    # --- Core Actions (existing) ---

    async def click_element(self, element_id: int) -> str:
        try:
            locator = self.page.locator(f'[data-agent-id="{element_id}"]')
            count = await locator.count()
            if count == 0:
                return f"Click failed: element with data-agent-id={element_id} not found on page"
            # Scroll into view and hover first (reveals hidden menus/dropdowns)
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.hover(timeout=3000)
            await self.page.wait_for_timeout(200)
            await locator.click(timeout=5000)
            await self._wait_for_page_stable()
        except Exception as e:
            return f"Click failed: {e}"
        return f"Clicked element {element_id} successfully. Page URL: {self.page.url}"

    async def type_text(self, element_id: int, text: str) -> str:
        try:
            locator = self.page.locator(f'[data-agent-id="{element_id}"]')
            count = await locator.count()
            if count == 0:
                return f"Type failed: element with data-agent-id={element_id} not found on page"
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=3000)
            await locator.fill(text, timeout=5000)
        except Exception as e:
            return f"Type failed: {e}"
        return f"Typed '{text}' into element {element_id} successfully."

    async def scroll_down(self, amount: int = 3) -> str:
        pixels = int(720 * amount / 3)
        await self.page.evaluate(f"window.scrollBy({{top: {pixels}, behavior: 'smooth'}})")
        await self.page.wait_for_timeout(600)  # smooth scroll animation
        await self._wait_for_page_stable()
        return f"Scrolled down ~{pixels}px."

    async def scroll_up(self, amount: int = 3) -> str:
        pixels = int(720 * amount / 3)
        await self.page.evaluate(f"window.scrollBy({{top: -{pixels}, behavior: 'smooth'}})")
        await self.page.wait_for_timeout(600)  # smooth scroll animation
        await self._wait_for_page_stable()
        return f"Scrolled up ~{pixels}px."

    async def go_to_url(self, url: str) -> str:
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await self._wait_for_page_stable()
        except Exception as e:
            return f"Navigation failed: {e}"
        return f"Navigated to {self.page.url}. Title: {await self.page.title()}"

    # --- New Actions ---

    async def type_and_submit(self, element_id: int, text: str) -> str:
        """Type character-by-character (triggering autocomplete) then press Enter.

        Unlike type_text (which uses instant fill()), this mimics real typing
        to trigger debounce timers, autocomplete suggestions, and search.
        """
        try:
            locator = self.page.locator(f'[data-agent-id="{element_id}"]')
            count = await locator.count()
            if count == 0:
                return f"Type failed: element with data-agent-id={element_id} not found"

            # Scroll into view, click to focus
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=3000)
            # Clear any existing value
            await locator.fill("", timeout=2000)
            # Type character-by-character to trigger autocomplete/debounce
            await locator.press_sequentially(text, delay=50)
            # Small wait for debounce + autocomplete network request
            await self.page.wait_for_timeout(800)
            # Submit with Enter
            await locator.press("Enter")
            await self._wait_for_page_stable()
        except Exception as e:
            return f"Type and submit failed: {e}"
        return f"Typed '{text}' and pressed Enter on element {element_id}. Page URL: {self.page.url}"

    async def select_option(self, element_id: int, value: str) -> str:
        """Select an option from a dropdown — native <select> or custom JS dropdown."""
        try:
            locator = self.page.locator(f'[data-agent-id="{element_id}"]')
            count = await locator.count()
            if count == 0:
                return f"Select failed: element with data-agent-id={element_id} not found"

            await locator.scroll_into_view_if_needed(timeout=3000)
            # Check if element is a native <select>
            tag = await locator.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                # Native select — use Playwright's built-in
                try:
                    await locator.select_option(label=value, timeout=3000)
                except Exception:
                    await locator.select_option(value=value, timeout=3000)
                await self._wait_for_page_stable()
                return f"Selected '{value}' from dropdown element {element_id}."

            # Custom dropdown fallback: click to open, then find & click matching option
            await locator.click(timeout=3000)
            await self.page.wait_for_timeout(500)  # Wait for dropdown to animate open

            # Look for the option by text across common patterns:
            # 1. ARIA listbox/option pattern
            # 2. Generic clickable elements containing the exact text
            option = None
            for selector in [
                f'[role="option"]:has-text("{value}")',
                f'[role="listbox"] >> text="{value}"',
                f'li:has-text("{value}")',
                f'[data-value="{value}"]',
            ]:
                try:
                    candidate = self.page.locator(selector).first
                    if await candidate.count() > 0 and await candidate.is_visible(timeout=1000):
                        option = candidate
                        break
                except Exception:
                    continue

            if not option:
                # Broad fallback: any visible element whose text matches exactly
                try:
                    option = self.page.get_by_text(value, exact=True).first
                    if not await option.is_visible(timeout=1000):
                        option = None
                except Exception:
                    option = None

            if option:
                await option.click(timeout=3000)
                await self._wait_for_page_stable()
                return f"Selected '{value}' from custom dropdown element {element_id}."
            else:
                return (
                    f"Select failed: opened dropdown {element_id} but couldn't find "
                    f"option '{value}'. Try clicking the specific option element instead."
                )
        except Exception as e:
            return f"Select failed: {e}"

    async def get_iframe_content(self, iframe_id: int) -> str:
        """Extract interactive elements from inside an iframe."""
        try:
            # Find the matching frame by its data-agent-iframe-id attribute
            frame = await self._get_iframe_frame(iframe_id)
            if not frame:
                return (
                    f"Iframe {iframe_id} not found or not accessible. "
                    f"This may be a cross-origin iframe that blocks content access."
                )

            result = await frame.evaluate(DOM_EXTRACTOR_JS)
            interactive = result.get("interactive", "")
            if not interactive:
                return f"Iframe {iframe_id} has no interactive elements."
            return f"IFRAME {iframe_id} CONTENTS:\n{interactive}"
        except Exception as e:
            return f"Iframe content extraction failed: {e}"

    async def click_iframe_element(self, iframe_id: int, element_id: int) -> str:
        """Click an element inside an iframe by its data-agent-id."""
        try:
            frame = await self._get_iframe_frame(iframe_id)
            if not frame:
                return f"Iframe {iframe_id} not found."

            locator = frame.locator(f'[data-agent-id="{element_id}"]')
            count = await locator.count()
            if count == 0:
                return f"Element {element_id} not found inside iframe {iframe_id}."
            await locator.click(timeout=5000)
            await self.page.wait_for_timeout(500)
        except Exception as e:
            return f"Iframe click failed: {e}"
        return f"Clicked element {element_id} inside iframe {iframe_id}."

    async def type_iframe_text(self, iframe_id: int, element_id: int, text: str) -> str:
        """Type text into an input field inside an iframe."""
        try:
            frame = await self._get_iframe_frame(iframe_id)
            if not frame:
                return f"Iframe {iframe_id} not found."

            locator = frame.locator(f'[data-agent-id="{element_id}"]')
            count = await locator.count()
            if count == 0:
                return f"Element {element_id} not found inside iframe {iframe_id}."
            await locator.click(timeout=3000)
            await locator.fill(text, timeout=5000)
        except Exception as e:
            return f"Iframe type failed: {e}"
        return f"Typed '{text}' into element {element_id} inside iframe {iframe_id}."

    async def _get_iframe_frame(self, iframe_id: int):
        """Find the Frame object for a given iframe agent ID."""
        for f in self.page.frames:
            try:
                frame_el = await f.frame_element()
                if frame_el:
                    agent_id = await frame_el.get_attribute("data-agent-iframe-id")
                    if agent_id == str(iframe_id):
                        return f
            except Exception:
                continue
        return None

    # --- Internals ---

    async def _page_summary(self) -> str:
        """Return a text summary of the current page state."""
        url, title, interactive = await self.get_page_markdown()
        return f"URL: {url}\nTitle: {title}\n\nInteractive elements:\n{interactive}"

    async def close(self) -> None:
        try:
            if self.page:
                await self.page.close(run_before_unload=False)
            
            if self.browser:
                # Close all contexts
                for context in self.browser.contexts:
                    await context.close()
                await self.browser.close()
                
        except Exception as e:
            logger.error("Error closing browser components: %s", e)
        finally:
            if self._playwright:
                await self._playwright.stop()
            logger.info("Browser closed")
