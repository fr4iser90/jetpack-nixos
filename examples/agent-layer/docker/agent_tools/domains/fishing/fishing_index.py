"""OpenWeather Current Weather + 5-day / 3-hour forecast (free-tier 2.5 APIs).

We use only ``/data/2.5/weather`` and ``/data/2.5/forecast`` with ``OPENWEATHER_API_KEY``.
Those endpoints are the standard subscription product; they are **not** the deprecated
One Call 2.5 API. Do **not** use ``/data/2.5/onecall`` or ``/data/3.0/onecall`` in
generated plugins unless you have explicitly enabled that product on your OpenWeather account.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

__version__ = "1.2.0"
TOOL_ID = "openweather"
TOOL_LABEL = "OpenWeather"
TOOL_DESCRIPTION = (
    "Current weather and 5-day / 3-hour forecast using OpenWeather 2.5 APIs (OPENWEATHER_API_KEY)."
)
TOOL_TRIGGERS = (
    "openweather",
    "weather",
    "forecast",
    "temperature",
    "openweathermap",
)

_OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def _api_key() -> str:
    return (os.environ.get("OPENWEATHER_API_KEY") or "").strip()


def openweather_current(arguments: dict[str, Any]) -> str:
    """
    Current weather for a place name (OpenWeather ``/weather``, metric units).
    API key: ``OPENWEATHER_API_KEY`` in the agent container environment only.
    """
    loc = str(arguments.get("location") or "").strip()
    if not loc:
        return json.dumps({"ok": False, "error": "location is required"}, ensure_ascii=False)
    key = _api_key()
    if not key:
        return json.dumps(
            {
                "ok": False,
                "error": "OPENWEATHER_API_KEY is not set in the agent environment",
                "hint": "Set it in docker/.env for the agent-layer service and restart.",
            },
            ensure_ascii=False,
        )
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                _OPENWEATHER_URL,
                params={"q": loc, "units": "metric", "appid": key},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {
                "ok": False,
                "error": f"OpenWeather HTTP {e.response.status_code}",
                "detail": (e.response.text or "")[:800],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    main = data.get("main") if isinstance(data.get("main"), dict) else {}
    wind = data.get("wind") if isinstance(data.get("wind"), dict) else {}
    clouds = data.get("clouds") if isinstance(data.get("clouds"), dict) else {}
    coord = data.get("coord") if isinstance(data.get("coord"), dict) else {}
    sys_o = data.get("sys") if isinstance(data.get("sys"), dict) else {}
    weather = data.get("weather")
    w0 = weather[0] if isinstance(weather, list) and weather and isinstance(weather[0], dict) else {}

    out: dict[str, Any] = {
        "ok": True,
        "location_query": loc,
        "name": data.get("name"),
        "country": sys_o.get("country"),
        "lat": coord.get("lat"),
        "lon": coord.get("lon"),
        "temp_c": main.get("temp"),
        "feels_like_c": main.get("feels_like"),
        "temp_min_c": main.get("temp_min"),
        "temp_max_c": main.get("temp_max"),
        "humidity_pct": main.get("humidity"),
        "pressure_hpa": main.get("pressure"),
        "sea_level_hpa": main.get("sea_level"),
        "visibility_m": data.get("visibility"),
        "wind_speed_m_s": wind.get("speed"),
        "wind_deg": wind.get("deg"),
        "wind_gust_m_s": wind.get("gust"),
        "cloudiness_pct": clouds.get("all"),
        "weather_id": w0.get("id"),
        "weather_main": w0.get("main"),
        "weather_TOOL_DESCRIPTION": w0.get("TOOL_DESCRIPTION"),
        "sunrise_unix": sys_o.get("sunrise"),
        "sunset_unix": sys_o.get("sunset"),
        "timezone_offset_s": data.get("timezone"),
        "data_dt_unix": data.get("dt"),
    }
    return json.dumps(out, ensure_ascii=False)


def openweather_forecast(arguments: dict[str, Any]) -> str:
    """
    5-day forecast in **3-hour steps** (OpenWeather ``/forecast``, metric).

    Use this (not ``onecall``) for “best time tomorrow”, fishing/bite heuristics, etc.
    Combine slots with your own formula in the model; there is no official “bite index” field.
    """
    loc = str(arguments.get("location") or "").strip()
    if not loc:
        return json.dumps({"ok": False, "error": "location is required"}, ensure_ascii=False)
    raw_max = arguments.get("max_slots")
    try:
        max_slots = int(raw_max) if raw_max is not None else 24
    except (TypeError, ValueError):
        max_slots = 24
    max_slots = max(1, min(40, max_slots))

    key = _api_key()
    if not key:
        return json.dumps(
            {
                "ok": False,
                "error": "OPENWEATHER_API_KEY is not set in the agent environment",
                "hint": "Set it in docker/.env for the agent-layer service and restart.",
            },
            ensure_ascii=False,
        )
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.get(
                _FORECAST_URL,
                params={"q": loc, "units": "metric", "appid": key},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {
                "ok": False,
                "error": f"OpenWeather HTTP {e.response.status_code}",
                "detail": (e.response.text or "")[:800],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    city = data.get("city") if isinstance(data.get("city"), dict) else {}
    series: list[dict[str, Any]] = []
    lst = data.get("list")
    if not isinstance(lst, list):
        lst = []

    for item in lst[:max_slots]:
        if not isinstance(item, dict):
            continue
        main = item.get("main") if isinstance(item.get("main"), dict) else {}
        wind = item.get("wind") if isinstance(item.get("wind"), dict) else {}
        wlist = item.get("weather")
        w0 = (
            wlist[0]
            if isinstance(wlist, list) and wlist and isinstance(wlist[0], dict)
            else {}
        )
        dt_u = item.get("dt")
        dt_txt = item.get("dt_txt")
        iso = None
        if isinstance(dt_u, int):
            iso = datetime.fromtimestamp(dt_u, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        series.append(
            {
                "dt_unix": dt_u,
                "time_utc": dt_txt if isinstance(dt_txt, str) else iso,
                "temp_c": main.get("temp"),
                "feels_like_c": main.get("feels_like"),
                "humidity_pct": main.get("humidity"),
                "pressure_hpa": main.get("pressure"),
                "wind_speed_m_s": wind.get("speed"),
                "wind_deg": wind.get("deg"),
                "pop": item.get("pop"),
                "weather_main": w0.get("main"),
                "weather_TOOL_DESCRIPTION": w0.get("TOOL_DESCRIPTION"),
            }
        )

    out: dict[str, Any] = {
        "ok": True,
        "location_query": loc,
        "city_name": city.get("name"),
        "country": city.get("country"),
        "lat": (city.get("coord") or {}).get("lat") if isinstance(city.get("coord"), dict) else None,
        "lon": (city.get("coord") or {}).get("lon") if isinstance(city.get("coord"), dict) else None,
        "slot_hours": 3,
        "slots_returned": len(series),
        "forecast": series,
    }
    return json.dumps(out, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "openweather_current": openweather_current,
    "openweather_forecast": openweather_forecast,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "openweather_current",
            "TOOL_DESCRIPTION": (
                "Current weather snapshot for a place (OpenWeather /data/2.5/weather, metric). "
                "For multi-hour or ‘tomorrow’ planning use openweather_forecast instead. "
                "Server env OPENWEATHER_API_KEY only — never pass API keys in chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "City name (and optional country), e.g. Berlin,de or Munich",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "openweather_forecast",
            "TOOL_DESCRIPTION": (
                "5-day weather forecast in 3-hour steps (OpenWeather /data/2.5/forecast, metric). "
                "Use for picking time windows (e.g. tomorrow); there is no official fishing/bite index in the API — "
                "compute any heuristic from temp, humidity, wind, pop in the returned slots. "
                "Same key as openweather_current: OPENWEATHER_API_KEY on the server only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "City name (and optional country), e.g. Leipzig,de",
                    },
                    "max_slots": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max forecast slots to return (1–40, default 24). API returns up to 40 three-hour steps.",
                    },
                },
                "required": ["location"],
            },
        },
    },
]
