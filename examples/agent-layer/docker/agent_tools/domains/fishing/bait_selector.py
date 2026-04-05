"""Bait / lure family suggestions from species and conditions (static rules)."""

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "1.0.0"
TOOL_ID = "fishing_bait"

TOOL_LABEL = "Fishing"

TOOL_DESCRIPTION = (
    "Angeln: Biss-Heuristik, Spot-Muster, Köder — keine Karten/GPS oder Rechtsberatung."
)

TOOL_TRIGGERS = (
    "köder",
    "bait",
    "lure",
    "montage",
    "wobbler",
    "gummifisch",
)
TOOL_TAGS = ("fishing", "outdoor", "action")
TOOL_DOMAIN = "fishing"
TOOL_REQUIRES = ["species", "conditions"]


def fishing_bait_suggest(arguments: dict[str, Any]) -> str:
    species = (arguments.get("target_species") or "").strip().lower()
    clarity = (arguments.get("water_clarity") or "").strip().lower()
    depth_m = arguments.get("depth_m")

    primary: list[str] = []
    alternate: list[str] = []
    rig_notes: list[str] = []

    if "hecht" in species or "pike" in species:
        primary.extend(["Großer Gummifisch / Jerk", "Spinnerbait bei Krautfeldern"])
        alternate.extend(["Köderfisch-Montage wo erlaubt", "Crankbait entlang Kanten"])
        rig_notes.append("Stahlvorfach; kräftiger Haken.")
    elif "zander" in species or "walleye" in species:
        primary.extend(["Gummifisch langsam am Grund", "Jigkopf an Kanten"])
        alternate.extend(["kleinere Jerks", "Spinnerbaits in trübem Wasser"])
        rig_notes.append("Feinere Köderköpfe bei Zögerbiss testen.")
    elif "barsch" in species or "perch" in species:
        primary.extend(["kleine Gummis, Dropshot, kleine Spinner"])
        alternate.extend(["Inline-Spoon", "kleine Crankbaits"])
    elif "karpfen" in species or "carp" in species:
        primary.extend(["Boilie / Mais / Teig — lokales Gewässerreglement beachten"])
        rig_notes.append("Haarmontage / Safety-Lead je nach Gewässer.")
    elif "forelle" in species or "trout" in species:
        primary.extend(["Spinner, kleiner Wobbler, Teig / Paste wo erlaubt"])
        rig_notes.append("Fliegenfischen separat; hier nur grobe Richtung.")
    else:
        primary.append("Allround: neutraler Gummi oder kleiner Spinner testen.")

    if clarity in ("clear", "klar", "kristall"):
        rig_notes.append("Natürlichere Farben, feinere Führung.")
    elif clarity in ("murky", "trüb", "dreckig"):
        rig_notes.append("Kontrastfarben, Vibration/Lärm, größere Silhouette.")

    if depth_m is not None:
        try:
            d = float(depth_m)
            if d > 6.0:
                rig_notes.append("Tiefer: schwerer Kopf / langsameres Arbeiten.")
            elif d < 1.5:
                rig_notes.append("Flach: flache Laufkultur, weniger Snag riskieren.")
        except (TypeError, ValueError):
            pass

    return json.dumps(
        {
            "ok": True,
            "target_species": species or None,
            "primary": primary,
            "alternate": alternate,
            "rig_notes": rig_notes,
            "disclaimer": "Local bait bans and hook rules override this list.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "fishing_bait_suggest": fishing_bait_suggest,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fishing_bait_suggest",
            "TOOL_DESCRIPTION": (
                "Suggest bait/lure families and short rig notes for a target species and water clarity. "
                "Static heuristics only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_species": {"type": "string"},
                    "water_clarity": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "clear | murky | unknown",
                    },
                    "depth_m": {"type": "number"},
                },
            },
        },
    },
]
