"""WhatsApp Cloud API (Meta): webhook verification, signature check, inbound parsing and sending.

WhatsApp only allows free-form messages within 24 hours of the person's last message. Outside that window
(e.g. a 07:00 morning brief), a pre-approved template must be used. Create a "Utility" template named as
in WHATSAPP_TEMPLATE_NAME (default: alfred_notice) with a body of just "{{1}}".
"""
from __future__ import annotations

import hashlib
import hmac

import httpx

GRAPH = "https://graph.facebook.com/v21.0"
REENGAGEMENT_ERRORS = {131047, 131026}  # outside the 24-hour window / undeliverable as free text
MAX_LEN = 4000


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not (app_secret and header and header.startswith("sha256=")):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def parse_inbound(payload: dict) -> list[dict]:
    """Returns [{'from': '316…', 'text': '…', 'id': 'wamid…'}] for text (and button) messages."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []) or []:
                text = None
                if msg.get("type") == "text":
                    text = msg["text"]["body"]
                elif msg.get("type") == "button":
                    text = msg["button"].get("text")
                elif msg.get("type") == "interactive":
                    inter = msg["interactive"]
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title")
                if text:
                    out.append({"from": msg["from"], "text": text, "id": msg.get("id")})
    return out


class WhatsApp:
    def __init__(self, secrets: dict, http=None):
        self.token = secrets.get("WHATSAPP_TOKEN")
        self.phone_id = secrets.get("WHATSAPP_PHONE_NUMBER_ID")
        self.template = secrets.get("WHATSAPP_TEMPLATE_NAME", "alfred_notice")
        self.http = http or httpx.Client(timeout=20)

    @property
    def configured(self) -> bool:
        return bool(self.token and self.phone_id)

    def _post(self, body: dict) -> httpx.Response:
        return self.http.post(f"{GRAPH}/{self.phone_id}/messages", json=body,
                              headers={"Authorization": f"Bearer {self.token}"})

    def send(self, to: str, text: str) -> None:
        text = text[:MAX_LEN]
        r = self._post({"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text",
                        "text": {"body": text, "preview_url": True}})
        if r.status_code >= 400:
            code = (r.json().get("error") or {}).get("code") if r.headers.get("content-type", "").startswith(
                "application/json") else None
            if code in REENGAGEMENT_ERRORS or r.status_code == 400:
                r = self._post({"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "template",
                                "template": {"name": self.template, "language": {"code": "en_GB"},
                                             "components": [{"type": "body", "parameters": [
                                                 {"type": "text", "text": text[:1000]}]}]}})
        r.raise_for_status()

    def mark_read(self, message_id: str) -> None:
        self._post({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
