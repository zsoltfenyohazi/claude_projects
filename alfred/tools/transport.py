"""Commute: NS train disruptions and maintenance on the family's routes (needs a free NS API key)."""
from __future__ import annotations

import httpx

from alfred.tools import Tool, ToolContext

NS_DISRUPTIONS = "https://gateway.apiportal.ns.nl/disruptions/v3"


def parse_ns(items: list[dict], stations: list[str]) -> list[dict]:
    wanted = [s.lower() for s in stations]
    out = []
    for d in items:
        text = " ".join([d.get("title", ""), str(d.get("timespans", "")), str(d.get("publicationSections", ""))])
        if wanted and not any(s in text.lower() for s in wanted):
            continue
        out.append({
            "type": d.get("type"),
            "title": d.get("title"),
            "active": d.get("isActive"),
            "impact": (d.get("impact") or {}).get("value"),
            "start": d.get("start"),
            "end": d.get("end"),
            "summary": (d.get("summaryAdditionalTravelTime") or {}).get("label"),
        })
    return out


def register(reg, cfg, http=None) -> None:
    def disruptions(ctx: ToolContext, a: dict):
        key = cfg.secrets.get("NS_API_KEY")
        if not key:
            return "NS train information is not configured (no NS_API_KEY)."
        client = http or httpx.Client(timeout=15)
        r = client.get(NS_DISRUPTIONS, headers={"Ocp-Apim-Subscription-Key": key}, params={"isActive": "true"})
        r.raise_for_status()
        return {"stations": cfg.ns_stations, "disruptions": parse_ns(r.json(), cfg.ns_stations)}

    reg.register(Tool("train_disruptions",
                      "Current NS train disruptions and engineering works affecting the family's stations "
                      "(e.g. 's-Hertogenbosch and Eindhoven Centraal).",
                      {"type": "object", "properties": {}, "additionalProperties": False}, disruptions))
