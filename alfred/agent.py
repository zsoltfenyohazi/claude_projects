"""Alfred's brain: a tool-use loop on the Claude Messages API."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from alfred.tools import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

PERSONA = (Path(__file__).parent / "persona.md").read_text(encoding="utf-8")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_ITERATIONS = 15


def family_profile(cfg) -> str:
    """Stable description of the household (kept out of per-request text so the prompt cache holds)."""
    lines = ["# Family profile"]
    for m in cfg.members:
        sources = [s for s, on in (("Gmail", m.gmail), ("Google Calendar", m.google_calendar),
                                   ("iCloud Mail", m.icloud_mail), ("iCloud Calendar", m.icloud_calendar)) if on]
        lines.append(f"- {m.name} (id: {m.id}), address as \"{m.address_as}\""
                     + (f", works in {cfg.locations[m.work_location].label}" if m.work_location in cfg.locations else "")
                     + (f"; connected: {', '.join(sources)}" if sources else "")
                     + ("; mailbox shared with the family" if m.share_mail_with_family else ""))
    for c in cfg.children:
        lines.append(f"- Child: {c.get('name')}" + (f", born {c['born']}" if c.get("born") else "")
                     + (f" — {c['notes']}" if c.get("notes") else ""))
    lines.append("# Places")
    lines += [f"- {k}: {loc.label}" for k, loc in cfg.locations.items()]
    if cfg.shops:
        lines.append("# Shops the family uses")
        lines += [f"- {s.name} ({s.kind})" for s in cfg.shops]
    lines.append(f"# Quiet hours: {cfg.quiet_start}–{cfg.quiet_end}")
    return "\n".join(lines)


def web_search_tool(cfg) -> dict:
    return {
        "type": "web_search_20260209", "name": "web_search", "max_uses": 5,
        "user_location": {"type": "approximate", "city": "'s-Hertogenbosch", "region": "Noord-Brabant",
                          "country": "NL", "timezone": str(cfg.timezone)},
    }


class Alfred:
    def __init__(self, cfg, store, registry: ToolRegistry, client=None):
        self.cfg, self.store, self.registry = cfg, store, registry
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.system = [{"type": "text", "text": PERSONA + "\n\n" + family_profile(cfg),
                        "cache_control": {"type": "ephemeral"}}]

    # ---- public entry points -----------------------------------------------------
    def chat(self, member_id: str, text: str, channel: str = "WhatsApp", effort: str = "low") -> str:
        member = self.cfg.member(member_id)
        now = datetime.now(self.cfg.timezone)
        stamped = f"[{now:%A %d %B %Y, %H:%M} — {member.name} ({member.address_as}) via {channel}]\n{text}"
        messages = self._history_messages(member_id) + [{"role": "user", "content": stamped}]
        reply = self._run(messages, ToolContext(requester=member_id), effort=effort, web=True)
        self.store.add_history(member_id, "user", stamped)
        self.store.add_history(member_id, "assistant", reply)
        return reply

    def task(self, instruction: str, effort: str = "medium", web: bool = False) -> str:
        """A scheduled job (morning brief, alerts, weekly plan). Runs as 'system'."""
        now = datetime.now(self.cfg.timezone)
        content = f"[{now:%A %d %B %Y, %H:%M} — scheduled task]\n{instruction}"
        return self._run([{"role": "user", "content": content}], ToolContext(requester="system"),
                         effort=effort, web=web)

    # ---- internals ---------------------------------------------------------------
    def _history_messages(self, member_id: str) -> list[dict]:
        msgs: list[dict] = []
        for row in self.store.history(member_id):
            if msgs and msgs[-1]["role"] == row["role"]:
                msgs[-1]["content"] += "\n" + row["text"]
            elif msgs or row["role"] == "user":
                msgs.append({"role": row["role"], "content": row["text"]})
        if msgs and msgs[-1]["role"] == "user":  # an unanswered turn; drop it to keep roles alternating
            msgs.pop()
        return msgs

    def _run(self, messages: list[dict], ctx: ToolContext, effort: str, web: bool) -> str:
        tools = self.registry.definitions() + ([web_search_tool(self.cfg)] if web else [])
        response = None
        for _ in range(MAX_ITERATIONS):
            response = self.client.beta.messages.create(
                model=self.cfg.model,
                max_tokens=16000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                system=self.system,
                tools=tools,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                self.store.audit(ctx.requester, "llm", f"in={usage.input_tokens} out={usage.output_tokens} "
                                 f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)}")

            if response.stop_reason == "refusal":
                return "I'm afraid I can't help with that one, but I'm happy to assist with anything else."
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                text, is_error = self.registry.execute(block.name, block.input, ctx)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text,
                                "is_error": is_error})
            messages.append({"role": "user", "content": results})
        else:
            log.warning("tool loop hit the iteration limit")

        text = "\n".join(b.text for b in (response.content if response else []) if b.type == "text").strip()
        return text or "My apologies, I seem to have lost my train of thought. Might you ask me again?"
