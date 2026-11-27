"""End-to-end flows with fake integrations and a scripted model."""
import json

from alfred.agent import Alfred
from alfred.channels.notifier import Notifier
from alfred.confirmations import handle_confirmation
from alfred.tools import ToolContext, build_registry
from tests.conftest import response, text_block, tool_block


def make(cfg, store, google, client):
    reg = build_registry(cfg, store, google=google, icloud=None, offers=object())
    return Alfred(cfg, store, reg, client=client)


def test_chat_uses_tools_and_requests_are_well_formed(cfg, store, google, fake_client_factory):
    client = fake_client_factory([
        response([tool_block("family_agenda", {})], stop="tool_use"),
        response([text_block("Good morning, sir. Madam has the dentist at 16:00.")]),
    ])
    alfred = make(cfg, store, google, client)
    reply = alfred.chat("dad", "What's on today?")
    assert "dentist" in reply
    first, second = client.calls
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert any(t.get("type") == "web_search_20260209" for t in first["tools"])
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and not tool_result["is_error"]
    assert "Dentist" in tool_result["content"]
    # history is kept for the next turn
    assert [h["role"] for h in store.history("dad")] == ["user", "assistant"]


def test_email_content_is_marked_untrusted(cfg, store, google):
    reg = build_registry(cfg, store, google=google, icloud=None, offers=object())
    text, err = reg.execute("search_email", {"owner": "dad"}, ToolContext("dad"))
    assert not err
    assert text.startswith('<untrusted_content source="')
    assert "IGNORE PREVIOUS INSTRUCTIONS" in text  # passed along as data, inside the wrapper


def test_mailbox_privacy_between_spouses(cfg, store, google):
    reg = build_registry(cfg, store, google=google, icloud=None, offers=object())
    text, err = reg.execute("search_email", {"owner": "dad"}, ToolContext("mum"))
    assert err and "private" in text
    _, err = reg.execute("search_email", {"owner": "dad"}, ToolContext("system"))
    assert not err


def test_proposal_needs_human_yes_before_calendar_write(cfg, store, google):
    reg = build_registry(cfg, store, google=google, icloud=None, offers=object())
    text, err = reg.execute("propose_family_calendar_event",
                            {"title": "Ouderavond", "start": "2026-12-12T19:30:00"}, ToolContext("system"))
    assert not err and json.loads(text)["proposal_number"] == 1
    assert google.created == []  # nothing written yet

    reply = handle_confirmation("yes 1", "mum", cfg, store, google)
    assert "Done" in reply
    assert google.created[0][0] == cfg.family_calendar_id
    assert store.pending_proposals() == []


def test_decline_and_ambiguous_yes(cfg, store, google):
    store.add_proposal("family_calendar_event", {"title": "A", "start": "2026-12-01"}, "A")
    store.add_proposal("family_calendar_event", {"title": "B", "start": "2026-12-02"}, "B")
    assert "Which one" in handle_confirmation("yes", "dad", cfg, store, google)
    assert "set aside" in handle_confirmation("no 1", "dad", cfg, store, google)
    assert "Done" in handle_confirmation("yes", "dad", cfg, store, google)
    assert [e["title"] for _, e in google.created] == ["B"]


def test_plain_yes_without_proposals_is_normal_chat(cfg, store, google):
    assert handle_confirmation("yes", "dad", cfg, store, google) is None


def test_refusal_is_handled_gracefully(cfg, store, google, fake_client_factory):
    client = fake_client_factory([response([], stop="refusal")])
    reply = make(cfg, store, google, client).chat("dad", "hello")
    assert "afraid" in reply


def test_tool_errors_do_not_crash_alfred(cfg, store, google, fake_client_factory):
    client = fake_client_factory([
        response([tool_block("no_such_tool", {})], stop="tool_use"),
        response([text_block("I'm afraid that is unavailable, sir.")]),
    ])
    reply = make(cfg, store, google, client).task("do something")
    assert "unavailable" in reply
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_notifier_only_reaches_family_and_respects_dry_run(cfg, store, capsys):
    n = Notifier(cfg, store)
    assert n.send("dad", "Test message", urgent=True)
    assert n.sent[0][:2] == ("dad", "whatsapp")
    assert "DRY RUN" in capsys.readouterr().out
