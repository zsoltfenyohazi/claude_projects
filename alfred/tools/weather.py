"""Weather: Open-Meteo forecast, Buienradar rain radar (next 2 hours) and MeteoAlarm/KNMI warnings."""
from __future__ import annotations

from datetime import datetime

import httpx

from alfred.tools import Tool, ToolContext

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
BUIENRADAR = "https://gpsgadget.buienradar.nl/data/raintext"
METEOALARM = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-netherlands"

LEVELS = {"1": "green", "2": "yellow", "3": "orange", "4": "red"}
DUTCH = {"yellow": "code geel", "orange": "code oranje", "red": "code rood"}


def _http(http):
    return http or httpx.Client(timeout=15, headers={"User-Agent": "alfred-family-butler/0.1"})


# ---- parsers (pure functions, tested with fixtures) ---------------------------------
def parse_buienradar(text: str) -> list[dict]:
    """'077|10:05' lines -> [{'time': '10:05', 'mm_per_hour': 0.4}]"""
    out = []
    for line in text.strip().splitlines():
        if "|" not in line:
            continue
        value, at = line.split("|", 1)
        v = int(value.strip() or 0)
        mm = 0.0 if v == 0 else round(10 ** ((v - 109) / 32), 2)
        out.append({"time": at.strip(), "mm_per_hour": mm})
    return out


def summarise_rain(points: list[dict]) -> str:
    wet = [p for p in points if p["mm_per_hour"] >= 0.1]
    if not wet:
        return "Dry for the next two hours."
    peak = max(wet, key=lambda p: p["mm_per_hour"])
    kind = "light rain" if peak["mm_per_hour"] < 2.5 else "moderate rain" if peak["mm_per_hour"] < 10 else "heavy rain"
    return f"{kind.capitalize()} from {wet[0]['time']} until about {wet[-1]['time']} (peak {peak['mm_per_hour']} mm/h at {peak['time']})."


def parse_meteoalarm(data: dict, regions: list[str]) -> list[dict]:
    """Extract English warnings for the configured regions (e.g. Noord-Brabant) from the MeteoAlarm feed."""
    regions_l = [r.lower() for r in regions]
    found, seen = [], set()
    for w in data.get("warnings", []):
        for info in w.get("alert", {}).get("info", []):
            lang = (info.get("language") or "").lower()
            if lang and not lang.startswith("en"):
                continue
            areas = [a.get("areaDesc", "") for a in info.get("area", [])]
            if not any(any(r in a.lower() for r in regions_l) for a in areas):
                continue
            level = "unknown"
            for p in info.get("parameter", []):
                if p.get("valueName") == "awareness_level":
                    level = LEVELS.get(p.get("value", "").split(";")[0].strip(), "unknown")
            key = (info.get("event"), level, info.get("onset"))
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "event": info.get("event"),
                "level": level,
                "dutch_code": DUTCH.get(level, ""),
                "areas": areas,
                "onset": info.get("onset"),
                "expires": info.get("expires"),
                "headline": info.get("headline"),
                "description": (info.get("description") or "")[:500],
            })
    return found


def summarise_forecast(data: dict) -> list[dict]:
    d = data.get("daily", {})
    days = []
    for i, day in enumerate(d.get("time", [])):
        days.append({
            "date": day,
            "min_c": d["temperature_2m_min"][i],
            "max_c": d["temperature_2m_max"][i],
            "rain_mm": d["precipitation_sum"][i],
            "rain_chance_pct": d["precipitation_probability_max"][i],
            "max_gust_kmh": d["wind_gusts_10m_max"][i],
            "sunshine_hours": round((d.get("sunshine_duration") or [0] * (i + 1))[i] / 3600, 1),
        })
    return days


# ---- fetchers ---------------------------------------------------------------------
def fetch_forecast(http, lat: float, lon: float, days: int = 7) -> list[dict]:
    r = _http(http).get(OPEN_METEO, params={
        "latitude": lat, "longitude": lon, "timezone": "Europe/Amsterdam", "forecast_days": days,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,precipitation_probability_max,"
                 "wind_gusts_10m_max,sunshine_duration",
    })
    r.raise_for_status()
    return summarise_forecast(r.json())


def fetch_rain(http, lat: float, lon: float) -> str:
    r = _http(http).get(BUIENRADAR, params={"lat": round(lat, 2), "lon": round(lon, 2)})
    r.raise_for_status()
    return summarise_rain(parse_buienradar(r.text))


def fetch_warnings(http, regions: list[str]) -> list[dict]:
    r = _http(http).get(METEOALARM)
    r.raise_for_status()
    return parse_meteoalarm(r.json(), regions)


def register(reg, cfg, http=None) -> None:
    loc_keys = list(cfg.locations)

    def forecast(ctx: ToolContext, a: dict):
        loc = cfg.locations[a.get("location", "home")]
        return {"location": loc.label, "days": fetch_forecast(http, loc.lat, loc.lon, int(a.get("days", 7)))}

    def rain(ctx: ToolContext, a: dict):
        loc = cfg.locations[a.get("location", "home")]
        return {"location": loc.label, "next_two_hours": fetch_rain(http, loc.lat, loc.lon),
                "checked_at": datetime.now(cfg.timezone).strftime("%H:%M")}

    def warnings(ctx: ToolContext, a: dict):
        return {"regions": cfg.meteoalarm_regions, "warnings": fetch_warnings(http, cfg.meteoalarm_regions)}

    loc_schema = {"type": "string", "enum": loc_keys}
    reg.register(Tool("weather_forecast",
                      "Daily weather forecast (up to 16 days) for one of the family's places.",
                      {"type": "object", "properties": {"location": loc_schema, "days": {"type": "integer"}},
                       "additionalProperties": False}, forecast))
    reg.register(Tool("rain_next_two_hours",
                      "Buienradar rain radar for the next two hours at a place. Ideal before a commute or a walk.",
                      {"type": "object", "properties": {"location": loc_schema}, "additionalProperties": False},
                      rain))
    reg.register(Tool("weather_warnings",
                      "Official KNMI weather warnings (code geel/oranje/rood) for the family's province, "
                      "via MeteoAlarm.",
                      {"type": "object", "properties": {}, "additionalProperties": False}, warnings))
