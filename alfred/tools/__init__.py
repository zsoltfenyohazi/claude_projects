"""Tool registry: every capability Alfred has is registered here, checked by the guards and audited."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from alfred.guards import GuardViolation, check_tool_name

log = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Who is asking. 'system' means a scheduled job rather than a family member."""
    requester: str


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[ToolContext, dict], Any]
    kind: str = "read"  # read | internal | propose

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


class ToolRegistry:
    def __init__(self, store):
        self.store = store
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        check_tool_name(tool.name)
        if tool.kind not in {"read", "internal", "propose"}:
            raise GuardViolation(f"Tool kind '{tool.kind}' is not allowed.")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def definitions(self) -> list[dict]:
        return [self._tools[n].definition() for n in sorted(self._tools)]

    def execute(self, name: str, args: dict, ctx: ToolContext) -> tuple[str, bool]:
        """Runs a tool. Returns (result_text, is_error)."""
        tool = self._tools.get(name)
        if tool is None:
            self.store.audit(ctx.requester, f"tool:{name}", "unknown tool", ok=False)
            return f"Unknown tool '{name}'.", True
        try:
            result = tool.handler(ctx, args or {})
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            self.store.audit(ctx.requester, f"tool:{name}", json.dumps(args, ensure_ascii=False)[:500])
            return text, False
        except GuardViolation as exc:
            self.store.audit(ctx.requester, f"tool:{name}", f"BLOCKED: {exc}", ok=False)
            return f"Not permitted: {exc}", True
        except Exception as exc:  # a broken source must never break Alfred
            log.warning("tool %s failed: %s: %s", name, type(exc).__name__, exc)
            self.store.audit(ctx.requester, f"tool:{name}", f"error: {exc}", ok=False)
            return f"The {name} source is unavailable at the moment ({type(exc).__name__}).", True


def build_registry(cfg, store, *, google=None, icloud=None, http=None, offers=None) -> ToolRegistry:
    """Assembles all tools. Integrations are injectable so tests can use fakes."""
    from alfred.tools import calendars, mail, memory, offers as offers_mod, transport, weather

    reg = ToolRegistry(store)
    memory.register(reg, cfg, store)
    weather.register(reg, cfg, http=http)
    transport.register(reg, cfg, http=http)
    calendars.register(reg, cfg, store, google=google, icloud=icloud)
    mail.register(reg, cfg, google=google, icloud=icloud)
    offers_mod.register(reg, cfg, store, provider=offers)
    return reg
