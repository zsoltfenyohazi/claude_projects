"""Preferences, memory and the shopping list: Alfred's own notebook (internal, harmless writes)."""
from __future__ import annotations

from alfred.tools import Tool, ToolContext

CATEGORIES = ["food", "health", "activities", "shopping", "schedule", "people", "finance", "other"]


def register(reg, cfg, store) -> None:
    member_ids = [m.id for m in cfg.members] + ["family"]

    def remember(ctx: ToolContext, a: dict):
        fact_id = store.remember(a["member_id"], a.get("category", "other"), a["fact"], source=ctx.requester)
        return {"saved": True, "id": fact_id}

    def recall(ctx: ToolContext, a: dict):
        return store.recall(a.get("member_id"), a.get("query"))

    def forget(ctx: ToolContext, a: dict):
        ok = store.forget(int(a["fact_id"]), ctx.requester if ctx.requester != "system" else a.get("member_id", ""))
        return {"forgotten": ok}

    def add_items(ctx: ToolContext, a: dict):
        ids = [store.add_shopping(i["item"], i.get("shop"), i.get("note")) for i in a["items"]]
        return {"added": len(ids)}

    def get_list(ctx: ToolContext, a: dict):
        return store.shopping_list()

    def tick(ctx: ToolContext, a: dict):
        return {"ticked_off": store.tick_off([int(i) for i in a["ids"]])}

    def activity(ctx: ToolContext, a: dict):
        return store.audit_since(int(a.get("hours", 24)))

    reg.register(Tool(
        "remember_preference",
        "Save a lasting fact about a family member or the family: likes, dislikes, allergies, habits, goals, "
        "important dates. Use member_id 'family' for shared facts. Save only what the family told you or "
        "clearly showed, never guesses.",
        {"type": "object", "properties": {
            "member_id": {"type": "string", "enum": member_ids},
            "category": {"type": "string", "enum": CATEGORIES},
            "fact": {"type": "string"}},
         "required": ["member_id", "fact"], "additionalProperties": False},
        remember, kind="internal"))
    reg.register(Tool(
        "recall_preferences",
        "Look up what you know about a family member (and shared family facts). Optional text query.",
        {"type": "object", "properties": {
            "member_id": {"type": "string", "enum": member_ids},
            "query": {"type": "string"}}, "additionalProperties": False},
        recall))
    reg.register(Tool(
        "forget_preference",
        "Remove a saved fact when a family member asks you to forget it. Use the id from recall_preferences.",
        {"type": "object", "properties": {"fact_id": {"type": "integer"}, "member_id": {"type": "string"}},
         "required": ["fact_id"], "additionalProperties": False},
        forget, kind="internal"))
    reg.register(Tool(
        "add_to_shopping_list",
        "Add items to the family shopping list. Optionally say which shop has the best offer.",
        {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {
                "item": {"type": "string"}, "shop": {"type": "string"}, "note": {"type": "string"}},
            "required": ["item"], "additionalProperties": False}}},
         "required": ["items"], "additionalProperties": False},
        add_items, kind="internal"))
    reg.register(Tool(
        "get_shopping_list", "Show the current family shopping list, grouped by shop.",
        {"type": "object", "properties": {}, "additionalProperties": False}, get_list))
    reg.register(Tool(
        "tick_off_shopping_items", "Mark shopping list items as bought, by id.",
        {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
         "required": ["ids"], "additionalProperties": False},
        tick, kind="internal"))
    reg.register(Tool(
        "my_recent_activity",
        "Alfred's own audit log: every tool he used recently. Use when asked 'what did you do today?'.",
        {"type": "object", "properties": {"hours": {"type": "integer"}}, "additionalProperties": False},
        activity))
