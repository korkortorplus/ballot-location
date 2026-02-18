"""Playwright headless browser for screenshots and turf.js evaluation."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger("map_tool.browser")


class HeadlessBrowser:
    """Manages a headless Chromium page that connects to the map server."""

    def __init__(self, base_url: str = "http://localhost:3000") -> None:
        self._base_url = base_url
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        await self._page.goto(self._base_url, wait_until="networkidle")
        # Wait for the map to signal readiness
        try:
            await self._page.wait_for_function(
                "window.__mapReady === true", timeout=15000
            )
        except Exception:
            logger.warning(
                "Map ready signal not received within timeout, proceeding anyway"
            )

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None

    async def screenshot(
        self,
        *,
        width: int = 1280,
        height: int = 960,
        basemap: str | None = None,
    ) -> str:
        """Take a screenshot and return base64-encoded PNG."""
        if not self._page:
            raise RuntimeError("Browser not started")

        await self._page.set_viewport_size({"width": width, "height": height})

        # Switch basemap if requested
        if basemap:
            await self._page.evaluate(
                f"window.__setBasemap && window.__setBasemap('{basemap}')"
            )
            await asyncio.sleep(1)

        # Wait for map to be idle (tiles loaded)
        try:
            await self._page.wait_for_function(
                "window.__mapIdle === true", timeout=10000
            )
        except Exception:
            await asyncio.sleep(2)

        buf = await self._page.screenshot(type="png")
        return base64.b64encode(buf).decode("ascii")

    async def evaluate_js(self, expression: str) -> Any:
        """Evaluate a JavaScript expression in the browser page."""
        if not self._page:
            raise RuntimeError("Browser not started")
        return await self._page.evaluate(expression)
