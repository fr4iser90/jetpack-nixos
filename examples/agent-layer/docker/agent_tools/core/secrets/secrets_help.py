"""Static help for user secrets (no OTP); use register_secrets tool for OTP + curl."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import config
from app import db
from app import identity
from app import secret_otp_bundle

__version__ = "1.0.0"
TOOL_ID = "secrets_help"
TOOL_DOMAIN = "secrets"
TOOL_TRIGGERS = ()


def secrets_help(arguments: dict[str, Any]) -> str:
    """Static help for user secrets: OTP only via register_secrets; no OTP is minted here."""
    raw_svc = secret_otp_bundle.normalize_service_key(
        arguments.get("service_key_example")
    )
    topic = (arguments.get("topic") or "").strip().lower()

    base = config.PUBLIC_BASE_URL or f"http://127.0.0.1:{config.HTTP_EXAMPLE_PORT}"
    user_hdr = (
        config.USER_SUB_HEADERS[0] if config.USER_SUB_HEADERS else "X-OpenWebUI-User-Id"
    )

    _tid, uid = identity.get_identity()
    resolved_sub = db.user_external_sub(uid)
    user_value = resolved_sub if resolved_sub is not None else "DEINE_WEBUI_USER_ID"

    hints: list[str] = [
        "Neues Secret speichern: **nur** Tool `register_secrets` — in der Antwort stehen `curl_bash` und ggf. `jq_register_example_de` (OTP ist schon eingebaut).",
        "Dieses Tool (`secrets_help`) erzeugt **kein** OTP und keinen curl — nur Erklärung.",
        "Gespeicherte `service_key`-Namen auflisten oder einen Key löschen: HTTP `GET`/`DELETE` `/v1/user/secrets` mit denselben User-Headern wie der Chat (optional Bearer `AGENT_API_KEY`) — siehe TOOLS.md.",
    ]
    if topic in ("email", "imap", "mail", "gmail"):
        hints.append(
            "Gmail: Google-Konto → App-Passwort; `service_key` z. B. `gmail` oder `email_imap`."
        )
    if topic in ("github", "gh", "pat"):
        hints.append(
            'GitHub: `service_key` `github_pat` — JSON `{"token":"…"}` oder Operator setzt `GITHUB_TOKEN` in docker/.env für alle Nutzer.'
        )
    if topic in ("calendar", "ics", "caldav", "nextcloud"):
        hints.append(
            'Kalender read-only: `calendar_ics` oder `google_calendar` mit JSON `{"ics_url":"https://…"}` — '
            "Google: Einstellungen → geheime iCal-Adresse (`calendar.google.com/.../basic.ics`)."
        )
    if topic in ("google", "gcal", "google_calendar"):
        hints.append(
            'Google Kalender: `register_secrets` mit `service_key_example: "google_calendar"`; Secret = iCal-URL aus den Google-Kalendereinstellungen.'
        )

    return json.dumps(
        {
            "ok": True,
            "otp_only_from_register_secrets_de": (
                "Ein **OTP** und der fertige **`curl_bash`** kommen **ausschließlich** aus der Tool-Antwort von "
                "`register_secrets`. **`secrets_help` ruft das Backend nicht an** und erzeugt **kein** OTP."
            ),
            "when_backend_emits_otp_de": (
                "Wenn dein Modell keine `tool_calls` sendet (Log z. B. „no tool_calls and content fallback missed“), "
                "wird `register_secrets` nicht ausgeführt → **kein** OTP. Dann größeres Modell mit Tool-Calling nutzen oder "
                "`AGENT_CONTENT_TOOL_FALLBACK`/Prompt anpassen."
            ),
            "gmail_save_use_this_tool": "register_secrets",
            "gmail_save_example_args": {"service_key_example": "gmail"},
            "google_calendar_save_example_args": {
                "service_key_example": "google_calendar"
            },
            "service_key_example": raw_svc,
            "base_url_used": base,
            "user_header": user_hdr,
            "resolved_user_id": uid,
            "resolved_external_sub": user_value,
            "for_llm_de": (
                "Neues Secret speichern: **nur** `register_secrets` mit passendem `service_key_example` "
                "(gmail, google_calendar, github_pat, …). Dem Nutzer **nur** `curl_bash` / `jq_register_example_de` "
                "aus **dieser** Antwort geben — nichts erfinden. Klartext-Secrets und iCal-URLs **nie** in den Chat."
            ),
            "common_mistakes_de": [
                "Falsch: `secrets_help` aufrufen und erwarten, dass ein OTP oder curl erscheint.",
                "Falsch: Geheime iCal-URL oder Passwörter in den Chat schreiben — nur lokal im Terminal im curl/jq.",
            ],
            "preferred_flow_de": (
                "`register_secrets` → Nutzer führt `curl_bash` (eine Zeile) lokal aus → HTTP-Antwort `stored:true`. "
                "Danach z. B. `calendar_ics_list_events` für Google-Kalender."
            ),
            "steps_de": [
                "Tool `register_secrets` mit JSON-Argumenten aufrufen, z. B. "
                '`{"service_key_example":"google_calendar"}` oder `{"service_key_example":"gmail"}`.',
                "Aus der **Tool-Antwort** `curl_bash` oder `jq_register_example_de` kopieren, Platzhalter lokal ersetzen, ausführen.",
                "Bei Google-Kalender: in `secret` die komplette https-URL (`…/basic.ics`) einsetzen (nur im Terminal).",
            ],
            "list_delete_note_de": (
                "Gespeicherte Keys auflisten oder löschen: REST `GET` bzw. `DELETE /v1/user/secrets` "
                "mit User-Header wie beim Chat; bei gesetztem `AGENT_API_KEY` Header "
                "`Authorization: Bearer <AGENT_API_KEY>`. Details: TOOLS.md."
            ),
            "hints": hints,
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "secrets_help": secrets_help,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "secrets_help",
            "TOOL_DESCRIPTION": (
                "Static help for user secrets: explains that OTP and curl_bash come ONLY from register_secrets — "
                "this tool does NOT mint an OTP. To save Gmail, google_calendar, github_pat, etc., the model must "
                "call register_secrets and pass the returned curl_bash to the user. "
                "Returns steps_de, google_calendar_save_example_args, list_delete_note_de (REST for list/delete), hints."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_key_example": {
                        "type": "string",
                        "TOOL_DESCRIPTION": (
                            "Example service_key name for hints only (lowercase [a-z0-9._-]), "
                            "e.g. gmail, google_calendar, github_pat"
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "TOOL_DESCRIPTION": (
                            "Optional hint: email, imap, mail, gmail, github, google, gcal, calendar, ics, or generic"
                        ),
                    },
                },
            },
        },
    },
]
