"""Daily job: re-scrape the help center, upload only new/changed articles, log the counts.

    python main.py                 # full run (needs OPENAI_API_KEY or API_KEY)
    python main.py --scrape-only   # just refresh articles/ (no API key needed)

Writes logs/last_run.log and logs/last_run.json (the run artefact). Exit code 0 = success.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from kbsync.scraper import Article, HelpCenterClient, save_articles
from kbsync.vector_store import Doc, VectorStoreSync

log = logging.getLogger("main")


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in [h for h in root.handlers if getattr(h, "_kbsync", False)]:
        root.removeHandler(h)
        h.close()
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / "last_run.log", mode="w")):
        handler.setFormatter(fmt)
        handler._kbsync = True
        root.addHandler(handler)
    for noisy in ("httpx", "httpx2", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def to_doc(a: Article) -> Doc:
    return Doc(article_id=str(a.id), filename=a.filename, content=a.markdown,
               url=a.url, title=a.title, updated_at=a.updated_at)


def write_articles(articles: list[Article], out_dir: Path, full: bool) -> None:
    """Save Markdown; on a full scrape also delete files of articles that no longer exist."""
    if full and out_dir.exists():
        keep = {a.filename for a in articles}
        for old in out_dir.glob("*.md"):
            if old.name not in keep:
                old.unlink()
    save_articles(articles, out_dir)


def run(args, client_factory=None) -> dict:
    started = time.monotonic()
    limit = args.limit
    full = limit == 0

    hc = HelpCenterClient(os.getenv("HELP_CENTER_URL", "https://support.optisigns.com"),
                          os.getenv("HELP_CENTER_LOCALE", "en-us"))
    articles = hc.fetch_articles(limit=limit)
    if not articles:
        raise RuntimeError("scraper returned 0 articles")
    write_articles(articles, Path(args.out), full)
    log.info("Scraped %d articles -> %s/", len(articles), args.out)

    result = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "scraped": len(articles)}
    if args.scrape_only:
        result["upload"] = "skipped (--scrape-only)"
    else:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
        if not api_key:
            raise RuntimeError("set OPENAI_API_KEY (or API_KEY), or use --scrape-only")
        if client_factory is None:
            from openai import OpenAI
            client_factory = OpenAI
        sync = VectorStoreSync(client_factory(api_key=api_key),
                               vector_store_id=os.getenv("VECTOR_STORE_ID") or None,
                               name=os.getenv("VECTOR_STORE_NAME", "optibot-kb"))
        # Only prune articles missing from the site when we scraped the whole site.
        stats = sync.sync([to_doc(a) for a in articles], prune=full)
        result.update(stats)
        log.info("added=%d updated=%d skipped=%d removed=%d failed=%d",
                 stats["added"], stats["updated"], stats["skipped"], stats["removed"], stats["failed"])
        log.info("Embedded %d files / ~%d chunks this run; store holds %d files / ~%d chunks (OpenAI: %s)",
                 stats["files_embedded"], stats["chunks_embedded"], stats["total_files"],
                 stats["total_chunks"], stats["store_file_counts"])

    result["duration_s"] = round(time.monotonic() - started, 1)
    return result


def main(argv=None, client_factory=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=int(os.getenv("MAX_ARTICLES", "0")), help="0 = all")
    ap.add_argument("--out", default=os.getenv("OUTPUT_DIR", "articles"))
    ap.add_argument("--log-dir", default=os.getenv("LOG_DIR", "logs"))
    ap.add_argument("--scrape-only", action="store_true")
    args = ap.parse_args(argv)

    log_dir = Path(args.log_dir)
    setup_logging(log_dir)
    try:
        result = run(args, client_factory)
        result["status"] = "ok" if not result.get("failed") else "partial"
    except Exception as exc:
        log.exception("Run failed")
        result = {"status": "error", "error": str(exc)}
    (log_dir / "last_run.json").write_text(json.dumps(result, indent=2))
    log.info("Run %s; artefact: %s", result["status"], log_dir / "last_run.json")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
