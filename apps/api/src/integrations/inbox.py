"""Incoming email via IMAP — READ-ONLY.

Lets ARIA report who emailed and feed messages into the drafting flow.
Deliberately read-only: fetching never marks messages as read (BODY.PEEK),
never deletes, never moves. Replying still goes out through the gateway.

Setup (Gmail): set IMAP_HOST=imap.gmail.com in .env; login reuses
SMTP_USER + SMTP_PASSWORD (the same App Password works for IMAP).
"""

import asyncio
import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header

from src.core.config import get_settings

MAX_SNIPPET = 300


@dataclass(frozen=True)
class InboxMessage:
    sender: str
    subject: str
    date: str
    snippet: str


def _decode(value: str | None) -> str:
    """Email headers can arrive MIME-encoded (=?utf-8?...?=); decode them."""
    if not value:
        return ""
    parts = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def _snippet(message: email.message.Message) -> str:
    """First chunk of the plain-text body, for the notification preview."""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )[:MAX_SNIPPET].strip()
        return ""
    payload = message.get_payload(decode=True)
    if not payload:
        return ""
    return payload.decode(
        message.get_content_charset() or "utf-8", errors="replace"
    )[:MAX_SNIPPET].strip()


def _fetch_unread_sync(limit: int) -> list[InboxMessage]:
    settings = get_settings()
    if not (settings.imap_host and settings.smtp_user and settings.smtp_password):
        raise RuntimeError(
            "IMAP is not configured. Set IMAP_HOST (plus SMTP_USER and "
            "SMTP_PASSWORD) in .env — for Gmail: imap.gmail.com + an App Password."
        )

    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as imap:
        imap.login(settings.smtp_user, settings.smtp_password)
        imap.select("INBOX", readonly=True)  # readonly: we never change state
        _, data = imap.search(None, "UNSEEN")
        ids = data[0].split()
        messages: list[InboxMessage] = []
        for msg_id in reversed(ids[-limit:]):  # newest first
            # BODY.PEEK keeps the message marked unread.
            _, parts = imap.fetch(msg_id, "(BODY.PEEK[])")
            raw = parts[0][1] if parts and parts[0] else None
            if not isinstance(raw, bytes):
                continue
            parsed = email.message_from_bytes(raw)
            messages.append(
                InboxMessage(
                    sender=_decode(parsed.get("From")),
                    subject=_decode(parsed.get("Subject")) or "(no subject)",
                    date=parsed.get("Date") or "",
                    snippet=_snippet(parsed),
                )
            )
        return messages


async def fetch_unread(limit: int = 10) -> list[InboxMessage]:
    """Async wrapper — imaplib is blocking, so it runs in a worker thread."""
    return await asyncio.to_thread(_fetch_unread_sync, limit)
