"""iCloud Mail over IMAP (opened read-only with EXAMINE, bodies fetched with BODY.PEEK so nothing is
marked as read) and iCloud Calendar over CalDAV (read-only). Uses app-specific passwords."""
from __future__ import annotations

import email
import imaplib
from datetime import date, datetime
from email.header import decode_header, make_header

from alfred.integrations.google import html_to_text

IMAP_HOST = "imap.mail.me.com"
CALDAV_URL = "https://caldav.icloud.com"


def _hdr(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def message_text(msg: email.message.Message) -> str:
    plain, htmlpart = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        (plain if part.get_content_type() == "text/plain" else htmlpart).append(text)
    return "\n".join(plain) if plain else html_to_text("\n".join(htmlpart))


class ICloudIntegration:
    def __init__(self, cfg):
        self.cfg = cfg

    def _login(self, member_id: str) -> tuple[str, str]:
        member = self.cfg.member(member_id)
        password = self.cfg.secrets.get(f"ICLOUD_PASSWORD_{member_id.upper()}")
        if not (member.icloud_username and password):
            raise RuntimeError(f"iCloud is not configured for {member_id}.")
        return member.icloud_username, password

    # ---- mail ------------------------------------------------------------------
    def _imap(self, member_id: str) -> imaplib.IMAP4_SSL:
        user, password = self._login(member_id)
        conn = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        conn.login(user, password)
        conn.select("INBOX", readonly=True)  # EXAMINE: read-only, cannot change or delete anything
        return conn

    def search_mail(self, member_id: str, since: date, text: str | None = None, max_results: int = 10) -> list[dict]:
        conn = self._imap(member_id)
        try:
            criteria = ["SINCE", since.strftime("%d-%b-%Y")]
            if text:
                criteria += ["TEXT", f'"{text}"']
            _, data = conn.uid("SEARCH", None, *criteria)
            uids = data[0].split()[-max_results:]
            out = []
            for uid in reversed(uids):
                _, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                msg = email.message_from_bytes(msg_data[0][1])
                out.append({"id": uid.decode(), "from": _hdr(msg["From"]), "subject": _hdr(msg["Subject"]),
                            "date": msg["Date"]})
            return out
        finally:
            conn.logout()

    def read_mail(self, member_id: str, uid: str, max_chars: int = 8000) -> dict:
        conn = self._imap(member_id)
        try:
            _, msg_data = conn.uid("FETCH", uid.encode(), "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            body = message_text(msg)
            return {"from": _hdr(msg["From"]), "subject": _hdr(msg["Subject"]), "date": msg["Date"],
                    "body": body[:max_chars], "truncated": len(body) > max_chars}
        finally:
            conn.logout()

    # ---- calendar --------------------------------------------------------------
    def list_events(self, member_id: str, start: datetime, end: datetime) -> list[dict]:
        import caldav

        user, password = self._login(member_id)
        client = caldav.DAVClient(url=CALDAV_URL, username=user, password=password)
        out = []
        for cal in client.principal().calendars():
            for ev in cal.search(start=start, end=end, event=True, expand=True):
                comp = ev.icalendar_component
                s, e = comp.get("dtstart"), comp.get("dtend")
                sv = s.dt if s else None
                out.append({
                    "title": str(comp.get("summary", "(no title)")),
                    "start": sv.isoformat() if sv else None,
                    "end": e.dt.isoformat() if e else None,
                    "all_day": isinstance(sv, date) and not isinstance(sv, datetime),
                    "location": str(comp.get("location")) if comp.get("location") else None,
                    "calendar": cal.name,
                    "owner": member_id,
                })
        return out
