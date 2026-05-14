"""Semantic search + LLM-grounded answers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_auth
from app.models.schemas import (
    AskRequest,
    AskResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services import indexer
from app.services.llm_providers import get_active_provider


router = APIRouter(prefix="/api", tags=["search"], dependencies=[Depends(require_auth)])


SNIPPET_LEN = 320

ASK_SYSTEM_PROMPT = (
    "You are an assistant answering the user's questions using ONLY their personal notes "
    "provided as context. Follow these rules:\n"
    "- Base every claim on the supplied notes; if the notes don't cover it, say so.\n"
    "- Be concise. Prefer 1-3 short paragraphs over a long essay.\n"
    "- When you reference a note, mention its title in plain text (no markdown links).\n"
    "- If the notes contradict each other, point that out.\n"
    "- Do not invent facts, dates, names, or numbers."
)


def _to_item(hit: dict) -> SearchResultItem:
    return SearchResultItem(
        id=hit["id"],
        title=hit.get("title", "") or "(untitled)",
        path=hit.get("path", ""),
        snippet=(hit.get("text", "") or "")[:SNIPPET_LEN].strip(),
        score=hit.get("score", 0.0),
        type=hit.get("type", ""),
        source=hit.get("source", ""),
        date=hit.get("date", ""),
        category=hit.get("category", ""),
        tags=hit.get("tags", []) or [],
    )


@router.post("/search", response_model=SearchResponse)
def do_search(req: SearchRequest) -> SearchResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    filters = {k: v for k, v in {"type": req.type, "source": req.source, "category": req.category}.items() if v}
    try:
        hits = indexer.search(query, limit=max(1, min(req.limit, 50)), filters=filters)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")
    return SearchResponse(results=[_to_item(h) for h in hits])


@router.post("/ask", response_model=AskResponse)
def do_ask(req: AskRequest) -> AskResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        hits = indexer.search(question, limit=max(1, min(req.limit, 12)))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")

    if not hits:
        return AskResponse(
            answer="I couldn't find anything relevant in your notes for that question.",
            sources=[],
        )

    context_blocks = []
    for h in hits:
        title = h.get("title") or "(untitled)"
        path = h.get("path") or ""
        body = (h.get("text") or "").strip()
        context_blocks.append(f"### {title}  ({path})\n{body}")
    context_text = "\n\n---\n\n".join(context_blocks)

    user_prompt = (
        f"The user asked: {question}\n\n"
        f"Here are the relevant notes from their vault:\n\n{context_text}\n\n"
        f"Answer the question using only those notes."
    )

    try:
        provider = get_active_provider()
        answer = provider.complete(prompt=user_prompt, system=ASK_SYSTEM_PROMPT)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    return AskResponse(
        answer=answer.strip() or "(empty answer)",
        sources=[_to_item(h) for h in hits],
    )
