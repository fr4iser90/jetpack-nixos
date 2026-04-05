"""Rough daily fluid maintenance estimate — not medical advice."""

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "1.0.0"
TOOL_ID = "survival_water"
TOOL_LABEL = "Survival"
TOOL_DESCRIPTION = (
    "Survival: Wasserbedarf, Unterstand, Risiko-Score — keine medizinische Beratung."
)
TOOL_TRIGGERS = (
    "survival",
    "wasser",
    "water",
    "dehydration",
    "outdoor",
    "notfall",
)
TOOL_TAGS = ("survival", "outdoor", "calculator")
TOOL_DOMAIN = "survival"
TOOL_REQUIRES = ["temperature", "activity"]


def survival_water_daily_liters(arguments: dict[str, Any]) -> str:
    temp_c = arguments.get("temp_c")
    activity = (arguments.get("activity") or "moderate").strip().lower()
    altitude_m = arguments.get("altitude_m")

    base = 2.5
    notes: list[str] = []

    if temp_c is not None:
        try:
            tc = float(temp_c)
            if tc > 30.0:
                base += 1.0
                notes.append("High heat: add electrolytes if available; sip steadily.")
            elif tc > 24.0:
                base += 0.5
        except (TypeError, ValueError):
            pass

    if activity in ("heavy", "stark", "march", "hike", "arbeit"):
        base += 0.8
        notes.append("Heavy exertion: increase frequency over volume per gulp if nauseous.")
    elif activity in ("light", "leicht", "rest"):
        base -= 0.2

    if altitude_m is not None:
        try:
            am = float(altitude_m)
            if am > 2500.0:
                base += 0.4
                notes.append("Altitude: dry air increases insensible loss.")
        except (TypeError, ValueError):
            pass

    base = max(1.5, round(base, 2))
    return json.dumps(
        {
            "ok": True,
            "estimated_liters_per_day": base,
            "activity_class": activity,
            "notes": notes or ["Purify unknown water; local disease risk varies."],
            "disclaimer": "Not medical advice; children, illness, and meds change needs.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "survival_water_daily_liters": survival_water_daily_liters,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "survival_water_daily_liters",
            "TOOL_DESCRIPTION": (
                "Rough maintenance fluid liters/day from temperature, activity level, and optional altitude. "
                "Educational planning only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "temp_c": {"type": "number"},
                    "activity": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "light | moderate | heavy (loose strings)",
                    },
                    "altitude_m": {"type": "number"},
                },
            },
        },
    },
]
