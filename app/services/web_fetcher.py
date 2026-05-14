"""Fetch a URL and extract title + main text content."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SecondBrain/1.0; +https://github.com/) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchedPage(TypedDict):
    url: str
    title: str
    text: str
    fetched_at: str


def fetch(url: str, timeout: float = 15.0, max_chars: int = 30000) -> FetchedPage:
    """Fetch URL, return title + extracted main text. Raises httpx.HTTPError on failure."""
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text
        final_url = str(response.url)

    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        title = final_url

    # Strip noise that's never real content
    for tag in soup(
        ["script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript", "svg"]
    ):
        tag.decompose()

    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="content")
        or soup.find(id="main")
        or soup.body
        or soup
    )
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[…truncated…]"

    return {
        "url": final_url,
        "title": title,
        "text": text,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
