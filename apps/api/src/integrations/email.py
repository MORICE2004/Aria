"""Outgoing email via SMTP — an Action Gateway executor.

This function is registered as the "email.send" executor, which means it is
reachable from EXACTLY ONE place: the gateway's approve path. No agent can
call it directly; an email exists only as a pending draft until approved.

Setup (Gmail): in .env set
  SMTP_HOST=smtp.gmail.com  SMTP_PORT=587
  SMTP_USER=you@gmail.com   SMTP_PASSWORD=<App Password>
App Passwords: Google account -> Security -> 2-Step Verification -> App passwords.
"""

import asyncio
import smtplib
from email.message import EmailMessage

from src.core.config import get_settings
from src.gateway import register_executor


@register_executor("email.send")
async def send_email(payload: dict) -> str:
    settings = get_settings()
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST, SMTP_USER and SMTP_PASSWORD "
            "in .env (see .env.example)."
        )

    message = EmailMessage()
    message["From"] = settings.smtp_user
    message["To"] = payload["to"]
    message["Subject"] = payload["subject"]
    message.set_content(payload["body"])

    def _send() -> None:
        # STARTTLS upgrades the connection to encrypted before credentials
        # are sent — never authenticate over plain SMTP.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)

    # smtplib is blocking; run it in a worker thread so the API stays responsive.
    await asyncio.to_thread(_send)
    return f"Email sent to {payload['to']}: {payload['subject']!r}"
