"""Unit tests for web search integration in ARIA's Research Agent."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.core.config import Settings
from src.research.agent import ResearchAgent, get_research_agent
from src.research.sources import WebSearchSource, SourceResult


@pytest.mark.asyncio
async def test_web_search_duckduckgo_parses_abstract_and_topics() -> None:
    source = WebSearchSource(provider="duckduckgo")

    mock_resp = {
        "AbstractText": "Python is a versatile high-level programming language.",
        "AbstractSource": "Wikipedia",
        "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "RelatedTopics": [
            {
                "Text": "Django - A high-level Python web framework.",
                "FirstURL": "https://duckduckgo.com/Django",
            },
            {
                "Topics": [
                    {
                        "Text": "FastAPI - Modern web framework for Python.",
                        "FirstURL": "https://fastapi.tiangolo.com/",
                    }
                ]
            },
        ],
    }

    from unittest.mock import MagicMock

    mock_resp_obj = MagicMock()
    mock_resp_obj.status_code = 200
    mock_resp_obj.json.return_value = mock_resp

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp_obj
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await source.search(None, "Python programming", limit=5)

    assert len(results) == 3
    assert results[0].source == "web"
    assert "Python is a versatile" in results[0].content
    assert "Wikipedia" in results[0].citation
    assert results[0].score == 0.9

    assert any("Django" in r.content for r in results)
    assert any("FastAPI" in r.content for r in results)


@pytest.mark.asyncio
async def test_web_search_degrades_gracefully_on_network_failure() -> None:
    source = WebSearchSource(provider="duckduckgo")

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection timeout")
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await source.search(None, "quantum computing", limit=5)

    # Must return empty list instead of crashing
    assert results == []


@pytest.mark.asyncio
async def test_web_search_tavily_parses_results() -> None:
    source = WebSearchSource(provider="tavily", api_key="test-key")

    mock_resp = {
        "results": [
            {
                "title": "Autonomous Agents Guide",
                "url": "https://example.com/agents",
                "content": "AI agents execute multi-step workflows autonomously.",
                "score": 0.95,
            }
        ]
    }

    from unittest.mock import MagicMock

    mock_resp_obj = MagicMock()
    mock_resp_obj.status_code = 200
    mock_resp_obj.json.return_value = mock_resp

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp_obj
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await source.search(None, "autonomous agents", limit=5)

    assert len(results) == 1
    assert results[0].source == "web"
    assert "Autonomous Agents Guide" in results[0].citation
    assert results[0].score == 0.95


def test_research_agent_scope_note_reflects_web_capability() -> None:
    agent_without_web = ResearchAgent([])
    assert "no web access" in agent_without_web.scope_note

    web_source = WebSearchSource()
    agent_with_web = ResearchAgent([web_source])
    assert "live web search" in agent_with_web.scope_note


def test_get_research_agent_toggles_with_settings() -> None:
    mock_memory = AsyncMock()

    settings_off = Settings(web_search_enabled=False)
    agent_off = get_research_agent(mock_memory, settings=settings_off)
    assert not any(s.name == "web" for s in agent_off._sources)

    settings_on = Settings(web_search_enabled=True, web_search_provider="duckduckgo")
    agent_on = get_research_agent(mock_memory, settings=settings_on)
    assert any(s.name == "web" for s in agent_on._sources)
