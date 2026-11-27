"""Routes Alfred's messages to family members: allowlist, quiet hours, channel fallback, dry-run."""
from __future__ import annotations

import logging
from datetime import datetime

from alfred.guards import check_recipient, may_send_now

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg, store, whatsapp=None, mail=None, sms=None):
        self.cfg, self.store = cfg, store
        self.whatsapp, self.mail, self.sms = whatsapp, mail, sms
        self.sent: list[tuple[str, str, str]] = []  # (member_id, channel, text) for dry-run and tests

    def _allowed(self) -> set[str]:
        return {a for m in self.cfg.members for a in (m.whatsapp, m.email, m.sms) if a}

    def send(self, member_id: str, text: str, *, subject: str = "A note from Alfred", urgent: bool = False,
             channel: str | None = None) -> bool:
        member = self.cfg.member(member_id)
        now = datetime.now(self.cfg.timezone)
        if not may_send_now(now, self.cfg.quiet_start, self.cfg.quiet_end, urgent):
            self.store.audit("system", "notify:held", f"quiet hours, to {member_id}")
            return False

        order = [channel or member.preferred_channel] + ["whatsapp", "email", "sms"]
        for ch in dict.fromkeys(order):
            address = {"whatsapp": member.whatsapp, "email": member.email, "sms": member.sms}.get(ch)
            transport = {"whatsapp": self.whatsapp, "email": self.mail, "sms": self.sms}.get(ch)
            if not address or (ch == "sms" and not urgent):  # SMS is for urgent alerts only
                continue
            check_recipient(address, self._allowed())
            if self.cfg.dry_run or transport is None or not transport.configured:
                if self.cfg.dry_run:
                    print(f"\n--- [DRY RUN] {ch} to {member.name} ---\n{text}\n")
                    self.sent.append((member_id, ch, text))
                    return True
                continue
            try:
                if ch == "email":
                    transport.send(address, subject, text)
                else:
                    transport.send(address, text)
                self.sent.append((member_id, ch, text))
                self.store.audit("system", f"notify:{ch}", f"to {member_id}: {text[:200]}")
                return True
            except Exception as exc:
                log.warning("sending via %s to %s failed: %s", ch, member_id, exc)
                self.store.audit("system", f"notify:{ch}", f"failed to {member_id}: {exc}", ok=False)
        return False

    def broadcast(self, text: str, *, adults_only: bool = True, **kw) -> None:
        for m in (self.cfg.adults if adults_only else self.cfg.members):
            self.send(m.id, text, **kw)
