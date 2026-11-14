"""Fetch help-center articles through the public Zendesk Help Center API and save them as Markdown."""
from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests

from .cleaner import html_to_markdown

log = logging.getLogger(__name__)

PAGE_SIZE = 100  # Zendesk max


@dataclass
class Article:
    id: int
    title: str
    url: str          # public html_url
    updated_at: str   # Zendesk "Last-Modified" equivalent
    slug: str
    markdown: str

    @property
    def filename(self) -> str:
        return f"{self.slug}.md"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.markdown.encode("utf-8")).hexdigest()


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "article"


def render_article(raw: dict) -> Article:
    """Turn one Zendesk article JSON object into an Article with a clean Markdown document."""
    title = (raw.get("title") or "").strip()
    url = raw.get("html_url") or ""
    body = html_to_markdown(raw.get("body") or "")
    # Header and footer both carry the URL so any retrieved chunk can be cited.
    doc = f"# {title}\n\nArticle URL: {url}\n\n{body}\n---\nArticle URL: {url}\n"
    return Article(
        id=int(raw["id"]),
        title=title,
        url=url,
        updated_at=raw.get("updated_at") or raw.get("edited_at") or "",
        slug=f"{raw['id']}-{slugify(title)}",
        markdown=doc,
    )


class HelpCenterClient:
    def __init__(self, base_url: str, locale: str = "en-us", session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.locale = locale
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "kb-sync/1.0")

    def _get(self, url: str, params: dict | None = None, retries: int = 4) -> dict:
        for attempt in range(retries):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                log.warning("HTTP %s from %s, retrying in %ss", resp.status_code, url, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        raise RuntimeError(f"giving up on {url}")

    def iter_raw_articles(self, limit: int = 0):
        url = f"{self.base_url}/api/v2/help_center/{self.locale}/articles.json"
        params = {"per_page": PAGE_SIZE, "sort_by": "created_at", "sort_order": "asc"}
        count = 0
        while url:
            data = self._get(url, params)
            params = None  # next_page already contains the query string
            for raw in data.get("articles", []):
                if raw.get("draft"):
                    continue
                yield raw
                count += 1
                if limit and count >= limit:
                    return
            url = data.get("next_page")

    def fetch_articles(self, limit: int = 0) -> list[Article]:
        return [render_article(raw) for raw in self.iter_raw_articles(limit)]


def save_articles(articles: list[Article], out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for a in articles:
        p = out / a.filename
        p.write_text(a.markdown, encoding="utf-8")
        paths.append(p)
    return paths
