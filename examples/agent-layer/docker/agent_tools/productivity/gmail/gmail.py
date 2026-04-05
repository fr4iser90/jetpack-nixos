"""Gmail via IMAP (Google App Password). User secret ``gmail`` — see module docstring."""

from __future__ import annotations

import imaplib
import json
import re
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from typing import Any, Callable

from app import db
from app import identity

__version__ = "1.0.1"
TOOL_ID = "gmail"
TOOL_DOMAIN = "gmail"
TOOL_TRIGGERS = (
    "gmail",
    "imap",
    "inbox",
    "e-mail",
    "email",
    "mailbox",
    "app password",
)
TOOL_LABEL = "Gmail"
TOOL_DESCRIPTION = (
    "Read and search Gmail over IMAP using the per-user `gmail` app-password secret."
)

# Stored via register_secrets / POST user/secrets — this tool reads it server-side only.
SECRET_SERVICE_KEY = "gmail"

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# JSON body for service_key ``gmail`` (one object):
# {
#   "email": "you@gmail.com",
#   "app_password": "xxxx xxxx xxxx xxxx"
# }
# Create App Password: Google Account → Security → 2-Step Verification → App passwords.


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    chunks: list[str] = []
    for text, enc in parts:
        if isinstance(text, bytes):
            chunks.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            chunks.append(str(text))
    return "".join(chunks)


def _parse_gmail_secret(raw: str | None) -> dict[str, str] | None:
    if not raw or not raw.strip():
        return None
    try:
        obj = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    email = str(obj.get("email") or "").strip()
    pw = (
        str(obj.get("app_password") or obj.get("password") or "")
        .strip()
        .replace(" ", "")
    )
    if not email or not pw:
        return None
    return {"email": email, "app_password": pw}


def _creds_for_user() -> dict[str, str] | str:
    _tid, uid = identity.get_identity()
    raw = db.user_secret_get_plaintext(uid, SECRET_SERVICE_KEY)
    if not raw:
        return (
            f"No Gmail secret for this user. Call register_secrets with service_key_example "
            f'"{SECRET_SERVICE_KEY}" and store JSON: '
            '{{"email":"you@gmail.com","app_password":"<16-char app password>"}}'
        )
    parsed = _parse_gmail_secret(raw)
    if not parsed:
        return (
            "Invalid gmail secret: expected JSON "
            '{"email":"you@gmail.com","app_password":"xxxx"} '
            "(app_password may include spaces; they are stripped)."
        )
    return parsed


def _sanitize_raw_query(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return "in:anywhere"
    q = re.sub(r'["\\\x00\r\n]', " ", q)
    return q[:800] or "in:anywhere"


def _connect(cfg: dict[str, str]) -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    m.login(cfg["email"], cfg["app_password"])
    return m


def _select(mail: imaplib.IMAP4_SSL, mailbox: str) -> str | None:
    mb = (mailbox or "INBOX").strip() or "INBOX"
    typ, _ = mail.select(mb, readonly=True)
    if typ != "OK":
        return f"cannot select mailbox {mb!r}"
    return None


def _uids_from_search(
    mail: imaplib.IMAP4_SSL, gmail_query: str, limit: int
) -> list[bytes]:
    q = _sanitize_raw_query(gmail_query)
    limit = max(1, min(int(limit or 20), 50))
    typ, data = mail.uid("SEARCH", None, "X-GM-RAW", f'"{q}"')
    if typ != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()
    if len(uids) > limit:
        uids = uids[-limit:]
    return list(reversed(uids))


def _header_message(raw_header: bytes) -> Message:
    return message_from_bytes(raw_header)


def _body_text_plain(msg: Message, max_chars: int) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain" and not part.get_filename():
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        t = payload.decode("utf-8", errors="replace")
                        return t[:max_chars] if len(t) > max_chars else t
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
        if not payload:
            return ""
        t = payload.decode("utf-8", errors="replace")
        return t[:max_chars] if len(t) > max_chars else t
    except Exception:
        return ""


def gmail_search(arguments: dict[str, Any]) -> str:
    """Search mailbox using Gmail search syntax (IMAP X-GM-RAW)."""
    creds = _creds_for_user()
    if isinstance(creds, str):
        return json.dumps({"ok": False, "error": creds}, ensure_ascii=False)

    q = (arguments.get("gmail_query") or arguments.get("query") or "").strip()
    if not q:
        return json.dumps(
            {"ok": False, "error": "gmail_query is required"}, ensure_ascii=False
        )
    mailbox = (arguments.get("mailbox") or "INBOX").strip() or "INBOX"
    try:
        limit = int(arguments.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20

    try:
        mail = _connect(creds)
    except imaplib.IMAP4.error as e:
        return json.dumps(
            {"ok": False, "error": f"IMAP login failed: {e!s}"}, ensure_ascii=False
        )

    try:
        err = _select(mail, mailbox)
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        uids = _uids_from_search(mail, q, limit)
        rows: list[dict[str, Any]] = []
        for uidb in uids:
            uid_s = (
                uidb.decode("ascii", errors="replace")
                if isinstance(uidb, bytes)
                else str(uidb)
            )
            typ, data = mail.uid(
                "FETCH", uid_s, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] UID)"
            )
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            raw = data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            h = _header_message(bytes(raw))
            rows.append(
                {
                    "uid": int(uid_s),
                    "from": _decode_header_value(h.get("From")),
                    "subject": _decode_header_value(h.get("Subject")),
                    "date": _decode_header_value(h.get("Date")),
                }
            )
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    out: dict[str, Any] = {
        "ok": True,
        "credentials_ok": True,
        "mailbox": mailbox,
        "gmail_query": q,
        "count": len(rows),
        "messages": rows,
        "hint": "Use gmail_read with uid from a row to fetch full text.",
    }
    if not rows:
        out["empty_result_note_de"] = (
            "IMAP-Anmeldung und Suche liefen; es gab **keine Treffer** für diese Gmail-Abfrage. "
            "Das ist **nicht** dasselbe wie „kein Secret“ (dann wäre ok:false mit error). "
            "Query verfeinern, z. B. `angel`, `subject:angel`, `in:anywhere angel`, `newer_than:30d`."
        )
    return json.dumps(out, ensure_ascii=False)


def gmail_read(arguments: dict[str, Any]) -> str:
    """Fetch one message by IMAP UID (from gmail_search)."""
    creds = _creds_for_user()
    if isinstance(creds, str):
        return json.dumps({"ok": False, "error": creds}, ensure_ascii=False)

    try:
        uid = int(arguments.get("uid"))
    except (TypeError, ValueError):
        return json.dumps(
            {"ok": False, "error": "uid is required (integer)"}, ensure_ascii=False
        )

    mailbox = (arguments.get("mailbox") or "INBOX").strip() or "INBOX"
    try:
        max_body = int(arguments.get("max_body_chars") or 24000)
    except (TypeError, ValueError):
        max_body = 24000
    max_body = max(1000, min(max_body, 100000))

    try:
        mail = _connect(creds)
    except imaplib.IMAP4.error as e:
        return json.dumps(
            {"ok": False, "error": f"IMAP login failed: {e!s}"}, ensure_ascii=False
        )

    try:
        err = _select(mail, mailbox)
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        typ, data = mail.uid("FETCH", str(uid), "(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return json.dumps(
                {"ok": False, "error": f"no message uid={uid}"}, ensure_ascii=False
            )
        raw = data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            return json.dumps({"ok": False, "error": "empty body"}, ensure_ascii=False)
        msg = message_from_bytes(bytes(raw))
        body = _body_text_plain(msg, max_body)
        return json.dumps(
            {
                "ok": True,
                "uid": uid,
                "mailbox": mailbox,
                "from": _decode_header_value(msg.get("From")),
                "to": _decode_header_value(msg.get("To")),
                "subject": _decode_header_value(msg.get("Subject")),
                "date": _decode_header_value(msg.get("Date")),
                "body_text": body,
                "truncated": len(body) >= max_body,
            },
            ensure_ascii=False,
        )
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def gmail_collect_for_summary(arguments: dict[str, Any]) -> str:
    """Fetch several messages (search + bodies); model summarizes the combined excerpts for the user."""
    creds = _creds_for_user()
    if isinstance(creds, str):
        return json.dumps({"ok": False, "error": creds}, ensure_ascii=False)

    q = (arguments.get("gmail_query") or arguments.get("query") or "").strip()
    if not q:
        return json.dumps(
            {"ok": False, "error": "gmail_query is required"}, ensure_ascii=False
        )
    mailbox = (arguments.get("mailbox") or "INBOX").strip() or "INBOX"
    try:
        max_msg = int(arguments.get("max_messages") or 8)
    except (TypeError, ValueError):
        max_msg = 8
    max_msg = max(1, min(max_msg, 15))
    try:
        per = int(arguments.get("max_chars_per_message") or 6000)
    except (TypeError, ValueError):
        per = 6000
    per = max(500, min(per, 20000))

    try:
        mail = _connect(creds)
    except imaplib.IMAP4.error as e:
        return json.dumps(
            {"ok": False, "error": f"IMAP login failed: {e!s}"}, ensure_ascii=False
        )

    blocks: list[str] = []
    try:
        err = _select(mail, mailbox)
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        uids = _uids_from_search(mail, q, max_msg)
        if not uids:
            return json.dumps(
                {
                    "ok": True,
                    "count": 0,
                    "combined_excerpt": "",
                    "hint": "No messages matched.",
                },
                ensure_ascii=False,
            )
        for uidb in uids:
            uid_s = (
                uidb.decode("ascii", errors="replace")
                if isinstance(uidb, bytes)
                else str(uidb)
            )
            typ, data = mail.uid("FETCH", uid_s, "(RFC822)")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            raw = data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = message_from_bytes(bytes(raw))
            uid_int = int(uidb.decode() if isinstance(uidb, bytes) else uidb)
            subj = _decode_header_value(msg.get("Subject"))
            frm = _decode_header_value(msg.get("From"))
            dt = _decode_header_value(msg.get("Date"))
            body = _body_text_plain(msg, per)
            blocks.append(
                f"---\nUID: {uid_int}\nFrom: {frm}\nDate: {dt}\nSubject: {subj}\n\n{body}\n"
            )
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    combined = "\n".join(blocks)
    return json.dumps(
        {
            "ok": True,
            "mailbox": mailbox,
            "gmail_query": q,
            "count": len(blocks),
            "combined_excerpt": combined,
            "instruction_de": (
                "Fasse combined_excerpt für den Nutzer in klaren Stichpunkten zusammen; keine vollständigen Zitate "
                "von Passwörtern oder personenbezogenen Daten wiederholen, wenn nicht nötig."
            ),
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "gmail_search": gmail_search,
    "gmail_read": gmail_read,
    "gmail_collect_for_summary": gmail_collect_for_summary,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "gmail_search",
            "TOOL_DESCRIPTION": (
                "Search the user's Gmail (IMAP) with Gmail web-style query syntax, e.g. "
                "from:alice newer_than:7d subject:invoice is:unread. "
                f"Requires per-user secret `{SECRET_SERVICE_KEY}` JSON (email + app_password). "
                "Returns message uids and headers; use gmail_read for full body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gmail_query": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Gmail search query (X-GM-RAW), e.g. from:github is:unread newer_than:14d",
                    },
                    "mailbox": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "IMAP mailbox name, default INBOX",
                    },
                    "limit": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max messages to return (1–50, default 20)",
                    },
                },
                "required": ["gmail_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_read",
            "TOOL_DESCRIPTION": (
                "Read one email by IMAP UID (from gmail_search). Returns plain-text body (truncated). "
                f"Secret `{SECRET_SERVICE_KEY}` must be set."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "IMAP UID from gmail_search",
                    },
                    "mailbox": {"type": "string", "TOOL_DESCRIPTION": "Default INBOX"},
                    "max_body_chars": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max characters of body text (default 24000, max 100000)",
                    },
                },
                "required": ["uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_collect_for_summary",
            "TOOL_DESCRIPTION": (
                "Search Gmail and fetch plain-text excerpts from several messages into combined_excerpt. "
                "You (the assistant) should then summarize for the user in natural language. "
                f"Requires secret `{SECRET_SERVICE_KEY}`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gmail_query": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Same as gmail_search (Gmail query syntax)",
                    },
                    "mailbox": {"type": "string", "TOOL_DESCRIPTION": "Default INBOX"},
                    "max_messages": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "How many messages to include (1–15, default 8)",
                    },
                    "max_chars_per_message": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Truncate each body (default 6000)",
                    },
                },
                "required": ["gmail_query"],
            },
        },
    },
]
