"""Browser endpoints: navigate, extract content, capture screenshots."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from src.browser import get_browser_service
from src.db import get_session

router = APIRouter(prefix="/browser", tags=["browser"])


class NavigateIn(BaseModel):
    url: str
    timeout_ms: int = 30000


class NavigateOut(BaseModel):
    success: bool
    url: str
    title: str = ""
    content: str = ""
    error: str | None = None


class ScreenshotOut(BaseModel):
    success: bool
    url: str
    title: str = ""
    screenshot_base64: str | None = None
    error: str | None = None


@router.get("/status")
async def browser_status():
    """Check browser automation availability."""
    try:
        import importlib.metadata
        import playwright
        version = importlib.metadata.version("playwright")
        return {"available": True, "provider": "playwright", "version": version}
    except (ImportError, Exception):
        return {
            "available": False,
            "provider": "playwright",
            "install_guide": "pip install playwright && playwright install chromium",
        }


@router.post("/navigate", response_model=NavigateOut)
async def navigate(body: NavigateIn, session: AsyncSession = Depends(get_session)):
    """Navigate to a web page and extract clean structured text/DOM under Action Gateway audit."""
    service = get_browser_service()
    res = await service.execute_action(
        action="navigate",
        params={"url": body.url, "timeout_ms": body.timeout_ms},
        session=session,
        origin="api",
    )
    return NavigateOut(
        success=res.success,
        url=res.url,
        title=res.title,
        content=res.content,
        error=res.error,
    )


@router.post("/screenshot", response_model=ScreenshotOut)
async def screenshot(body: NavigateIn, session: AsyncSession = Depends(get_session)):
    """Capture a screenshot of a web page under Action Gateway audit."""
    service = get_browser_service()
    res = await service.execute_action(
        action="screenshot",
        params={"url": body.url, "timeout_ms": body.timeout_ms},
        session=session,
        origin="api",
    )
    return ScreenshotOut(
        success=res.success,
        url=res.url,
        title=res.title,
        screenshot_base64=res.screenshot_base64,
        error=res.error,
    )
