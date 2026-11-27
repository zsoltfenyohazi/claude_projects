"""Wires everything together."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from alfred.agent import Alfred
from alfred.channels.email_out import AlfredMail
from alfred.channels.notifier import Notifier
from alfred.channels.sms import TwilioSMS
from alfred.channels.whatsapp import WhatsApp
from alfred.config import Config, load_config
from alfred.confirmations import handle_confirmation
from alfred.jobs.routines import Routines
from alfred.store import Store
from alfred.tools import build_registry

log = logging.getLogger(__name__)


@dataclass
class App:
    cfg: Config
    store: Store
    alfred: Alfred
    notifier: Notifier
    routines: Routines
    google: object | None
    whatsapp: WhatsApp

    def handle_message(self, member_id: str, text: str, channel: str = "WhatsApp") -> str:
        reply = handle_confirmation(text, member_id, self.cfg, self.store, self.google)
        if reply is not None:
            self.store.add_history(member_id, "user", text)
            self.store.add_history(member_id, "assistant", reply)
            return reply
        return self.alfred.chat(member_id, text, channel=channel)


def build_app(config_path: str | None = None, client=None) -> App:
    cfg = load_config(config_path)
    store = Store(cfg.data_dir / "alfred.sqlite3")

    google = icloud = None
    if any(m.gmail or m.google_calendar or m.family_calendar_writer for m in cfg.members):
        from alfred.integrations.google import GoogleIntegration
        google = GoogleIntegration(cfg)
    if any(m.icloud_mail or m.icloud_calendar for m in cfg.members):
        from alfred.integrations.icloud import ICloudIntegration
        icloud = ICloudIntegration(cfg)

    registry = build_registry(cfg, store, google=google, icloud=icloud)
    alfred = Alfred(cfg, store, registry, client=client)
    whatsapp = WhatsApp(cfg.secrets)
    notifier = Notifier(cfg, store, whatsapp=whatsapp, mail=AlfredMail(cfg.secrets), sms=TwilioSMS(cfg.secrets))
    routines = Routines(cfg, store, alfred, notifier)
    return App(cfg, store, alfred, notifier, routines, google, whatsapp)
