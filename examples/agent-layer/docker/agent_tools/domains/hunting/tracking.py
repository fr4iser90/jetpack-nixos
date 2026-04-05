"""Static tracking / sign reading checklist (no live telemetry)."""

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "1.0.0"
TOOL_ID = "hunting_tracking"
TOOL_LABEL = "Hunting"
TOOL_DESCRIPTION = (
    "Jagd: Windkomponenten und Spuren-Checklisten — keine Ballistik, keine Live-Daten."
)
TOOL_TRIGGERS = (
    "track",
    "spur",
    "tracking",
    "trittsiegel",
    "wild",
)
TOOL_TAGS = ("hunting", "outdoor", "guide")
TOOL_DOMAIN = "hunting"
TOOL_REQUIRES = ["field_context"]


def hunting_tracking_guide(arguments: dict[str, Any]) -> str:
    animal = (arguments.get("animal") or "generic").strip().lower()
    substrate = (arguments.get("substrate") or "unknown").strip().lower()

    checks = [
        "Frische: Kanten scharf? Erde im Spalt frisch? Überprüfung an mehreren Stellen.",
        "Gangrichtung: längere Abdrücke / Schlepp-/Schlagschwanz bei Bedarf.",
        "Begleitspuren: Futterstellen, Liege, Kot/Losung (Art beachten).",
        "Höhenlinie: Wechsel von Deckung zu Futter oft entlang Kanten.",
    ]

    if "schnee" in substrate or "snow" in substrate:
        checks.insert(0, "Schnee: Kristallart, Überfrieren, Schneefall seit Spur?")
    if "schlamm" in substrate or "mud" in substrate:
        checks.insert(0, "Matsch: Wassereintrag, abgelaufene Ränder = älter.")

    species_hints: list[str] = []
    if "reh" in animal or "roe" in animal:
        species_hints.append("Reh: oft kleinere, schmalere Tritte; Sprungabstände beobachten.")
    if "wildschwein" in animal or "boar" in animal:
        species_hints.append("Schwein: breitere Front, Wühlstellen, Gruppenlogik möglich.")
    if "rotwild" in animal or "red deer" in animal or "hirsch" in animal:
        species_hints.append("Rotwild: größere Klauenabstände; Hirschgleise bei Schnee.")

    return json.dumps(
        {
            "ok": True,
            "animal": animal,
            "substrate": substrate,
            "field_checks": checks,
            "species_hints": species_hints or ["Generic: compare stride and width to known references."],
            "disclaimer": "Laws, seasons, and land access always override field practice.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "hunting_tracking_guide": hunting_tracking_guide,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "hunting_tracking_guide",
            "TOOL_DESCRIPTION": (
                "Return a structured field checklist for reading animal sign; optional substrate and species hints. "
                "Educational only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "animal": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "e.g. reh, wildschwein, rotwild, generic",
                    },
                    "substrate": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "snow, mud, sand, forest_floor, …",
                    },
                },
            },
        },
    },
]
