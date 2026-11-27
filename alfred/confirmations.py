"""Handles 'yes 3' / 'no' replies in code, so the model never executes a write on its own."""
from __future__ import annotations

from alfred.guards import parse_confirmation


def handle_confirmation(text: str, member_id: str, cfg, store, google) -> str | None:
    """Returns Alfred's reply if the message was a yes/no to a pending proposal, else None."""
    parsed = parse_confirmation(text)
    if not parsed:
        return None
    pending = store.pending_proposals()
    if not pending:
        return None  # a plain "yes" with nothing pending is ordinary chat
    member = cfg.member(member_id)
    if not member.is_adult:
        return f"Thank you, {member.address_as}. I'll wait for a grown-up to confirm that one."

    verdict, target = parsed
    if target == "all":
        chosen = pending
    elif target:
        chosen = [p for p in pending if str(p["id"]) == target]
        if not chosen:
            return f"I'm afraid I have no open proposal number {target}, {member.address_as}."
    elif len(pending) == 1:
        chosen = pending
    else:
        listing = "\n".join(f"{p['id']}. {p['summary']}" for p in pending)
        return f"Which one, {member.address_as}? Reply 'yes <number>' or 'yes all':\n{listing}"

    lines = []
    for p in chosen:
        if verdict == "no":
            store.decide_proposal(p["id"], "declined", member_id)
            lines.append(f"Very good, I've set aside: {p['summary']}.")
            continue
        if p["kind"] != "family_calendar_event":
            store.decide_proposal(p["id"], "unsupported", member_id)
            continue
        if google is None:
            lines.append(f"I'm afraid the Family calendar is not connected yet, so I couldn't add: {p['summary']}.")
            continue
        try:
            google.create_family_event(cfg.family_calendar_id, p["payload"])
            store.decide_proposal(p["id"], "done", member_id)
            store.audit(member_id, "family_calendar:add", p["summary"])
            lines.append(f"Done — on the Family calendar: {p['summary']}.")
        except Exception as exc:
            store.audit(member_id, "family_calendar:add", f"{p['summary']}: {exc}", ok=False)
            lines.append(f"I'm sorry, the calendar wouldn't take it just now ({type(exc).__name__}): {p['summary']}.")
    return "\n".join(lines) if lines else None
