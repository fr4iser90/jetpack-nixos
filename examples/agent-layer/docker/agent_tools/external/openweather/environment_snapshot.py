"""Single-call context bundle: local time + optional OpenWeather + coarse daylight flag."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from zoneinfo import ZoneInfo

__version__ = "1.0.0"
TOOL_ID = "outdoor_snapshot"
TOOL_LABEL = "Outdoor context"
TOOL_DESCRIPTION = (
    "Normalized snapshot: clock + optional weather + daylight hint for planning domain tools."
)
TOOL_TRIGGERS = (
    "outdoor",
    "context",
    "snapshot",
    "umgebung",
    "environment",
    "wetter",
    "zeit",
    "angeln",
    "jagd",
    "survival",
)
TOOL_DOMAIN = "shared"
TOOL_TAGS = ("context", "weather", "time", "shared")
TOOL_REQUIRES: list[str] = []

_OWM = "https://api.openweathermap.org/data/2.5/weather"


def _api_key() -> str:
    return (os.environ.get("OPENWEATHER_API_KEY") or "").strip()


def outdoor_environment_snapshot(arguments: dict[str, Any]) -> str:
    tz_name = (arguments.get("timezone_name") or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
        tz_name = "UTC"

    now_local = datetime.now(tz)
    out: dict[str, Any] = {
        "ok": True,
        "time": {
            "timezone_name": tz_name,
            "iso_local": now_local.isoformat(),
            "unix_utc": datetime.now(timezone.utc).timestamp(),
        },
        "weather": None,
        "daylight": None,
        "coarse_exposure_hint": None,
    }

    loc = (arguments.get("location") or "").strip()
    if loc:
        key = _api_key()
        if not key:
            out["weather"] = {
                "ok": False,
                "error": "location set but OPENWEATHER_API_KEY missing on server",
            }
        else:
            try:
                with httpx.Client(timeout=20.0) as client:
                    r = client.get(
                        _OWM,
                        params={"q": loc, "units": "metric", "appid": key},
                    )
                    r.raise_for_status()
                    data = r.json()
            except httpx.HTTPStatusError as e:
                out["weather"] = {
                    "ok": False,
                    "error": f"HTTP {e.response.status_code}",
                    "detail": (e.response.text or "")[:400],
                }
                data = None
            except Exception as e:
                out["weather"] = {"ok": False, "error": str(e)}
                data = None

            if data is not None:
                main = data.get("main") if isinstance(data.get("main"), dict) else {}
                wind = data.get("wind") if isinstance(data.get("wind"), dict) else {}
                clouds = data.get("clouds") if isinstance(data.get("clouds"), dict) else {}
                sys_o = data.get("sys") if isinstance(data.get("sys"), dict) else {}
                wlist = data.get("weather")
                w0 = (
                    wlist[0]
                    if isinstance(wlist, list) and wlist and isinstance(wlist[0], dict)
                    else {}
                )
                sr = sys_o.get("sunrise")
                ss = sys_o.get("sunset")
                now_u = int(datetime.now(timezone.utc).timestamp())
                daylight = None
                if isinstance(sr, int) and isinstance(ss, int):
                    daylight = sr < now_u < ss
                out["weather"] = {
                    "ok": True,
                    "location_query": loc,
                    "name": data.get("name"),
                    "temp_c": main.get("temp"),
                    "pressure_hpa": main.get("pressure"),
                    "humidity_pct": main.get("humidity"),
                    "wind_speed_m_s": wind.get("speed"),
                    "wind_deg": wind.get("deg"),
                    "cloudiness_pct": clouds.get("all"),
                    "weather_main": w0.get("main"),
                    "weather_TOOL_DESCRIPTION": w0.get("TOOL_DESCRIPTION"),
                    "sunrise_unix_utc": sr,
                    "sunset_unix_utc": ss,
                }
                out["daylight"] = {
                    "approx_above_horizon_utc_window": daylight,
                    "note": "OpenWeather sunrise/sunset treated as UTC unix for coarse day/night.",
                }
                tc = main.get("temp")
                ws = wind.get("speed")
                hints: list[str] = []
                if isinstance(tc, (int, float)) and tc < 0:
                    hints.append("freezing_risk")
                if isinstance(ws, (int, float)) and ws > 12:
                    hints.append("strong_wind")
                if daylight is False:
                    hints.append("night")
                out["coarse_exposure_hint"] = hints or ["moderate_default"]
    else:
        out["weather"] = {
            "ok": True,
            "skipped": True,
            "hint": "Pass location for live weather; or call openweather_* separately.",
        }
        out["daylight"] = {"unknown": True, "hint": "Need location+weather or solar data."}

    return json.dumps(out, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "outdoor_environment_snapshot": outdoor_environment_snapshot,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "outdoor_environment_snapshot",
            "TOOL_DESCRIPTION": (
                "Return structured context: current time in an IANA timezone, optional OpenWeather snapshot "
                "(if location + server OPENWEATHER_API_KEY), coarse daylight flag, tiny exposure hints. "
                "Use before fishing_bite_index / survival / hunting planning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone_name": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "IANA zone, default UTC (e.g. Europe/Berlin)",
                    },
                    "location": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "City,country for OpenWeather q= — omit to skip weather.",
                    },
                },
            },
        },
    },
]
