"""Coarse survival risk level from stated factors (planning aid)."""

from __future__ import annotations

import json
from typing import Any, Callable


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


__version__ = "1.0.0"
TOOL_ID = "survival_risk"
TOOL_LABEL = "Survival"
TOOL_DESCRIPTION = (
    "Survival: Wasserbedarf, Unterstand, Risiko-Score — keine medizinische Beratung."
)
TOOL_TRIGGERS = (
    "risk",
    "risiko",
    "survival",
    "notfall",
    "exposure",
)
TOOL_TAGS = ("survival", "outdoor", "calculator")
TOOL_DOMAIN = "survival"
TOOL_REQUIRES = ["situation_factors"]


def survival_risk_score(arguments: dict[str, Any]) -> str:
    r = 2.0
    factors: dict[str, float] = {}

    temp_c = arguments.get("temp_c")
    if temp_c is not None:
        try:
            tc = float(temp_c)
            if tc < -5.0:
                r += 2.0
                factors["cold"] = 2.0
            elif tc < 2.0:
                r += 1.0
                factors["cold"] = 1.0
            elif tc > 35.0:
                r += 1.5
                factors["heat"] = 1.5
        except (TypeError, ValueError):
            pass

    if bool(arguments.get("heavy_precip", False)):
        r += 1.25
        factors["precip"] = 1.25

    wind_m_s = arguments.get("wind_m_s")
    if wind_m_s is not None:
        try:
            if float(wind_m_s) > 14.0:
                r += 1.0
                factors["wind"] = 1.0
        except (TypeError, ValueError):
            pass

    if bool(arguments.get("night", False)):
        r += 0.75
        factors["night"] = 0.75
    if bool(arguments.get("injured", False)):
        r += 2.0
        factors["injured"] = 2.0

    h2o = arguments.get("hours_without_water")
    if h2o is not None:
        try:
            hw = float(h2o)
            if hw > 8.0:
                add = min(3.0, (hw - 8.0) * 0.35)
                r += add
                factors["water"] = add
        except (TypeError, ValueError):
            pass

    exp = arguments.get("hours_exposed")
    if exp is not None:
        try:
            he = float(exp)
            if he > 12.0:
                add = min(2.0, (he - 12.0) * 0.1)
                r += add
                factors["exposure_hours"] = add
        except (TypeError, ValueError):
            pass

    level = int(round(_clamp(r, 0.0, 10.0)))
    return json.dumps(
        {
            "ok": True,
            "risk_0_10": level,
            "factors": factors,
            "priority_hint": "Address highest-weight factors first (injury, water, then shelter/thermoregulation).",
            "disclaimer": "Ordinal model only; not a substitute for rescue services.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "survival_risk_score": survival_risk_score,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "survival_risk_score",
            "TOOL_DESCRIPTION": (
                "Compute a coarse 0–10 survival risk score from temperature, precip, wind, night, injury, "
                "hours without water, hours exposed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "temp_c": {"type": "number"},
                    "heavy_precip": {"type": "boolean"},
                    "wind_m_s": {"type": "number"},
                    "night": {"type": "boolean"},
                    "injured": {"type": "boolean"},
                    "hours_without_water": {"type": "number"},
                    "hours_exposed": {"type": "number"},
                },
            },
        },
    },
]
