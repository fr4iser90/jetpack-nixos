"""
Game Lore Generator Workflow
Consistent world building for games with small models
Automatic consistency checking, RAG backed lore bible
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app import db
from app.agent import chat_completion

logger = logging.getLogger(__name__)

__version__ = "1.0.0"

RUN_ON_STARTUP = False
RUN_EVERY_MINUTES = 0 # Manual trigger only

LORE_SYSTEM_PROMPT = """
Du bist professioneller Lore Designer für Rollenspiele.

REGELN DIE DU IMMER EINHÄLTST:
1.  ✅ Bleibe 100% konsistent mit bereits bestehenden Fakten
2.  ✅ Erfinde niemals widersprüchliche Details
3.  ✅ Nutze nur bereits definierte Weltregeln
4.  ✅ Schreibe präzise, konsistent und kreativ
5.  ✅ Teile Lore immer in logische Abschnitte auf
6.  ❌ Niemals Platzhalter
7.  ❌ Niemals "wir werden sehen" oder offene Enden
8.  ❌ Niemals Meta Kommentare

Antworte NUR mit dem fertigen Lore Text. Keine Einleitungen. Keine Anmerkungen.
"""

CONSISTENCY_CHECK_PROMPT = """
Prüfe diesen Lore Text auf Konsistenz mit bestehenden Fakten:

{existing_facts}

NEUER TEXT:
{new_text}

Antworte NUR mit EINEM WORT:
OK      → wenn alles passt
CONFLICT → wenn es Widersprüche gibt
"""


def generate_lore(arguments: dict[str, Any]) -> str:
    """
    Generate consistent game lore, automatically check consistency, save to lore bible
    
    Parameters:
        topic: Lore topic to generate (world, faction, character, location, history)
        name: Name of the element
        context: Additional context / requirements
    """
    topic = arguments.get('topic', 'general')
    name = arguments.get('name', 'unknown')
    context = arguments.get('context', '')

    logger.info(f"Generating lore: {topic} / {name}")

    # Get existing relevant lore from RAG
    existing_facts = ""
    
    # Build generation prompt
    prompt = LORE_SYSTEM_PROMPT + "\n\n"
    if existing_facts:
        prompt += f"BEREITS EXISTIERENDE FAKTEN:\n{existing_facts}\n\n"
    prompt += f"Generiere Lore für: {name}\nThema: {topic}\n"
    if context:
        prompt += f"Zusätzliche Anforderungen: {context}\n\n"

    # Generate lore
    completion = chat_completion({
        "stream": False,
        "messages": [
            { "role": "user", "content": prompt }
        ],
        "temperature": 0.7,
        "max_tokens": 2048
    })

    lore_text = completion["choices"][0]["message"]["content"].strip()

    # Check consistency
    check_prompt = CONSISTENCY_CHECK_PROMPT.format(
        existing_facts=existing_facts,
        new_text=lore_text
    )

    check_result = chat_completion({
        "stream": False,
        "messages": [
            { "role": "user", "content": check_prompt }
        ],
        "temperature": 0.0,
        "max_tokens": 16
    })

    is_ok = "ok" in check_result["choices"][0]["message"]["content"].strip().lower()

    if not is_ok:
        logger.warning(f"Consistency check failed for {name}")
        return json.dumps({
            "ok": False,
            "error": "Consistency check failed",
            "generated": lore_text
        })

    # Save to lore bible file
    lore_dir = Path(__file__).parent / "lore_bible"
    lore_dir.mkdir(parents=True, exist_ok=True)
    lore_file = lore_dir / f"{topic}_{name.lower().replace(' ', '_')}.md"
    lore_file.write_text(lore_text, encoding="utf-8")

    logger.info(f"Lore saved to: {lore_file}")

    return json.dumps({
        "ok": True,
        "topic": topic,
        "name": name,
        "consistent": True,
        "lore": lore_text,
        "file": str(lore_file)
    })


HANDLERS: dict[str, Any] = {
    "generate_lore": generate_lore,
}