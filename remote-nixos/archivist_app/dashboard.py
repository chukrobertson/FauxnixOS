from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from app.config import DATA_DIR
from app.file_operator import recent_actions
from app.index_state import latest_run, run_snapshot

DASHBOARD_FILE = DATA_DIR / "dashboard_sources.json"
WEATHER_CACHE = {
    "key": "",
    "ts": 0.0,
    "data": None,
}


def default_dashboard_settings() -> dict:
    return {
        "weather": {"provider": None, "location": None, "sync_enabled": False},
        "calendar": {"providers": [], "sync_enabled": False},
        "updated_ts": None,
    }


def read_dashboard_settings() -> dict:
    try:
        data = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        data = {}
    defaults = default_dashboard_settings()
    return {
        "weather": {**defaults["weather"], **(data.get("weather") or {})},
        "calendar": {**defaults["calendar"], **(data.get("calendar") or {})},
        "updated_ts": data.get("updated_ts"),
    }


def write_dashboard_settings(settings: dict) -> dict:
    payload = {
        "weather": settings.get("weather") or default_dashboard_settings()["weather"],
        "calendar": settings.get("calendar") or default_dashboard_settings()["calendar"],
        "updated_ts": time.time(),
    }
    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return read_dashboard_settings()


def fetch_json(url: str, timeout: int = 6) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Archivist/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def weather_code_label(code: int | None) -> str:
    labels = {
        0: "Clear",
        1: "Mostly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Dense drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        80: "Light showers",
        81: "Showers",
        82: "Heavy showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Severe thunderstorm with hail",
    }
    return labels.get(int(code or 0), f"Weather code {code}")


def geocode_open_meteo(location: str) -> dict:
    query = urllib.parse.urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
    data = fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?{query}")
    results = data.get("results") or []
    if not results:
        raise ValueError(f"Could not find weather location `{location}`")
    item = results[0]
    label_bits = [item.get("name"), item.get("admin1"), item.get("country_code")]
    return {
        "latitude": float(item["latitude"]),
        "longitude": float(item["longitude"]),
        "resolved_location": ", ".join(str(bit) for bit in label_bits if bit),
        "timezone": item.get("timezone") or "auto",
    }


def fetch_open_meteo_weather(settings: dict, *, force: bool = False) -> dict:
    location = str(settings.get("location") or "").strip()
    if not location:
        return {
            **settings,
            "chat_aware": True,
            "status": "not_configured",
            "summary": "Weather location not configured yet.",
        }

    cache_key = json.dumps(
        {
            "provider": settings.get("provider"),
            "location": location,
            "latitude": settings.get("latitude"),
            "longitude": settings.get("longitude"),
        },
        sort_keys=True,
    )
    now = time.time()
    if not force and WEATHER_CACHE["key"] == cache_key and WEATHER_CACHE["data"] and now - WEATHER_CACHE["ts"] < 900:
        return dict(WEATHER_CACHE["data"])

    try:
        latitude = settings.get("latitude")
        longitude = settings.get("longitude")
        resolved_location = settings.get("resolved_location") or location
        timezone = settings.get("timezone") or "auto"
        if latitude is None or longitude is None:
            geo = geocode_open_meteo(location)
            latitude = geo["latitude"]
            longitude = geo["longitude"]
            resolved_location = geo["resolved_location"]
            timezone = geo["timezone"]

        params = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": timezone,
                "forecast_days": 3,
            }
        )
        data = fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
        current = data.get("current") or {}
        current_units = data.get("current_units") or {}
        daily = data.get("daily") or {}
        temp = current.get("temperature_2m")
        feels = current.get("apparent_temperature")
        code = current.get("weather_code")
        condition = weather_code_label(code)
        summary = condition
        if temp is not None:
            summary = f"{condition}, {round(float(temp))} F"
        if feels is not None:
            summary += f" feels like {round(float(feels))} F"
        result = {
            **settings,
            "provider": "open_meteo",
            "provider_label": "Open-Meteo",
            "location": location,
            "resolved_location": resolved_location,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": data.get("timezone") or timezone,
            "sync_enabled": True,
            "chat_aware": True,
            "status": "connected",
            "summary": summary,
            "condition": condition,
            "temperature_f": temp,
            "feels_like_f": feels,
            "humidity_percent": current.get("relative_humidity_2m"),
            "wind_mph": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "precipitation_in": current.get("precipitation"),
            "cloud_cover_percent": current.get("cloud_cover"),
            "current_units": current_units,
            "daily": daily,
            "updated_ts": now,
        }
        WEATHER_CACHE.update({"key": cache_key, "ts": now, "data": result})
        return result
    except Exception as e:
        result = {
            **settings,
            "provider": settings.get("provider") or "open_meteo",
            "provider_label": "Open-Meteo",
            "sync_enabled": bool(settings.get("sync_enabled")),
            "chat_aware": True,
            "status": "error",
            "summary": f"Weather provider issue: {e}",
            "error": str(e),
            "updated_ts": now,
        }
        WEATHER_CACHE.update({"key": cache_key, "ts": now - 720, "data": result})
        return result


def weather_context(settings: dict | None = None, *, force: bool = False) -> dict:
    weather = dict(settings or read_dashboard_settings()["weather"])
    if not weather.get("provider") and not weather.get("location"):
        return {
            **weather,
            "chat_aware": True,
            "status": "not_connected",
            "summary": "Weather provider not connected yet.",
        }
    if weather.get("provider") in {None, "open_meteo"}:
        return fetch_open_meteo_weather({**weather, "provider": "open_meteo"}, force=force)
    return {
        **weather,
        "chat_aware": True,
        "status": "unsupported",
        "summary": f"Weather provider `{weather.get('provider')}` is not supported yet.",
    }


def update_weather_settings(
    *,
    location: str | None = None,
    provider: str | None = "open_meteo",
    sync_enabled: bool | None = True,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    settings = read_dashboard_settings()
    weather = dict(settings.get("weather") or {})
    location_text = str(location or "").strip()
    weather.update(
        {
            "provider": provider or "open_meteo",
            "location": location_text,
            "sync_enabled": bool(sync_enabled) and bool(location_text),
            "updated_ts": time.time(),
        }
    )
    if latitude is not None and longitude is not None:
        weather["latitude"] = float(latitude)
        weather["longitude"] = float(longitude)
    elif location_text and location_text != weather.get("resolved_location"):
        weather.pop("latitude", None)
        weather.pop("longitude", None)
        weather.pop("resolved_location", None)
        weather.pop("timezone", None)
    if not location_text:
        weather = {"provider": None, "location": None, "sync_enabled": False}
    settings["weather"] = weather
    saved = write_dashboard_settings(settings)
    WEATHER_CACHE.update({"key": "", "ts": 0.0, "data": None})
    return {"settings": saved["weather"], "weather": weather_context(saved["weather"], force=True)}


def dashboard_context() -> dict:
    settings = read_dashboard_settings()
    run = latest_run()
    run_details = run_snapshot(int(run["id"])) if run else None
    actions = recent_actions(8)
    run_status = run_details.get("status") if run_details else "not started"
    recent_action = actions[0] if actions else None
    greeting_summary = (
        f"Index status: {run_status}. "
        f"Latest action: #{recent_action['id']} {recent_action['tool']} {recent_action['status']}."
        if recent_action
        else f"Index status: {run_status}. No recent file-operator actions."
    )
    return {
        "greeting": {
            "chat_aware": True,
            "summary": greeting_summary,
            "recommendations": [
                "Weather and calendar are ready for provider sync.",
                "Archive activity is available so the chat agent can help resume work.",
            ],
        },
        "weather": weather_context(settings["weather"]),
        "calendar": {
            **settings["calendar"],
            "chat_aware": True,
            "status": "not_connected" if not settings["calendar"].get("sync_enabled") else "sync_ready",
            "summary": "Calendar provider not connected yet.",
        },
        "chat_awareness": {
            "weather": True,
            "calendar": True,
            "archive_activity": True,
            "memory": True,
            "evidence": True,
        },
        "archive_activity": {
            "latest_index_run": run_details,
            "recent_actions": actions,
        },
        "generated_ts": time.time(),
    }


def format_dashboard_context(context: dict) -> str:
    greeting = context.get("greeting") or {}
    weather = context.get("weather") or {}
    calendar = context.get("calendar") or {}
    activity = context.get("archive_activity") or {}
    run = activity.get("latest_index_run") or {}
    actions = activity.get("recent_actions") or []
    lines = [
        "[GREETING]",
        f"Summary: {greeting.get('summary') or '[none]'}",
        "",
        "[WEATHER]",
        f"Status: {weather.get('status')}",
        f"Summary: {weather.get('summary')}",
        f"Location: {weather.get('location') or '[not configured]'}",
        f"Updated: {weather.get('updated_ts') or '[never]'}",
        "",
        "[CALENDAR]",
        f"Status: {calendar.get('status')}",
        f"Summary: {calendar.get('summary')}",
        f"Providers: {', '.join(calendar.get('providers') or []) or '[none connected]'}",
        "",
        "[ARCHIVE ACTIVITY]",
        f"Latest index status: {run.get('status') or '[none]'}",
        f"Indexed: {run.get('indexed_count', 0)}; duplicates: {run.get('duplicate_count', 0)}; failed: {run.get('failed_count', 0)}",
    ]
    if actions:
        lines.append("Recent file-operator actions:")
        for action in actions[:5]:
            lines.append(f"- #{action.get('id')} {action.get('tool')} {action.get('status')}")
    else:
        lines.append("Recent file-operator actions: [none]")
    return "\n".join(lines)[:5000]
