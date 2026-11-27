"""Weekly offers at the family's shops.

Each shop's public offers page is fetched, reduced to text, and Claude extracts the offers into a fixed
JSON shape. That is sturdier than hand-written scrapers that break whenever a site changes its HTML.
Results are cached for 12 hours. A shop that fails is skipped; it never breaks Alfred.
Some shops render offers with JavaScript only; for those, put a better URL (e.g. a weekly folder page)
in config/family.yaml.
"""
from __future__ import annotations

import json
import logging
from datetime import date

import httpx

from alfred.guards import untrusted
from alfred.integrations.google import html_to_text
from alfred.tools import Tool, ToolContext

log = logging.getLogger(__name__)

OFFER_SCHEMA = {
    "type": "object",
    "properties": {
        "offers": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "product": {"type": "string"},
                "deal": {"type": "string", "description": "e.g. '1+1 gratis', '35% korting', '2 voor 5,00'"},
                "price_eur": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "category": {"type": "string", "enum": [
                    "vegetables_fruit", "meat_fish", "dairy_eggs", "bakery", "pantry", "frozen", "drinks",
                    "snacks", "health_beauty", "household", "baby_kids", "electronics", "other"]},
                "healthy": {"type": "boolean", "description": "Fresh, whole or minimally processed food."},
            },
            "required": ["product", "deal", "price_eur", "category", "healthy"],
            "additionalProperties": False,
        }},
    },
    "required": ["offers"],
    "additionalProperties": False,
}


class OffersProvider:
    def __init__(self, cfg, store, client, http=None):
        self.cfg, self.store, self.client = cfg, store, client
        self.http = http or httpx.Client(timeout=20, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (alfred-family-butler; personal use)", "Accept-Language": "nl-NL,nl;q=0.9"})

    def page_text(self, url: str, max_chars: int = 60000) -> str:
        r = self.http.get(url)
        r.raise_for_status()
        return html_to_text(r.text)[:max_chars]

    def extract(self, shop_name: str, text: str) -> list[dict]:
        resp = self.client.messages.create(
            model=self.cfg.model,
            max_tokens=16000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": OFFER_SCHEMA}},
            messages=[{"role": "user", "content":
                       f"List the current promotional offers on this {shop_name} web page. Keep the Dutch "
                       f"product names. If there are no offers in the text, return an empty list.\n\n"
                       + untrusted(f"{shop_name} offers page", text)}],
        )
        if resp.stop_reason == "refusal":
            return []
        body = next((b.text for b in resp.content if b.type == "text"), '{"offers": []}')
        return json.loads(body)["offers"]

    def weekly_offers(self, shop_name: str) -> list[dict]:
        shop = next(s for s in self.cfg.shops if s.name.lower() == shop_name.lower())
        key = f"offers:{shop.name}:{date.today().isocalendar()[:2]}"
        cached = self.store.cache_get(key, max_age_hours=12)
        if cached is not None:
            return cached
        offers = self.extract(shop.name, self.page_text(shop.url))
        self.store.cache_set(key, offers)
        return offers


def register(reg, cfg, store, provider=None) -> None:
    if not cfg.shops:
        return
    shop_names = [s.name for s in cfg.shops]
    state = {"provider": provider}

    def get_provider():
        if state["provider"] is None:
            import anthropic
            state["provider"] = OffersProvider(cfg, store, anthropic.Anthropic())
        return state["provider"]

    def offers(ctx: ToolContext, a: dict):
        names = a.get("shops") or [s.name for s in cfg.shops if s.kind == a.get("kind", "groceries")]
        result, problems = {}, []
        for name in names:
            try:
                items = get_provider().weekly_offers(name)
                if a.get("healthy_only"):
                    items = [i for i in items if i.get("healthy")]
                result[name] = items
            except Exception as exc:
                log.warning("offers for %s failed: %s", name, exc)
                problems.append(name)
        return {"offers": result, "unavailable": problems}

    reg.register(Tool(
        "shop_offers",
        "This week's promotions at the family's shops (Albert Heijn, Plus, Lidl, Aldi, Ekoplaza, Etos, "
        "Holland & Barrett, Bol, Coolblue as configured). Choose shops by name, or kind 'groceries', "
        "'drugstore' or 'online'.",
        {"type": "object", "properties": {
            "shops": {"type": "array", "items": {"type": "string", "enum": shop_names}},
            "kind": {"type": "string", "enum": ["groceries", "drugstore", "online"]},
            "healthy_only": {"type": "boolean"}},
         "additionalProperties": False},
        offers))
