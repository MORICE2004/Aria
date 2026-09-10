"""Tests for continuous chat learning, few-shot exemplars, audio ingestion, and n8n webhooks."""

from __future__ import annotations

import base64
from typing import AsyncIterator
import pytest
from fastapi.testclient import TestClient

from src.communication.learning import (
    DialogueExemplar,
    extract_chat_insights,
    get_relevant_exemplars,
)
from src.db import get_session
from src.llm.base import LLMProvider
from src.llm.router import Routed, Tier
from src.models import Contact, MessageDraft, WhatsAppMessage


@pytest.mark.asyncio
async def test_get_relevant_exemplars(client: TestClient) -> None:
    session_maker = client.session_maker
    async with session_maker() as session:
        contact = Contact(name="Amani", handle="254700112233@s.whatsapp.net", relationship="friend")
        session.add(contact)
        await session.commit()

        # 1. Approved MessageDraft
        draft = MessageDraft(
            contact_id=contact.id,
            incoming="Mambo vipi bro?",
            draft="Poa sana, mzima?",
            final="Poa sana bro, mzima? Niambie",
            status="approved",
        )
        session.add(draft)

        # 2. Sequential WhatsApp messages (in -> out)
        msg_in = WhatsAppMessage(
            contact_id=contact.id,
            direction="in",
            body="Uko wapi sasa hivi?",
        )
        msg_out = WhatsAppMessage(
            contact_id=contact.id,
            direction="out",
            body="Niko home napumzika",
        )
        session.add(msg_in)
        session.add(msg_out)
        await session.commit()

        # Retrieve exemplars for greeting
        exemplars = await get_relevant_exemplars(session, "Mambo vipi", contact=contact, limit=4)
        assert len(exemplars) >= 1
        bodies = [e.reply for e in exemplars]
        assert any("Poa sana" in b for b in bodies)


@pytest.mark.asyncio
async def test_extract_chat_insights(client: TestClient) -> None:
    class MockInsightLLM(LLMProvider):
        async def stream_chat(self, messages, system) -> AsyncIterator[str]:
            yield (
                '{"style_habits": ["uses Sheng phrase \'poa sana\' frequently"],'
                ' "facts": ["working together on mobile app"]}'
            )

    class MockInsightRouter:
        def resolve(self, task, session=None):
            return Routed(provider=MockInsightLLM(), tier=Tier.LOCAL_FAST, model="mock")

    session_maker = client.session_maker
    async with session_maker() as session:
        contact = Contact(name="Baraka", handle="254711998877@s.whatsapp.net", relationship="colleague")
        session.add(contact)
        await session.commit()

        messages = [
            WhatsAppMessage(contact_id=contact.id, direction="in", body="Niaje Baraka"),
            WhatsAppMessage(contact_id=contact.id, direction="out", body="Poa sana, vipi kazi?"),
        ]
        session.add_all(messages)
        await session.commit()

        insights = await extract_chat_insights(session, MockInsightRouter(), contact, messages)
        assert any("Style:" in i for i in insights)
        assert any("Fact:" in i for i in insights)


def test_n8n_inbound_webhook(client: TestClient) -> None:
    # 1. Status query
    status_res = client.post("/webhooks/n8n", json={"action": "status", "data": {}})
    assert status_res.status_code == 200
    assert status_res.json()["ok"] is True
    assert "mode" in status_res.json()["result"]

    # 2. Ingest knowledge
    ingest_res = client.post(
        "/webhooks/n8n",
        json={
            "action": "ingest",
            "data": {
                "title": "n8n AI Project Brief",
                "content": "Aria integrates with n8n self-hosted AI workflows.",
                "kind": "document",
            },
        },
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["ok"] is True
    assert "item_id" in ingest_res.json()["result"]

    # 3. Query memory
    query_res = client.post(
        "/webhooks/n8n",
        json={"action": "query_memory", "data": {"query": "n8n AI workflows"}},
    )
    assert query_res.status_code == 200
    assert query_res.json()["ok"] is True


def test_audio_voice_note_ingest(client: TestClient, ingest_secret: str) -> None:
    fake_audio_base64 = base64.b64encode(b"OggS fake opus audio content").decode("utf-8")
    res = client.post(
        "/whatsapp/ingest",
        json={
            "handle": "254700000000@s.whatsapp.net",
            "name": "AudioSender",
            "body": "",
            "audio_base64": fake_audio_base64,
            "mimetype": "audio/ogg",
        },
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    )
    assert res.status_code == 202
    assert res.json()["queued"] is True
