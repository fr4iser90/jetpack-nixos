"""Where-to-fish style suggestions from coarse inputs (no maps, no live data)."""

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "1.0.0"
TOOL_ID = "fishing_spot"
TOOL_LABEL = "Fishing"
TOOL_DESCRIPTION = (
    "Angeln: Biss-Heuristik, Spot-Muster, Köder — keine Karten/GPS oder Rechtsberatung."
)
TOOL_TRIGGERS = (
    "spot",
    "stelle",
    "gewässer",
    "where to fish",
    "angelplatz",
)
TOOL_TAGS = ("fishing", "outdoor", "planner")
TOOL_DOMAIN = "fishing"
TOOL_REQUIRES = ["location_context"]


def fishing_spot_recommend(arguments: dict[str, Any]) -> str:
    species = (arguments.get("target_species") or "").strip().lower()
    water = (arguments.get("water_type") or "").strip().lower()
    season = (arguments.get("season") or "").strip().lower()
    wind_m_s = arguments.get("wind_m_s")

    spots: list[str] = []
    avoid: list[str] = []

    if "hecht" in species or "pike" in species:
        spots.extend(
            [
                "Kanten zu tieferem Wasser, Struktur (Fallen, Steine, Wasserpflanzen).",
                "Langsam geführte Köder entlang Wechselböden.",
            ]
        )
        avoid.append("Sehr flaches, strukturloses Flachwasser bei Hochdruckglätte.")
    if "zander" in species or "walleye" in species or "sander" in species:
        spots.extend(
            [
                "Abbruchkanten, Brückenpfeiler, Flussmündungen in Seen.",
                "Weiche bis mittlere Strömung mit Kanten.",
            ]
        )
    if "barsch" in species or "perch" in species:
        spots.extend(["Steinstruktur, Buhnen, Totholz, flacheres bis mittleres Wasser."])

    if water in ("river", "fluss"):
        spots.append("Außenkurven, Einmündungen kleiner Bäche, hinter Stromschutz.")
    elif water in ("lake", "see"):
        spots.append("Windufer bei moderatem Wellengang kann Futterfisch anziehen.")
    elif water in ("sea", "meer", "küste", "coast"):
        spots.append("Brandungszonen, Buhnen, tiefe Rinnen — immer lokale Regeln beachten.")

    if season in ("spring", "frühling"):
        spots.append("Flacheres Wasser und Zuflüsse können in der Laich-/Aufwärmphase stärker sein.")
    elif season in ("autumn", "herbst"):
        spots.append("Futterplatze und Übergänge tief/flach oft relevant.")
    elif season in ("winter", "winter"):
        spots.append("Tiefere, langsamere Passagen; Eisangeln nur wo erlaubt und sicher.")

    if wind_m_s is not None and float(wind_m_s) > 10.0:
        avoid.append("Aufgewühltes Ufer bei Sturm: Sicherheit vor Biss.")

    if not spots:
        spots.append(
            "Generisch: erste Struktur (Kante, Holz, Steine), Wechsel von Licht/Schatten probieren."
        )

    return json.dumps(
        {
            "ok": True,
            "target_species": species or None,
            "water_type": water or None,
            "season": season or None,
            "try_spots": spots,
            "avoid_or_caution": avoid,
            "disclaimer": "No GPS/maps; obey access, seasons, and local law.",
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "fishing_spot_recommend": fishing_spot_recommend,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fishing_spot_recommend",
            "TOOL_DESCRIPTION": (
                "Suggest coarse fishing spot patterns (structure, water type, season). "
                "Does not fetch maps or regulations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_species": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "e.g. Hecht, Zander, Barsch",
                    },
                    "water_type": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "river | lake | sea (loose strings accepted)",
                    },
                    "season": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "spring | summer | autumn | winter (any language hints ok)",
                    },
                    "wind_m_s": {"type": "number"},
                },
            },
        },
    },
]
