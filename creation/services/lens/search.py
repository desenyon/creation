"""Lens — first-party research: web search and page extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus

import httpx

from creation.config import UserSecrets


@dataclass
class SearchHit:
    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass
class LensBundle:
    query: str
    hits: List[SearchHit] = field(default_factory=list)
    answer: Optional[str] = None

    def to_context_block(self) -> str:
        lines = [f"## Lens research: {self.query}"]
        if self.answer:
            lines.append(f"**Synthesis:** {self.answer}")
        for i, h in enumerate(self.hits[:8], 1):
            lines.append(f"\n### [{i}] {h.title}\n{h.url}\n{h.content[:1200]}")
        return "\n".join(lines)


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class LensSearch:
    """DuckDuckGo + lightweight HTTP extraction — no third-party API keys."""

    def __init__(self, secrets: UserSecrets, demo: bool = False):
        self.secrets = secrets
        self.demo = demo

    def search_ideas(self, seed: str = "") -> LensBundle:
        query = seed.strip() or "best micro-SaaS software ideas to build in 2026 AI agents"
        if self.demo:
            return LensBundle(
                query=query,
                answer=(
                    "Local dev tools, agent memory layers, and vertical workflow automation "
                    "are strong opportunities for autonomous builders."
                ),
                hits=[
                    SearchHit(
                        "AI agent tooling gap",
                        "https://creation.dev/research/agents",
                        "Builders need local-first agent stacks with built-in QA loops.",
                        0.92,
                    ),
                    SearchHit(
                        "Micro-SaaS for developers",
                        "https://creation.dev/research/saas",
                        "CLI-first tools with native GitHub and Linear sync win distribution.",
                        0.88,
                    ),
                ],
            )
        hits = self._ddg_search(query)
        answer = hits[0].content[:400] if hits else None
        return LensBundle(query=query, hits=hits, answer=answer)

    def refine_idea(self, idea: str) -> LensBundle:
        return self.search_ideas(f"market validation and competitors for: {idea}")

    def _ddg_search(self, query: str, max_results: int = 8) -> List[SearchHit]:
        try:
            from duckduckgo_search import DDGS

            results: List[SearchHit] = []
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    results.append(
                        SearchHit(
                            title=str(item.get("title") or ""),
                            url=str(item.get("href") or item.get("link") or ""),
                            content=str(item.get("body") or item.get("snippet") or ""),
                            score=0.8,
                        )
                    )
            return results
        except Exception:
            return self._ddg_html_fallback(query, max_results)

    def _ddg_html_fallback(self, query: str, max_results: int) -> List[SearchHit]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            resp = httpx.get(url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
        except Exception:
            return []
        hits: List[SearchHit] = []
        for block in re.findall(r'class="result__body".*?</div>\s*</div>', html, flags=re.S)[:max_results]:
            title_m = re.search(r'class="result__a"[^>]*>([^<]+)', block)
            link_m = re.search(r'class="result__url"[^>]*>([^<]+)', block)
            snippet_m = re.search(r'class="result__snippet"[^>]*>([^<]+)', block)
            if title_m:
                hits.append(
                    SearchHit(
                        title=title_m.group(1).strip(),
                        url=link_m.group(1).strip() if link_m else "",
                        content=snippet_m.group(1).strip() if snippet_m else "",
                        score=0.7,
                    )
                )
        return hits


class LensScrape:
    """Fetch and extract readable text from URLs."""

    def __init__(self, secrets: UserSecrets, demo: bool = False):
        self.secrets = secrets
        self.demo = demo

    def scrape_urls(self, urls: List[str], max_pages: int = 6) -> LensBundle:
        pages: List[SearchHit] = []
        if self.demo:
            for i, url in enumerate(urls[:max_pages], 1):
                pages.append(
                    SearchHit(
                        title=f"Demo page {i}",
                        url=url,
                        content=f"Demo scrape of {url}. Competitor positioning and feature notes.",
                        score=0.9,
                    )
                )
            return LensBundle(query="scrape", hits=pages, answer="Demo competitor scan complete.")

        for url in urls[:max_pages]:
            if not url.startswith("http"):
                continue
            try:
                resp = httpx.get(
                    url,
                    timeout=20.0,
                    follow_redirects=True,
                    headers={"User-Agent": "Creation-Lens/1.0"},
                )
                text = _strip_html(resp.text)
                title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", resp.text)
                title = title_m.group(1).strip() if title_m else url
                pages.append(SearchHit(title=title, url=url, content=text[:4000], score=0.85))
            except Exception:
                continue
        return LensBundle(query="scrape", hits=pages, answer=f"Scraped {len(pages)} pages.")
