"""Upload Markdown articles to an OpenAI vector store, sending only what changed.

State lives in the vector store itself: every attached file carries attributes
`article_id` and `content_hash`. A run lists the store's files, compares hashes with the
freshly scraped Markdown and then:
  * added   -> article id not in the store            -> upload + attach
  * updated -> article id present, hash differs        -> upload new, attach, remove old
  * skipped -> same hash                               -> nothing
  * removed -> in the store but no longer on the site  -> detach + delete (full scrapes only)
No local state file is needed, so the daily job can run in a throwaway container.
"""
from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import CHUNKING_STRATEGY, estimate_chunks

log = logging.getLogger(__name__)

URL_RE = re.compile(r"^Article URL:\s*(\S+)", re.M)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.M)


@dataclass
class Doc:
    article_id: str
    filename: str
    content: str
    url: str = ""
    title: str = ""

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def attributes(self) -> dict:
        # OpenAI limits: <=16 keys, string values <=512 chars.
        return {
            "article_id": self.article_id,
            "content_hash": self.content_hash,
            "url": self.url[:512],
            "title": self.title[:512],
        }


def load_docs(folder: str | Path) -> list[Doc]:
    """Read `<id>-<slug>.md` files written by the scraper."""
    docs = []
    for path in sorted(Path(folder).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        url = URL_RE.search(text)
        title = TITLE_RE.search(text)
        docs.append(Doc(
            article_id=path.stem.split("-", 1)[0],
            filename=path.name,
            content=text,
            url=url.group(1) if url else "",
            title=title.group(1).strip() if title else path.stem,
        ))
    return docs


@dataclass
class RemoteFile:
    file_id: str
    article_id: str
    content_hash: str


@dataclass
class Plan:
    added: list[Doc] = field(default_factory=list)
    updated: list[tuple[Doc, RemoteFile]] = field(default_factory=list)
    skipped: list[Doc] = field(default_factory=list)
    removed: list[RemoteFile] = field(default_factory=list)


def plan_delta(docs: list[Doc], remote: list[RemoteFile], prune: bool = True) -> Plan:
    by_id: dict[str, RemoteFile] = {}
    plan = Plan()
    for r in remote:
        if r.article_id in by_id:  # duplicate from an interrupted run -> clean it up
            plan.removed.append(r)
        else:
            by_id[r.article_id] = r
    seen = set()
    for d in docs:
        seen.add(d.article_id)
        r = by_id.get(d.article_id)
        if r is None:
            plan.added.append(d)
        elif r.content_hash != d.content_hash:
            plan.updated.append((d, r))
        else:
            plan.skipped.append(d)
    if prune:
        plan.removed.extend(r for aid, r in by_id.items() if aid not in seen)
    return plan


def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(vars(obj))


class VectorStoreSync:
    def __init__(self, client, vector_store_id: str | None = None, name: str = "optibot-kb", workers: int = 8):
        self.client = client
        self.name = name
        self.workers = workers
        self.vector_store_id = vector_store_id or self._find_or_create_store()

    # --- store ------------------------------------------------------------
    def _find_or_create_store(self) -> str:
        for vs in self.client.vector_stores.list(limit=100):
            if vs.name == self.name:
                log.info("Using existing vector store %s (%s)", vs.name, vs.id)
                return vs.id
        vs = self.client.vector_stores.create(name=self.name, chunking_strategy=CHUNKING_STRATEGY)
        log.info("Created vector store %s (%s)", vs.name, vs.id)
        return vs.id

    def remote_files(self) -> list[RemoteFile]:
        out = []
        for f in self.client.vector_stores.files.list(vector_store_id=self.vector_store_id, limit=100):
            attrs = f.attributes or {}
            if f.status == "failed" or "article_id" not in attrs:
                # Unknown or broken file: make it look stale so it gets replaced/removed.
                out.append(RemoteFile(f.id, str(attrs.get("article_id", f"?{f.id}")), ""))
            else:
                out.append(RemoteFile(f.id, str(attrs["article_id"]), str(attrs.get("content_hash", ""))))
        return out

    # --- file operations -----------------------------------------------------
    def _upload(self, doc: Doc) -> str:
        uploaded = self.client.files.create(
            file=(doc.filename, doc.content.encode("utf-8"), "text/markdown"),
            purpose="assistants",
        )
        vs_file = self.client.vector_stores.files.create_and_poll(
            vector_store_id=self.vector_store_id,
            file_id=uploaded.id,
            attributes=doc.attributes,
            chunking_strategy=CHUNKING_STRATEGY,
        )
        if vs_file.status != "completed":
            raise RuntimeError(f"{doc.filename}: embedding {vs_file.status} {getattr(vs_file, 'last_error', '')}")
        return uploaded.id

    def _remove(self, file_id: str) -> None:
        self.client.vector_stores.files.delete(file_id=file_id, vector_store_id=self.vector_store_id)
        try:
            self.client.files.delete(file_id)
        except Exception as exc:  # already gone is fine
            log.debug("files.delete(%s): %s", file_id, exc)

    def _replace(self, item: tuple[Doc, RemoteFile]) -> str:
        doc, old = item
        new_id = self._upload(doc)  # upload first so the article is never missing
        self._remove(old.file_id)
        return new_id

    # --- main entry ----------------------------------------------------------
    def sync(self, docs: list[Doc], prune: bool = True) -> dict:
        plan = plan_delta(docs, self.remote_files(), prune=prune)
        failures: list[str] = []

        def run(fn, items, label, name_of):
            ok = []
            with ThreadPoolExecutor(self.workers) as pool:
                futures = [(item, pool.submit(fn, item)) for item in items]
                for item, fut in futures:
                    try:
                        fut.result()
                        ok.append(item)
                    except Exception as exc:
                        log.error("%s failed for %s: %s", label, name_of(item), exc)
                        failures.append(f"{label}:{name_of(item)}")
            return ok

        added = run(self._upload, plan.added, "add", lambda d: d.filename)
        updated = run(self._replace, plan.updated, "update", lambda i: i[0].filename)
        removed = run(lambda r: self._remove(r.file_id), plan.removed, "remove", lambda r: r.file_id)

        embedded = added + [d for d, _ in updated]  # only the uploads that succeeded
        store = self.client.vector_stores.retrieve(self.vector_store_id)
        return {
            "vector_store_id": self.vector_store_id,
            "added": len(added),
            "updated": len(updated),
            "skipped": len(plan.skipped),
            "removed": len(removed),
            "failed": len(failures),
            "failures": failures,
            "files_embedded": len(embedded),
            "chunks_embedded": sum(estimate_chunks(d.content) for d in embedded),
            # Reported by OpenAI, as a cross-check of the local numbers.
            "store_file_counts": _as_dict(getattr(store, "file_counts", None)),
            "store_usage_bytes": getattr(store, "usage_bytes", None),
            "total_files": len(docs),
            "total_chunks": sum(estimate_chunks(d.content) for d in docs),
        }
