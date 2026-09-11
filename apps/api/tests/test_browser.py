"""Tests for ARIA Browser Automation subsystem."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.browser.service import BrowserResult, BrowserService, get_browser_service


def test_browser_status_endpoint(client):
    res = client.get("/browser/status")
    assert res.status_code == 200
    data = res.json()
    assert "available" in data
    assert data["provider"] == "playwright"


@pytest.mark.asyncio
async def test_browser_service_mocked():
    service = BrowserService()

    # Test navigate mock
    mock_result = BrowserResult(
        success=True,
        url="https://example.com",
        title="Example Domain",
        content="This domain is for use in illustrative examples.",
    )

    with patch.object(service, "navigate_and_extract", AsyncMock(return_value=mock_result)):
        res = await service.execute_action("navigate", {"url": "https://example.com"})
        assert res.success
        assert res.title == "Example Domain"
        assert "illustrative examples" in res.content


def test_browser_api_endpoints(client):
    mock_res = BrowserResult(
        success=True,
        url="https://example.com",
        title="Example Domain",
        content="Clean extracted content",
    )

    with patch("src.routers.browser.get_browser_service") as mock_get:
        mock_svc = MagicMock()
        mock_svc.execute_action = AsyncMock(return_value=mock_res)
        mock_get.return_value = mock_svc

        # POST /browser/navigate
        res = client.post("/browser/navigate", json={"url": "https://example.com"})
        assert res.status_code == 200
        assert res.json()["title"] == "Example Domain"
        assert res.json()["content"] == "Clean extracted content"

        # POST /browser/screenshot
        shot_res = BrowserResult(
            success=True,
            url="https://example.com",
            title="Example Domain",
            screenshot_base64="dGVzdA==",
        )
        mock_svc.execute_action = AsyncMock(return_value=shot_res)
        res_shot = client.post("/browser/screenshot", json={"url": "https://example.com"})
        assert res_shot.status_code == 200
        assert res_shot.json()["screenshot_base64"] == "dGVzdA=="
