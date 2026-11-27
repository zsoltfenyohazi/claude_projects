"""Gmail (read-only) and Google Calendar (read; write only to the Family calendar).

Tokens are created once per person with:  python -m alfred google-auth <member_id>
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime
from pathlib import Path

from alfred.guards import check_family_calendar

SCOPE_GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_CAL_READ = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_CAL_EVENTS = "https://www.googleapis.com/auth/calendar.events"  # only for the Family calendar writer


def scopes_for(member) -> list[str]:
    scopes = []
    if member.gmail:
        scopes.append(SCOPE_GMAIL_READ)
    if member.google_calendar or member.family_calendar_writer:
        scopes.append(SCOPE_CAL_READ)
    if member.family_calendar_writer:
        scopes.append(SCOPE_CAL_EVENTS)
    return scopes


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


class GoogleIntegration:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token_dir = Path(cfg.data_dir) / "tokens"
        self._services: dict[tuple[str, str], object] = {}

    # ---- auth ------------------------------------------------------------------
    def _creds(self, member_id: str):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        member = self.cfg.member(member_id)
        path = self.token_dir / f"{member_id}_google.json"
        if not path.exists():
            raise RuntimeError(f"No Google token for {member_id}. Run: python -m alfred google-auth {member_id}")
        creds = Credentials.from_authorized_user_file(str(path), scopes_for(member))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json())
        return creds

    def _service(self, member_id: str, api: str):
        from googleapiclient.discovery import build

        key = (member_id, api)
        if key not in self._services:
            version = "v1" if api == "gmail" else "v3"
            self._services[key] = build(api, version, credentials=self._creds(member_id), cache_discovery=False)
        return self._services[key]

    def authorise(self, member_id: str, client_secrets: str = "config/google_client_secret.json") -> Path:
        from google_auth_oauthlib.flow import InstalledAppFlow

        member = self.cfg.member(member_id)
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets, scopes_for(member))
        creds = flow.run_local_server(port=0, open_browser=False)
        self.token_dir.mkdir(parents=True, exist_ok=True)
        path = self.token_dir / f"{member_id}_google.json"
        path.write_text(creds.to_json())
        path.chmod(0o600)
        return path

    # ---- calendar ----------------------------------------------------------------
    @staticmethod
    def _norm_event(e: dict, calendar: str, owner: str) -> dict:
        start, end = e.get("start", {}), e.get("end", {})
        return {
            "title": e.get("summary", "(no title)"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "all_day": "date" in start,
            "location": e.get("location"),
            "calendar": calendar,
            "owner": owner,
        }

    def list_events(self, member_id: str, start: datetime, end: datetime) -> list[dict]:
        svc = self._service(member_id, "calendar")
        out = []
        for cal in svc.calendarList().list().execute().get("items", []):
            if cal.get("id") == self.cfg.family_calendar_id:
                continue  # listed separately
            items = svc.events().list(calendarId=cal["id"], timeMin=start.isoformat(), timeMax=end.isoformat(),
                                      singleEvents=True, orderBy="startTime", maxResults=100).execute()
            out += [self._norm_event(e, cal.get("summary", ""), member_id) for e in items.get("items", [])]
        return out

    def _writer(self) -> str:
        writer = next((m.id for m in self.cfg.members if m.family_calendar_writer), None)
        if not writer:
            raise RuntimeError("No member has family_calendar_writer: true in the config.")
        return writer

    def list_family_events(self, start: datetime, end: datetime) -> list[dict]:
        if not self.cfg.family_calendar_id:
            return []
        svc = self._service(self._writer(), "calendar")
        items = svc.events().list(calendarId=self.cfg.family_calendar_id, timeMin=start.isoformat(),
                                  timeMax=end.isoformat(), singleEvents=True, orderBy="startTime").execute()
        return [self._norm_event(e, "Family", "family") for e in items.get("items", [])]

    def create_family_event(self, calendar_id: str, event: dict) -> str:
        """The only write Alfred can make anywhere. Called by code after a human said yes."""
        check_family_calendar(calendar_id, self.cfg.family_calendar_id)
        tz = str(self.cfg.timezone)
        if event.get("all_day"):
            body_time = {"start": {"date": event["start"][:10]}, "end": {"date": (event.get("end") or event["start"])[:10]}}
        else:
            body_time = {"start": {"dateTime": event["start"], "timeZone": tz},
                         "end": {"dateTime": event.get("end") or event["start"], "timeZone": tz}}
        body = {"summary": event["title"], "location": event.get("location"),
                "description": (event.get("notes") or "") + "\n\nAdded by Alfred with the family's approval.",
                **body_time}
        created = self._service(self._writer(), "calendar").events().insert(
            calendarId=calendar_id, body=body).execute()
        return created.get("htmlLink", "")

    # ---- gmail (read-only) -------------------------------------------------------
    def search_mail(self, member_id: str, query: str, max_results: int = 10) -> list[dict]:
        svc = self._service(member_id, "gmail")
        ids = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        out = []
        for m in ids.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                             metadataHeaders=["From", "Subject", "Date"]).execute()
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            out.append({"id": m["id"], "from": headers.get("from"), "subject": headers.get("subject"),
                        "date": headers.get("date"), "snippet": msg.get("snippet")})
        return out

    def read_mail(self, member_id: str, message_id: str, max_chars: int = 8000) -> dict:
        svc = self._service(member_id, "gmail")
        msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

        plain, htmlpart = [], []

        def walk(part):
            data = part.get("body", {}).get("data")
            if data:
                text = base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
                (plain if part.get("mimeType") == "text/plain" else htmlpart).append(text)
            for p in part.get("parts", []) or []:
                walk(p)

        walk(msg.get("payload", {}))
        body = "\n".join(plain) if plain else html_to_text("\n".join(htmlpart))
        return {"from": headers.get("from"), "subject": headers.get("subject"), "date": headers.get("date"),
                "body": body[:max_chars], "truncated": len(body) > max_chars}
