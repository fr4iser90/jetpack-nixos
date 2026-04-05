"""Prioritized shelter steps from conditions and gear flags."""

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "1.0.0"
TOOL_ID = "survival_shelter"
TOOL_LABEL = "Survival"
TOOL_DESCRIPTION = (
    "Survival: Wasserbedarf, Unterstand, Risiko-Score — keine medizinische Beratung."
)
TOOL_TRIGGERS = (
    "shelter",
    "unterstand",
    "bivouac",
    "notlager",
    "übernachtung",
)
TOOL_TAGS = ("survival", "outdoor", "guide")
TOOL_DOMAIN = "survival"
TOOL_REQUIRES = ["weather", "gear"]


def survival_shelter_plan(arguments: dict[str, Any]) -> str:
    precip = bool(arguments.get("precip", False))
    try:
        wind = float(arguments.get("wind_m_s") or 0.0)
    except (TypeError, ValueError):
        wind = 0.0
    try:
        temp_c = float(arguments.get("temp_c") or 15.0)
    except (TypeError, ValueError):
        temp_c = 15.0
    has_tarp = bool(arguments.get("has_tarp", False))
    has_cordage = bool(arguments.get("has_cordage", False))

    steps: list[str] = [
        "1) Site: dry ground, not a watercourse; deadfall/widow-makers check overhead.",
        "2) Insulation from ground: boughs, pack, debris bed — priority in cold.",
        "3) Wind: back to wind, use terrain or build windward wall.",
    ]

    if precip or wind > 8.0:
        steps.insert(
            3,
            "Roof first: lean-to or A-frame; drip lines away from sleeping area.",
        )
    if temp_c < 5.0:
        steps.append("Cold: reduce convective losses; block ground cold; keep head covered.")
    if has_tarp and has_cordage:
        steps.append("Tarp: ridge line or low pitch A-frame; anchor corners.")
    elif has_tarp and not has_cordage:
        steps.append("Tarp without cordage: wedge under logs/rocks; improvise toggles from strips.")
    else:
        steps.append("No tarp: debris hut / long log lean shorter sticks; smaller door.")

    return json.dumps(
        {
            "ok": True,
            "conditions": {
                "precip": precip,
                "wind_m_s": wind,
                "temp_c": temp_c,
                "has_tarp": has_tarp,
                "has_cordage": has_cordage,
            },
            "steps": steps,
            "disclaimer": "Practice skills safely; fire and tree risk are local.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "survival_shelter_plan": survival_shelter_plan,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "survival_shelter_plan",
            "TOOL_DESCRIPTION": (
                "Return an ordered shelter checklist from weather hints and whether tarp/cordage exist. "
                "No terrain data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "precip": {"type": "boolean"},
                    "wind_m_s": {"type": "number"},
                    "temp_c": {"type": "number"},
                    "has_tarp": {"type": "boolean"},
                    "has_cordage": {"type": "boolean"},
                },
            },
        },
    },
]
