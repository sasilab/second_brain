"""Claude conversations.json parser.

Claude's export is a JSON array of conversation objects. Each has `chat_messages`
where each message has `sender` ("human" | "assistant") and either a `text` field
or a `content` list of typed blocks.
"""

from __future__ import annotations

from app.parsers._common import (
    NormalizedConversation,
    load_json,
    parse_date,
    strip_unsupported_blocks,
)


def parse(data: bytes | str | list | dict) -> list[NormalizedConversation]:
    raw = load_json(data)
    # Accept both [convs] and {conversations: [convs]} (and a couple of other key names)
    if isinstance(raw, dict):
        raw = (
            raw.get("conversations")
            or raw.get("data")
            or raw.get("chats")
            or []
        )
    if not isinstance(raw, list):
        raise ValueError("Claude export: expected an array of conversations")

    out: list[NormalizedConversation] = []
    for conv in raw:
        if not isinstance(conv, dict):
            continue
        try:
            normalized = _parse_conversation(conv)
            if normalized and normalized["messages"]:
                out.append(normalized)
        except Exception:
            continue
    return out


def _parse_conversation(conv: dict) -> NormalizedConversation | None:
    title = (conv.get("name") or conv.get("title") or "Untitled chat").strip() or "Untitled chat"
    source_id = str(conv.get("uuid") or conv.get("id") or "")

    date = (
        parse_date(conv.get("created_at"))
        or parse_date(conv.get("create_time"))
        or parse_date(conv.get("createdAt"))
        or parse_date(conv.get("updated_at"))
    )

    raw_messages = conv.get("chat_messages") or conv.get("messages") or []
    if not isinstance(raw_messages, list):
        return None

    messages = []
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        sender = (msg.get("sender") or msg.get("role") or "").lower()
        if sender in ("human", "user"):
            role = "user"
        elif sender in ("assistant", "claude", "model"):
            role = "assistant"
        else:
            continue

        text = (msg.get("text") or "").strip()
        if not text and isinstance(msg.get("content"), list):
            parts = []
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
            text = "\n\n".join(p for p in parts if p).strip()
        elif not text and isinstance(msg.get("content"), str):
            text = msg["content"].strip()

        text = strip_unsupported_blocks(text)
        if not text:
            continue
        messages.append({"role": role, "content": text})

    return {
        "source_id": source_id,
        "title": title,
        "date": date,
        "messages": messages,
    }
