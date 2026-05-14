"""ChatGPT conversations.json parser.

Format: a JSON array of conversation objects. Each has a `mapping` of node_id →
{message, parent, children}. We follow `current_node` back to the root and then
reverse, which gives us the actual conversation path the user saw (handles edits/branches).
"""

from __future__ import annotations

from typing import Any

from app.parsers._common import NormalizedConversation, load_json, parse_date


def parse(data: bytes | str | list | dict) -> list[NormalizedConversation]:
    raw = load_json(data)
    if not isinstance(raw, list):
        raise ValueError("ChatGPT export should be a JSON array of conversations")

    out: list[NormalizedConversation] = []
    for conv in raw:
        if not isinstance(conv, dict):
            continue
        try:
            normalized = _parse_conversation(conv)
            if normalized and normalized["messages"]:
                out.append(normalized)
        except Exception:
            # Don't let one malformed conversation kill the whole import
            continue
    return out


def _parse_conversation(conv: dict) -> NormalizedConversation | None:
    title = (conv.get("title") or "Untitled chat").strip() or "Untitled chat"
    date = parse_date(conv.get("create_time")) or parse_date(conv.get("update_time"))
    source_id = str(conv.get("id") or conv.get("conversation_id") or "")

    mapping = conv.get("mapping") or {}
    if not isinstance(mapping, dict) or not mapping:
        return None

    nodes = _path_through_tree(mapping, conv.get("current_node"))

    messages = []
    for node in nodes:
        msg = (node or {}).get("message")
        if not isinstance(msg, dict):
            continue
        author = ((msg.get("author") or {}).get("role") or "").lower()
        if author not in ("user", "assistant"):
            continue
        content = msg.get("content") or {}
        ctype = content.get("content_type")
        if ctype not in (None, "text"):
            # Skip code-interpreter / multimodal / tether for now
            continue
        parts = content.get("parts") or []
        text = "\n\n".join(str(p) for p in parts if p).strip()
        if not text:
            continue
        messages.append({"role": author, "content": text})

    return {
        "source_id": source_id,
        "title": title,
        "date": date,
        "messages": messages,
    }


def _path_through_tree(mapping: dict, current_node: Any) -> list[dict]:
    """Walk current_node → parent → … → root, then reverse. If no current_node,
    take a left-most descent from the first root."""
    if isinstance(current_node, str) and current_node in mapping:
        path: list[dict] = []
        node_id: Any = current_node
        seen: set[str] = set()
        while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            node = mapping[node_id]
            path.append(node)
            node_id = (node or {}).get("parent")
        path.reverse()
        return path

    # Fallback: find a root and descend through first child
    roots = [n for n in mapping.values() if isinstance(n, dict) and not n.get("parent")]
    if not roots:
        return []
    descent: list[dict] = []
    node = roots[0]
    seen2: set[str] = set()
    while node:
        nid = node.get("id")
        if nid in seen2:
            break
        if nid:
            seen2.add(nid)
        descent.append(node)
        children = node.get("children") or []
        if not children:
            break
        next_id = children[0]
        node = mapping.get(next_id) if isinstance(next_id, str) else None
    return descent
