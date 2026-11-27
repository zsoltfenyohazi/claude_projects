import hashlib
import hmac
import json
from pathlib import Path

from alfred.channels.whatsapp import parse_inbound, verify_signature
from alfred.tools.transport import parse_ns
from alfred.tools.weather import parse_buienradar, parse_meteoalarm, summarise_rain

FIX = Path(__file__).parent / "fixtures"


def test_buienradar_dry_and_wet():
    assert summarise_rain(parse_buienradar("000|10:00\n000|10:05\n")) == "Dry for the next two hours."
    pts = parse_buienradar("000|10:00\n077|10:05\n140|10:10\n000|10:15\n")
    assert pts[1]["mm_per_hour"] == 0.1 and pts[2]["mm_per_hour"] > 9
    assert summarise_rain(pts).startswith("Moderate rain from 10:05")


def test_meteoalarm_filters_region_and_language():
    data = json.loads((FIX / "meteoalarm.json").read_text())
    warnings = parse_meteoalarm(data, ["Noord-Brabant"])
    assert len(warnings) == 1
    w = warnings[0]
    assert w["level"] == "orange" and w["dutch_code"] == "code oranje" and w["event"] == "Severe wind gusts"


def test_ns_filter_by_station():
    items = [{"type": "DISRUPTION", "title": "'s-Hertogenbosch - Eindhoven Centraal", "isActive": True},
             {"type": "MAINTENANCE", "title": "Groningen - Zwolle", "isActive": True}]
    assert [d["title"] for d in parse_ns(items, ["'s-Hertogenbosch"])] == ["'s-Hertogenbosch - Eindhoven Centraal"]


def test_whatsapp_signature_and_parse():
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "31612345678", "id": "wamid.1", "type": "text", "text": {"body": "Good morning Alfred"}}]}}]}]})
    sig = "sha256=" + hmac.new(b"secret", body.encode(), hashlib.sha256).hexdigest()
    assert verify_signature("secret", body.encode(), sig)
    assert not verify_signature("secret", body.encode(), "sha256=bad")
    assert not verify_signature("", body.encode(), sig)
    assert parse_inbound(json.loads(body)) == [{"from": "31612345678", "text": "Good morning Alfred", "id": "wamid.1"}]
