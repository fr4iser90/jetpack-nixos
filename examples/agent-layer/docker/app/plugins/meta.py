"""Meta-tools: list all registered tools and show help for one tool."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any, Callable

from .. import config
from .. import db
from .. import identity
from ..registry import get_registry

__version__ = "1.4.3"
PLUGIN_ID = "meta"


def list_available_tools(arguments: dict[str, Any]) -> str:
    """Return every tool name, description, and JSON Schema parameters (as registered)."""
    _ = arguments
    reg = get_registry()
    tools_out: list[dict[str, Any]] = []
    for spec in reg.openai_tools:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        tools_out.append(
            {
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
            }
        )
    return json.dumps(
        {
            "ok": True,
            "count": len(tools_out),
            "tools": tools_out,
            "hint": "Use get_tool_help with a tool name for one schema in full, or call a tool with JSON args per parameters.properties / required.",
        },
        ensure_ascii=False,
    )


def get_tool_help(arguments: dict[str, Any]) -> str:
    """Return full description + parameter schema for a single tool."""
    name = (arguments.get("tool_name") or "").strip()
    if not name:
        return json.dumps({"ok": False, "error": "tool_name is required"})
    reg = get_registry()
    for spec in reg.openai_tools:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        if fn.get("name") != name:
            continue
        return json.dumps(
            {
                "ok": True,
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
                "how_to_use": (
                    "The model calls this tool with a JSON object matching "
                    "`parameters.properties`; required keys are in `parameters.required`."
                ),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": False,
            "error": f"unknown tool: {name}",
            "hint": "Call list_available_tools for valid names.",
        },
        ensure_ascii=False,
    )


_SERVICE_KEY_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


def register_secrets(arguments: dict[str, Any]) -> str:
    """
    Mint a one-time code bound to the current chat user; return a bash-safe curl that only needs
    the secret placeholder replaced (no Bearer / user headers for the end user).
    """
    if not config.SECRETS_MASTER_KEY:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "Speichern ist auf dem Server nicht aktiviert: Betreiber muss einmalig "
                    "AGENT_SECRETS_MASTER_KEY in docker/.env setzen (Verschlüsselung in Postgres — "
                    "Endnutzer tragen das nie ein). Siehe TOOLS.md."
                ),
            },
            ensure_ascii=False,
        )
    raw_svc = (arguments.get("service_key_example") or "email_imap").strip().lower()
    if not _SERVICE_KEY_SAFE.fullmatch(raw_svc):
        raw_svc = "email_imap"
    ttl = 600
    raw_ttl = arguments.get("ttl_seconds")
    if isinstance(raw_ttl, (int, float)):
        t = int(raw_ttl)
        if 120 <= t <= 3600:
            ttl = t

    _tid, uid = identity.get_identity()
    otp = db.secret_upload_otp_create(uid, ttl_seconds=ttl)
    base = config.PUBLIC_BASE_URL or f"http://127.0.0.1:{config.HTTP_EXAMPLE_PORT}"
    if raw_svc == "gmail":
        secret_blob = '{"email":"du@gmail.com","app_password":"DEIN_APP_PASSWORT"}'
    else:
        secret_blob = "DEIN_SECRET_TEXT"
    body_str = json.dumps(
        {"otp": otp, "service_key": raw_svc, "secret": secret_blob},
        ensure_ascii=False,
    )
    url = f"{base}/v1/user/secrets/register-with-otp"
    curl_bash = (
        f"curl -sS -X POST {shlex.quote(url)} "
        f"-H {shlex.quote('Content-Type: application/json')} "
        f"--data-raw {shlex.quote(body_str)}"
    )

    return json.dumps(
        {
            "ok": True,
            "expires_in_seconds": ttl,
            "service_key": raw_svc,
            "resolved_user_id": uid,
            "curl_bash": curl_bash,
            "steps_de": (
                [
                    "Befehl `curl_bash` im Terminal einfügen und ausführen.",
                    "Vorher im JSON-Feld `secret` die Platzhalter durch echte Werte ersetzen (Editor lokal — nie in den Chat).",
                    "Für service_key `gmail`: `secret` muss JSON sein: "
                    '`{"email":"…","app_password":"…"}` (Google App-Passwort, 2FA voraus).',
                ]
                if raw_svc == "gmail"
                else [
                    "Befehl `curl_bash` im Terminal einfügen und ausführen.",
                    "Vorher nur den `secret`-Wert im JSON durch den echten Token/Passwort-Text ersetzen (lokal — nie in den Chat).",
                ]
            ),
            "security_de": (
                "Das OTP steht im Chat und verknüpft den Upload mit deinem Account. Wer deinen Chat mitlesen kann, "
                "könnte es missbrauchen — Befehl zeitnah ausführen; OTP ist einmalig und läuft ab."
            ),
            "operator_note_de": (
                "AGENT_SECRETS_MASTER_KEY ist nur Server-Konfiguration (Fernet), kein Wert für Nutzer im Chat."
            ),
        },
        ensure_ascii=False,
    )


def secrets_help(arguments: dict[str, Any]) -> str:
    """Return help: points to register_secrets (OTP) + legacy curl for list/delete / header POST."""
    raw_svc = (arguments.get("service_key_example") or "email_imap").strip().lower()
    if not _SERVICE_KEY_SAFE.fullmatch(raw_svc):
        raw_svc = "email_imap"
    topic = (arguments.get("topic") or "").strip().lower()

    base = config.PUBLIC_BASE_URL or f"http://127.0.0.1:{config.HTTP_EXAMPLE_PORT}"
    user_hdr = config.USER_SUB_HEADERS[0] if config.USER_SUB_HEADERS else "X-OpenWebUI-User-Id"

    _tid, uid = identity.get_identity()
    resolved_sub = db.user_external_sub(uid)
    user_value = resolved_sub if resolved_sub is not None else "DEINE_WEBUI_USER_ID"

    bearer_line = '  -H "Authorization: Bearer $AGENT_API_KEY" \\\n'
    curl_post_ready_lines = [
        f'curl -sS -X POST "{base}/v1/user/secrets" \\\n',
    ]
    if config.OPTIONAL_API_KEY:
        curl_post_ready_lines.append(bearer_line)
    curl_post_ready_lines.extend(
        [
            f'  -H "{user_hdr}: {user_value}" \\\n',
            f'  -H "Content-Type: application/json" \\\n',
            f"  -d '{{\"service_key\":\"{raw_svc}\",\"secret\":\"HIER_GMAIL_APP_PASSWORT_ODER_TOKEN\"}}'",
        ]
    )
    curl_post_ready = "".join(curl_post_ready_lines)

    curl_list_ready_lines = [f'curl -sS "{base}/v1/user/secrets" \\\n']
    if config.OPTIONAL_API_KEY:
        curl_list_ready_lines.append(bearer_line)
    curl_list_ready_lines.append(f'  -H "{user_hdr}: {user_value}"')
    curl_list_ready = "".join(curl_list_ready_lines)

    curl_del_ready_lines = [
        f'curl -sS -X DELETE "{base}/v1/user/secrets/{raw_svc}" \\\n',
    ]
    if config.OPTIONAL_API_KEY:
        curl_del_ready_lines.append(bearer_line)
    curl_del_ready_lines.append(f'  -H "{user_hdr}: {user_value}"')
    curl_del_ready = "".join(curl_del_ready_lines)

    hints: list[str] = [
        "**Empfohlen:** Tool `register_secrets` — fertiger `curl` mit OTP, nur noch App-Passwort ersetzen.",
        "Legacy: `curl_post_ready` braucht User-Header (vorausgefüllt) "
        + ("und Bearer `$AGENT_API_KEY` (Open WebUI / docker `.env`)." if config.OPTIONAL_API_KEY else "(kein AGENT_API_KEY am Server)."),
        "Listen/Löschen über GET/DELETE `/v1/user/secrets` — gleiche Header; Betreiber: siehe TOOLS.md.",
    ]
    if topic in ("email", "imap", "mail", "gmail"):
        hints.append("Gmail: Google-Konto → App-Passwort; `service_key` z. B. `gmail` oder `email_imap`.")

    return json.dumps(
        {
            "ok": True,
            "when_backend_emits_otp_de": (
                "Das Backend erzeugt ein OTP **nur** in der **Tool-Antwort** von `register_secrets` "
                "(Feld `curl_bash` enthält OTP + URL). `secrets_help` erzeugt **kein** OTP — es ist nur Hilfstext. "
                "Wenn dein Modell keine `tool_calls` sendet (Log z. B. „no tool_calls and content fallback missed“), "
                "wird **kein** Tool ausgeführt → **kein** OTP. Dann größeres Modell mit Tool-Calling nutzen oder "
                "`AGENT_CONTENT_TOOL_FALLBACK`/Prompt anpassen."
            ),
            "gmail_save_use_this_tool": "register_secrets",
            "gmail_save_example_args": {"service_key_example": "gmail"},
            "service_key_example": raw_svc,
            "base_url_used": base,
            "user_header": user_hdr,
            "resolved_user_id": uid,
            "resolved_external_sub": user_value,
            "for_llm_de": (
                "Neues Secret (Gmail usw.) speichern: **zuerst** `register_secrets` mit passendem "
                "`service_key_example` (z. B. gmail) aufrufen und dem Nutzer **nur** `curl_bash` aus dieser Antwort geben. "
                "**Nicht** selbst `curl` mit `DEIN_AGENT_API_KEY` erfinden; **niemals** die Open-WebUI-User-ID in "
                "`Authorization: Bearer` setzen (Bearer = nur `AGENT_API_KEY`, falls der Server einen verlangt — OTP-Flow braucht keinen)."
            ),
            "common_mistakes_de": [
                "Falsch: `Authorization: Bearer` = WebUI-User-ID — die steht nur im Header "
                f"`{user_hdr}` (hier schon `{user_value}` in `curl_*_ready`).",
                "Falsch: `echo \"curl …\"` — Nutzer soll den echten `curl` aus `register_secrets` → `curl_bash` kopieren.",
            ],
            "preferred_flow_de": (
                "Modell soll `register_secrets` aufrufen — Nutzer kopiert `curl_bash` und ersetzt nur "
                "`DEIN_GMAIL_APP_PASSWORT`. Kein gemeinsamer API-Key für Endnutzer nötig."
            ),
            "steps_de": [
                "`register_secrets` mit z. B. `service_key_example: \"gmail\"` aufrufen.",
                "Aus der Antwort `curl_bash` kopieren, Passwort-Platzhalter lokal ersetzen, im Terminal ausführen.",
            ],
            "curl_post_ready": curl_post_ready,
            "curl_list_ready": curl_list_ready,
            "curl_delete_ready": curl_del_ready,
            "curl_post": curl_post_ready,
            "curl_list": curl_list_ready,
            "curl_del": curl_del_ready,
            "aliases_note_de": (
                "`curl_post` / `curl_list` / `curl_del` = gleicher Text wie `curl_*_ready` (Legacy-Namen). "
                "Neu speichern: `register_secrets` (OTP)."
            ),
            "hints": hints,
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "list_available_tools": list_available_tools,
    "get_tool_help": get_tool_help,
    "register_secrets": register_secrets,
    "secrets_help": secrets_help,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_available_tools",
            "description": (
                "Lists all tools this agent can run: name, short description, and JSON parameter schema. "
                "Use when the user asks what you can do, which tools exist, or how to get started."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tool_help",
            "description": (
                "Returns full help for one tool: description and parameter schema. "
                "Use when the user asks how to use a specific tool by name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Exact tool name, e.g. create_todo, search_web",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_secrets",
            "description": (
                "Register/store one user secret (Gmail app password, API token, OAuth secret, etc.) for CLI upload. "
                "Returns curl_bash with a fresh one-time OTP in the JSON body; user copies that line and replaces only "
                "DEIN_GMAIL_APP_PASSWORT locally — no Bearer token. Pass service_key_example e.g. gmail. "
                "Do not invent alternate curl or put WebUI user id in Authorization. Never paste real secrets into chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_key_example": {
                        "type": "string",
                        "description": (
                            "Logical name for this secret (lowercase [a-z0-9._-]), e.g. gmail, email_imap, github_pat"
                        ),
                    },
                    "ttl_seconds": {
                        "type": "integer",
                        "description": "Optional OTP lifetime 120–3600 (default 600).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "secrets_help",
            "description": (
                "Help for user secrets: overview, list/delete curl templates, and legacy header-based POST. "
                "Does NOT mint an OTP. To save a new secret, call register_secrets first and give the user curl_bash from that response. "
                "NEVER tell the user to put Open WebUI user id in Authorization Bearer (Bearer is AGENT_API_KEY only when the server uses it). "
                "Returns curl_list_ready / curl_delete_ready and hints in common_mistakes_de / for_llm_de."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_key_example": {
                        "type": "string",
                        "description": (
                            "Example service_key for legacy POST body (lowercase [a-z0-9._-]), "
                            "e.g. email_imap, github_pat, brave_api"
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional hint: email, imap, mail, gmail, github, or generic",
                    },
                },
            },
        },
    },
]
