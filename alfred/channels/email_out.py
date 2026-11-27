"""Email from Alfred's OWN mailbox (e.g. a dedicated alfred.<family>@gmail.com) to family members only.

Alfred never sends from, or on behalf of, the family's personal accounts.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage


class AlfredMail:
    def __init__(self, secrets: dict):
        self.host = secrets.get("ALFRED_SMTP_HOST")
        self.port = int(secrets.get("ALFRED_SMTP_PORT", 587))
        self.user = secrets.get("ALFRED_SMTP_USER")
        self.password = secrets.get("ALFRED_SMTP_PASSWORD")
        self.sender = secrets.get("ALFRED_FROM_EMAIL", self.user)

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = f"Alfred <{self.sender}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
