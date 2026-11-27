"""Calendars: read everyone's agenda; *propose* events for the Family calendar (a human confirms)."""
from __future__ import annotations

from datetime import datetime, timedelta

from alfred.tools import Tool, ToolContext


def register(reg, cfg, store, google=None, icloud=None) -> None:
    def agenda(ctx: ToolContext, a: dict):
        tz = cfg.timezone
        day = datetime.fromisoformat(a["start_date"]).date() if a.get("start_date") else datetime.now(tz).date()
        start = datetime.combine(day, datetime.min.time(), tz)
        end = start + timedelta(days=int(a.get("days", 1)))
        events, problems = [], []
        for m in cfg.members:
            for enabled, source, name in ((m.google_calendar, google, "Google"), (m.icloud_calendar, icloud, "iCloud")):
                if not (enabled and source):
                    continue
                try:
                    events += source.list_events(m.id, start, end)
                except Exception as exc:
                    problems.append(f"{m.name}'s {name} calendar: {type(exc).__name__}")
        if google and cfg.family_calendar_id:
            try:
                events += google.list_family_events(start, end)
            except Exception as exc:
                problems.append(f"Family calendar: {type(exc).__name__}")
        events.sort(key=lambda e: e.get("start") or "")
        return {"from": start.isoformat(), "to": end.isoformat(), "events": events, "unavailable": problems}

    def propose(ctx: ToolContext, a: dict):
        summary = f"{a['title']} — {a['start']}" + (f" at {a['location']}" if a.get("location") else "")
        pid = store.add_proposal("family_calendar_event", a, summary, proposed_to=ctx.requester)
        return {"proposal_number": pid, "status": "awaiting the family's confirmation",
                "instruction": f"Ask the family to reply 'yes {pid}' to add it, or 'no {pid}' to decline. "
                               "Do not claim it has been added."}

    def pending(ctx: ToolContext, a: dict):
        return [{"number": p["id"], "summary": p["summary"]} for p in store.pending_proposals()]

    reg.register(Tool(
        "family_agenda",
        "Everyone's appointments (personal Google/iCloud calendars plus the shared Family calendar) for a "
        "period. start_date is YYYY-MM-DD (default today); days defaults to 1.",
        {"type": "object", "properties": {"start_date": {"type": "string"}, "days": {"type": "integer"}},
         "additionalProperties": False},
        agenda))
    reg.register(Tool(
        "propose_family_calendar_event",
        "Suggest an event for the shared Family calendar. This does NOT add it: it creates a numbered "
        "proposal that a family member must confirm by replying 'yes <number>'. Times are local "
        "ISO 8601, e.g. 2026-12-05T14:00:00.",
        {"type": "object", "properties": {
            "title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
            "all_day": {"type": "boolean"}, "location": {"type": "string"}, "notes": {"type": "string"},
            "reason": {"type": "string", "description": "Why you suggest it, e.g. 'found in an email from the school'."}},
         "required": ["title", "start"], "additionalProperties": False},
        propose, kind="propose"))
    reg.register(Tool(
        "pending_proposals", "List proposals still waiting for the family's yes or no.",
        {"type": "object", "properties": {}, "additionalProperties": False}, pending))
