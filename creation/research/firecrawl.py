"""Firecrawl shim — use Creation Lens scrape instead."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from creation.config import UserSecrets
from creation.services.lens.search import LensScrape, SearchHit


@dataclass
class CrawlPage:
    url: str
    title: str = ""
    markdown: str = ""


@dataclass
class FirecrawlBundle:
    pages: List[CrawlPage] = field(default_factory=list)

    def to_context_block(self) -> str:
        lines = ["## Lens deep scrape"]
        for i, p in enumerate(self.pages[:6], 1):
            lines.append(f"\n### [{i}] {p.title or p.url}\n{p.url}\n{p.markdown[:2000]}")
        return "\n".join(lines)


class FirecrawlResearch:
    def __init__(self, secrets: UserSecrets, demo: bool = False, composio: object | None = None):
        self._lens = LensScrape(secrets, demo=demo)

    def scrape_urls(self, urls: List[str]) -> FirecrawlBundle:
        return self.crawl_from_urls(urls)

    def crawl_from_urls(self, urls: List[str]) -> FirecrawlBundle:
        bundle = self._lens.scrape_urls(urls)
        pages = [
            CrawlPage(url=h.url, title=h.title, markdown=h.content)
            for h in bundle.hits
        ]
        return FirecrawlBundle(pages=pages)

    def batch_scrape(self, urls: List[str]) -> FirecrawlBundle:
        return self.crawl_from_urls(urls)
