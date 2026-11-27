"""Loads the family configuration (YAML) and secrets (environment variables)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


@dataclass
class Member:
    id: str
    name: str
    address_as: str = "sir"          # how Alfred addresses them: sir / madam / Master Tom ...
    whatsapp: str | None = None      # E.164 without '+', e.g. 31612345678
    email: str | None = None         # where Alfred may write to them (from his own mailbox)
    sms: str | None = None
    preferred_channel: str = "whatsapp"
    is_adult: bool = True
    work_location: str | None = None
    gmail: bool = False
    google_calendar: bool = False
    icloud_mail: bool = False
    icloud_calendar: bool = False
    icloud_username: str | None = None
    share_mail_with_family: bool = False   # private by default
    family_calendar_writer: bool = False   # whose Google token is used to write the Family calendar


@dataclass
class Location:
    key: str
    label: str
    lat: float
    lon: float


@dataclass
class Shop:
    name: str
    url: str
    kind: str = "groceries"


@dataclass
class Config:
    timezone: ZoneInfo
    members: list[Member]
    children: list[dict]
    locations: dict[str, Location]
    family_calendar_id: str | None
    quiet_start: str
    quiet_end: str
    shops: list[Shop]
    schedule: dict
    ns_stations: list[str]
    meteoalarm_regions: list[str]
    data_dir: Path
    dry_run: bool
    model: str = "claude-opus-5-5"
    secrets: dict = field(default_factory=dict)

    def member(self, member_id: str) -> Member:
        for m in self.members:
            if m.id == member_id:
                return m
        raise KeyError(member_id)

    def member_by_whatsapp(self, number: str) -> Member | None:
        number = number.lstrip("+")
        return next((m for m in self.members if m.whatsapp and m.whatsapp.lstrip("+") == number), None)

    def member_by_email(self, address: str) -> Member | None:
        address = address.strip().lower()
        return next((m for m in self.members if m.email and m.email.lower() == address), None)

    @property
    def adults(self) -> list[Member]:
        return [m for m in self.members if m.is_adult]


SECRET_KEYS = [
    "ANTHROPIC_API_KEY",
    "WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET",
    "WHATSAPP_TEMPLATE_NAME",
    "ALFRED_SMTP_HOST", "ALFRED_SMTP_PORT", "ALFRED_SMTP_USER", "ALFRED_SMTP_PASSWORD", "ALFRED_FROM_EMAIL",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
    "NS_API_KEY",
]


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.environ.get("ALFRED_CONFIG", "config/family.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    members = [Member(**m) for m in raw["family"]["members"]]
    locations = {k: Location(key=k, **v) for k, v in raw["locations"].items()}
    shops = [Shop(**s) for s in raw.get("shops", [])]
    data_dir = Path(os.environ.get("ALFRED_DATA_DIR", raw.get("data_dir", "data")))
    data_dir.mkdir(parents=True, exist_ok=True)

    secrets = {k: os.environ[k] for k in SECRET_KEYS if os.environ.get(k)}
    for m in members:  # iCloud app-specific passwords: ICLOUD_PASSWORD_<MEMBERID>
        key = f"ICLOUD_PASSWORD_{m.id.upper()}"
        if os.environ.get(key):
            secrets[key] = os.environ[key]

    return Config(
        timezone=ZoneInfo(raw["family"].get("timezone", "Europe/Amsterdam")),
        members=members,
        children=raw["family"].get("children", []),
        locations=locations,
        family_calendar_id=raw.get("family_calendar_id"),
        quiet_start=raw.get("quiet_hours", {}).get("start", "22:00"),
        quiet_end=raw.get("quiet_hours", {}).get("end", "07:00"),
        shops=shops,
        schedule=raw.get("schedule", {}),
        ns_stations=raw.get("ns_stations", []),
        meteoalarm_regions=raw.get("meteoalarm_regions", ["Noord-Brabant"]),
        data_dir=data_dir,
        dry_run=os.environ.get("ALFRED_DRY_RUN", "0") == "1",
        model=os.environ.get("ALFRED_MODEL", raw.get("model", "claude-opus-5-5")),
        secrets=secrets,
    )
