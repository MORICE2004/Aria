"""ARIA Browser Automation Subsystem.

Provides controlled, headless browser automation for web tasks (research, job portal
inspection, and form assistance) using Playwright and clean DOM extraction principles.
Governed by ARIA's Action Gateway: read-only navigation is pre-authorized; mutations
and submissions require approval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.gateway import gateway
from src.gateway.service import register_executor
from src.models import AuditEvent

logger = logging.getLogger(__name__)

BROWSER_ACTION_TYPE = "browser.action"


@dataclass
class BrowserResult:
    """Result from a browser execution."""

    success: bool
    url: str
    title: str = ""
    content: str = ""
    screenshot_base64: str | None = None
    error: str | None = None


class BrowserService:
    """Headless browser automation controller."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        try:
            from playwright.async_api import async_playwright
            if self._playwright is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
            return self._browser
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. To enable browser automation, run: "
                "pip install playwright && playwright install chromium"
            )

    async def navigate_and_extract(self, url: str, timeout_ms: int = 30000) -> BrowserResult:
        """Load a URL, wait for network idle, and extract title and clean markdown/text."""
        try:
            browser = await self._ensure_browser()
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                title = await page.title()
                # Clean extraction: remove script and style tags
                content = await page.evaluate(
                    """() => {
                        const clone = document.body.cloneNode(true);
                        const elementsToRemove = clone.querySelectorAll('script, style, noscript, svg');
                        elementsToRemove.forEach(el => el.remove());
                        return clone.innerText.replace(/\\n{3,}/g, '\\n\\n').trim();
                    }"""
                )
                return BrowserResult(success=True, url=url, title=title, content=content)
            finally:
                await page.close()
        except Exception as exc:
            logger.warning("Browser navigation error for %s: %s", url, exc)
            return BrowserResult(success=False, url=url, error=str(exc))

    async def take_screenshot(self, url: str, timeout_ms: int = 30000) -> BrowserResult:
        """Navigate to URL and capture a base64 screenshot."""
        import base64
        try:
            browser = await self._ensure_browser()
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                title = await page.title()
                shot_bytes = await page.screenshot(type="png", full_page=False)
                shot_b64 = base64.b64encode(shot_bytes).decode("utf-8")
                return BrowserResult(
                    success=True,
                    url=url,
                    title=title,
                    screenshot_base64=shot_b64,
                )
            finally:
                await page.close()
        except Exception as exc:
            return BrowserResult(success=False, url=url, error=str(exc))

    async def execute_action(
        self,
        action: str,
        params: dict[str, Any],
        session: AsyncSession | None = None,
        origin: str = "aria_core",
    ) -> BrowserResult:
        """Execute a browser action governed by the Action Gateway."""
        url = params.get("url", "")
        if not url:
            return BrowserResult(success=False, url="", error="Missing 'url' parameter")

        # Action Gateway Audit
        if session is not None:
            action_req = await gateway.submit(
                session,
                agent="browser",
                action_type=BROWSER_ACTION_TYPE,
                summary=f"Browser action '{action}' on {url}",
                payload={
                    "action": action,
                    "params": params,
                    "origin": origin,
                },
            )
            # Read actions are approved; form submissions remain supervised
            if action in ("navigate", "screenshot", "extract"):
                await gateway.approve(session, action_req.id)
                session.add(
                    AuditEvent(
                        action_request_id=action_req.id,
                        event="browser_executing",
                        detail=f"Executing read action '{action}' on {url}",
                    )
                )
                await session.commit()

        if action in ("navigate", "extract"):
            result = await self.navigate_and_extract(url)
        elif action == "screenshot":
            result = await self.take_screenshot(url)
        else:
            result = BrowserResult(
                success=False, url=url, error=f"Unsupported browser action '{action}'"
            )

        if session is not None and "action_req" in locals():
            session.add(
                AuditEvent(
                    action_request_id=action_req.id,
                    event="browser_executed",
                    detail=f"Success={result.success}, Title='{result.title[:60]}'",
                )
            )
            await session.commit()

        return result

    async def shutdown(self) -> None:
        """Close browser instance."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Singleton instance
_browser_service: BrowserService | None = None


def get_browser_service() -> BrowserService:
    global _browser_service
    if _browser_service is None:
        _browser_service = BrowserService()
    return _browser_service


@register_executor(BROWSER_ACTION_TYPE)
async def execute_browser_action(payload: dict[str, Any]) -> str:
    """Action Gateway executor for browser actions."""
    action = payload["action"]
    params = payload.get("params", {})
    service = get_browser_service()
    result = await service.execute_action(action, params)
    if not result.success:
        raise RuntimeError(f"Browser action failed: {result.error}")
    return f"Browser {action} completed on {result.url}: {result.title}"
