"""Chat completion with tool-call loop against Ollama OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import uuid
from json import JSONDecoder
from typing import Any

import httpx

from . import config
from .registry import get_registry
from .tools import run_tool

logger = logging.getLogger(__name__)


def _inject_system_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not config.SYSTEM_PROMPT_EXTRA:
        return messages
    extra = config.SYSTEM_PROMPT_EXTRA
    if not messages:
        return [{"role": "system", "content": extra}]
    out = list(messages)
    if out[0].get("role") == "system":
        existing = out[0].get("content") or ""
        out[0] = {
            **out[0],
            "content": (existing + "\n\n" + extra).strip() if existing else extra,
        }
    else:
        out.insert(0, {"role": "system", "content": extra})
    return out


def _tool_spec_name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    fn = entry.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


def _merge_tools(body_tools: list[Any] | None) -> list[Any]:
    """
    Always send registry tools to Ollama (create_todo, …).

    Open WebUI often sends its own non-empty ``tools`` list; previously that
    replaced our list entirely so the model never saw agent-layer tools.
    """
    ours = get_registry().openai_tools
    if not body_tools:
        return ours
    seen = {n for t in ours if (n := _tool_spec_name(t))}
    merged: list[Any] = list(ours)
    for t in body_tools:
        if not isinstance(t, dict):
            continue
        n = _tool_spec_name(t)
        if n is None:
            merged.append(t)
            continue
        if n not in seen:
            merged.append(t)
            seen.add(n)
    logger.debug(
        "tools merge: registry=%d client=%d merged=%d",
        len(ours),
        len(body_tools),
        len(merged),
    )
    return merged


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid tool arguments JSON: %s", raw[:200])
        return {}


def _unwrap_fenced_json(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if not lines:
        return t
    lines = lines[1:]
    while lines and lines[-1].strip() in ("```", ""):
        lines.pop()
    return "\n".join(lines).strip()


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _end = JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _known_tool_names() -> set[str]:
    return {n for t in get_registry().openai_tools if (n := _tool_spec_name(t))}


def _parse_tool_intent_from_content(content: str) -> tuple[str, dict[str, Any]] | None:
    """
    Models like nemotron-3-nano emit {\"tool\": \"create_todo\", \"parameters\": {...}} in content
    instead of OpenAI-style tool_calls.
    """
    obj = _extract_first_json_object(_unwrap_fenced_json(content))
    if not obj:
        return None
    name: str | None = None
    params: dict[str, Any] | None = None
    if isinstance(obj.get("tool"), str):
        name = obj["tool"]
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        if isinstance(p, dict):
            params = p
    elif isinstance(obj.get("name"), str):
        name = obj["name"]
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        if isinstance(p, dict):
            params = p
    elif isinstance(obj.get("function"), str):
        name = obj["function"]
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        if isinstance(p, dict):
            params = p
    if not name or params is None:
        return None
    return name, params


def _text_blobs_from_message(msg: dict[str, Any]) -> list[str]:
    """Collect strings where models may hide JSON tool intent (reasoning models, multimodal content)."""
    blobs: list[str] = []
    t = msg.get("text")
    if isinstance(t, str) and t.strip():
        blobs.append(t)
    c = msg.get("content")
    if isinstance(c, str) and c.strip():
        blobs.append(c)
    elif isinstance(c, list):
        for part in c:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    blobs.append(part["text"])
                elif isinstance(part.get("content"), str):
                    blobs.append(part["content"])
            elif isinstance(part, str):
                blobs.append(part)
    for key in (
        "reasoning_content",
        "reasoning",
        "thinking",
        "thought",
        "reasoning_content_delta",  # some proxies
    ):
        v = msg.get(key)
        if isinstance(v, str) and v.strip():
            blobs.append(v)
    return blobs


def _synthetic_tool_calls_from_message(
    msg: dict[str, Any],
    choice: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    if not config.CONTENT_TOOL_FALLBACK:
        return None
    if msg.get("tool_calls"):
        return None
    known = _known_tool_names()
    blobs = _text_blobs_from_message(msg)
    if choice:
        for key in ("thought", "reasoning", "thinking"):
            v = choice.get(key)
            if isinstance(v, str) and v.strip():
                blobs.append(v)
    for blob in blobs:
        parsed = _parse_tool_intent_from_content(blob)
        if not parsed:
            continue
        name, params = parsed
        if name not in known:
            logger.debug("content tool JSON names unknown tool %r, ignoring", name)
            continue
        tc = {
            "id": f"content-{uuid.uuid4().hex[:16]}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(params)},
        }
        logger.info(
            "content tool fallback: treating assistant JSON as tool_calls for %s(%s)",
            name,
            params,
        )
        return [tc]
    logger.debug(
        "content tool fallback: no tool JSON found (message keys=%s, blobs=%d)",
        list(msg.keys()),
        len(blobs),
    )
    return None


async def chat_completion(body: dict[str, Any]) -> dict[str, Any]:
    # stream flag is ignored here; Ollama always gets stream=false. Caller may wrap JSON as SSE.
    model = body.get("model")
    if not model:
        raise ValueError("missing model")

    messages = _inject_system_prompt(list(body.get("messages") or []))
    tools = _merge_tools(body.get("tools"))
    if tools:
        names = [n for t in tools if (n := _tool_spec_name(t))]
        logger.info("forwarding %d tools to Ollama: %s", len(names), names)
    options = {k: v for k, v in body.items() if k not in ("messages", "model", "tools", "stream")}

    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=600.0) as client:
        for round_i in range(config.MAX_TOOL_ROUNDS):
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
                **options,
            }
            if tools:
                payload["tools"] = tools

            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            choice0 = (data.get("choices") or [{}])[0]
            raw_msg = choice0.get("message")
            if not isinstance(raw_msg, dict):
                raw_msg = {}
            msg = dict(raw_msg)
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                tool_calls = _synthetic_tool_calls_from_message(msg, choice0)
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                    choice0["message"] = msg

            if not tool_calls:
                if tools:
                    logger.warning(
                        "no tool_calls and content fallback missed (model=%s message_keys=%s)",
                        model,
                        list(msg.keys()),
                    )
                return data

            # Append assistant message (includes tool_calls, and content if any)
            messages.append(msg)

            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                args = _parse_tool_arguments(fn.get("arguments"))
                tool_call_id = tc.get("id") or ""
                logger.info("tool round %s: %s(%s)", round_i + 1, name, args)
                result = run_tool(name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    }
                )

        logger.warning("max tool rounds (%s) exceeded", config.MAX_TOOL_ROUNDS)
        return data
