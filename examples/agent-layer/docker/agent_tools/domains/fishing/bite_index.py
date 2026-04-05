"""Heuristic fishing bite score (0–10) from weather-ish inputs — hobby model, not biology."""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any, Callable


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _moon_illumination(d: date) -> tuple[float, str]:
    epoch = date(2000, 1, 6)
    days = (d - epoch).days % 29.53058867
    phase = days / 29.53058867
    illum = 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))
    if phase < 0.0625 or phase > 0.9375:
        TOOL_LABEL = "new"
    elif phase < 0.5625 and phase > 0.4375:
        TOOL_LABEL = "full"
    else:
        TOOL_LABEL = "intermediate"
    return _clamp(illum, 0.0, 1.0), TOOL_LABEL


__version__ = "1.0.0"
TOOL_ID = "fishing_bite_index"
TOOL_LABEL = "Fishing"
TOOL_DESCRIPTION = (
    "Angeln: Biss-Heuristik, Spot-Muster, Köder — keine Karten/GPS oder Rechtsberatung."
)
TOOL_TRIGGERS = (
    "fishing",
    "angeln",
    "bite",
    "beiß",
    "fisch",
    "köderzeit",
)
TOOL_TAGS = ("fishing", "outdoor", "heuristic")
TOOL_DOMAIN = "fishing"
TOOL_REQUIRES = ["time", "weather"]


def fishing_bite_index(arguments: dict[str, Any]) -> str:
    temp_c = arguments.get("temp_c")
    pressure_trend_hpa_3h = arguments.get("pressure_trend_hpa_3h")
    wind_m_s = arguments.get("wind_m_s")
    cloudiness_pct = arguments.get("cloudiness_pct")
    hour_local = arguments.get("hour_local")
    date_iso = (arguments.get("date_iso") or "").strip()

    score = 5.0
    parts: dict[str, float] = {}

    if pressure_trend_hpa_3h is not None:
        t = float(pressure_trend_hpa_3h)
        if t < -1.5:
            score += 1.25
            parts["pressure_trend"] = 1.25
        elif t > 1.5:
            score -= 1.0
            parts["pressure_trend"] = -1.0
        else:
            parts["pressure_trend"] = 0.25

    if temp_c is not None:
        tc = float(temp_c)
        if 10.0 <= tc <= 22.0:
            score += 1.0
            parts["temp"] = 1.0
        elif tc < 4.0 or tc > 28.0:
            score -= 1.0
            parts["temp"] = -1.0
        else:
            parts["temp"] = 0.2

    if wind_m_s is not None:
        w = float(wind_m_s)
        if 2.0 <= w <= 6.0:
            score += 0.5
            parts["wind"] = 0.5
        elif w > 12.0:
            score -= 1.25
            parts["wind"] = -1.25
        else:
            parts["wind"] = 0.0

    if cloudiness_pct is not None:
        c = float(cloudiness_pct)
        if 40.0 <= c <= 85.0:
            score += 0.35
            parts["clouds"] = 0.35
        else:
            parts["clouds"] = 0.0

    moon_i = None
    moon_l = None
    if date_iso:
        try:
            y, m, d = (int(x) for x in date_iso.split("-")[:3])
            moon_i, moon_l = _moon_illumination(date(y, m, d))
            if moon_i < 0.15 or moon_i > 0.85:
                score += 0.25
                parts["moon"] = 0.25
            else:
                parts["moon"] = 0.0
        except (ValueError, OSError):
            moon_i, moon_l = None, None

    if hour_local is not None:
        h = int(hour_local) % 24
        if h in range(5, 9) or h in range(17, 21):
            score += 1.0
            parts["dawn_dusk"] = 1.0
        elif h in range(22, 24) or h in range(0, 4):
            score += 0.35
            parts["dawn_dusk"] = 0.35
        else:
            parts["dawn_dusk"] = 0.0

    score = round(_clamp(score, 0.0, 10.0), 2)
    return json.dumps(
        {
            "ok": True,
            "bite_index_0_10": score,
            "components": parts,
            "moon_illumination_0_1": moon_i,
            "moon_phase_coarse": moon_l,
            "disclaimer": "Heuristic only; species, water, and local rules matter.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "fishing_bite_index": fishing_bite_index,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fishing_bite_index",
            "TOOL_DESCRIPTION": (
                "Compute a coarse 0–10 bite-activity score from optional weather inputs. "
                "Pass numbers from openweather_* or your own observations. Not scientific."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "temp_c": {"type": "number"},
                    "pressure_trend_hpa_3h": {
                        "type": "number",
                        "TOOL_DESCRIPTION": "Negative = falling pressure (often scored higher here).",
                    },
                    "wind_m_s": {"type": "number"},
                    "cloudiness_pct": {"type": "number"},
                    "hour_local": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Local hour 0–23 for dawn/dusk bonus.",
                    },
                    "date_iso": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "YYYY-MM-DD for crude moon illumination tweak.",
                    },
                },
            },
        },
    },
]
