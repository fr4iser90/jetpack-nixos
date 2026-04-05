"""Wind components for shot / approach geometry (simple trigonometry)."""

from __future__ import annotations

import json
import math
from typing import Any, Callable

__version__ = "1.0.0"
TOOL_ID = "hunting_wind"
TOOL_LABEL = "Hunting"
TOOL_DESCRIPTION = (
    "Jagd: Windkomponenten und Spuren-Checklisten — keine Ballistik, keine Live-Daten."
)
TOOL_TRIGGERS = (
    "hunting",
    "jagd",
    "wind",
    "drift",
    "crosswind",
    "ansitz",
)
TOOL_TAGS = ("hunting", "outdoor", "calculator")
TOOL_DOMAIN = "hunting"
TOOL_REQUIRES = ["wind", "bearing"]


def hunting_wind_analysis(arguments: dict[str, Any]) -> str:
    try:
        wind_speed = float(arguments.get("wind_speed_m_s"))
        wind_from_deg = float(arguments.get("wind_from_deg"))
        bearing_deg = float(arguments.get("bearing_to_target_deg"))
    except (TypeError, ValueError):
        return json.dumps(
            {"ok": False, "error": "wind_speed_m_s, wind_from_deg, bearing_to_target_deg required (numbers)"},
            ensure_ascii=False,
        )

    theta = math.radians((wind_from_deg + 180.0 - bearing_deg) % 360.0)
    cross = abs(wind_speed * math.sin(theta))
    along = wind_speed * math.cos(theta)
    smell_risk = "lower" if along > 0.5 else "higher"
    return json.dumps(
        {
            "ok": True,
            "crosswind_m_s": round(cross, 3),
            "along_wind_m_s": round(along, 3),
            "interpretation": {
                "positive_along": "Wind roughly from hunter toward target line — scent may carry ahead.",
                "scent_risk_hint": smell_risk,
            },
            "disclaimer": "Meteorological wind FROM deg; bearing is direction you face toward target. Not ballistics.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "hunting_wind_analysis": hunting_wind_analysis,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "hunting_wind_analysis",
            "TOOL_DESCRIPTION": (
                "Given wind speed (m/s), wind FROM direction (deg), and bearing toward target (deg), "
                "return crosswind and along-wind components plus a coarse scent-transport hint."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "wind_speed_m_s": {"type": "number"},
                    "wind_from_deg": {
                        "type": "number",
                        "TOOL_DESCRIPTION": "Meteorological: direction wind blows FROM, 0=N, 90=E",
                    },
                    "bearing_to_target_deg": {
                        "type": "number",
                        "TOOL_DESCRIPTION": "Compass bearing from you toward target, same convention",
                    },
                },
                "required": ["wind_speed_m_s", "wind_from_deg", "bearing_to_target_deg"],
            },
        },
    },
]
