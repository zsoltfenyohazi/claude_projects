"""Optional SMS via Twilio, used as a fallback for urgent alerts."""
from __future__ import annotations

import httpx


class TwilioSMS:
    def __init__(self, secrets: dict, http=None):
        self.sid = secrets.get("TWILIO_ACCOUNT_SID")
        self.token = secrets.get("TWILIO_AUTH_TOKEN")
        self.sender = secrets.get("TWILIO_FROM_NUMBER")
        self.http = http or httpx.Client(timeout=20)

    @property
    def configured(self) -> bool:
        return bool(self.sid and self.token and self.sender)

    def send(self, to: str, text: str) -> None:
        r = self.http.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                           auth=(self.sid, self.token),
                           data={"From": self.sender, "To": "+" + to.lstrip("+"), "Body": text[:1500]})
        r.raise_for_status()
