"""Step 2: upload the scraped Markdown files to an OpenAI vector store via the API.

Only new/changed articles are uploaded (see kbsync/vector_store.py).
Usage:  python upload.py [--dir articles] [--no-prune]
"""
import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from kbsync.vector_store import VectorStoreSync, load_docs


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=os.getenv("OUTPUT_DIR", "articles"))
    ap.add_argument("--no-prune", action="store_true", help="keep store files whose article is not in --dir")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        logging.error("Set OPENAI_API_KEY (or API_KEY)")
        return 2

    docs = load_docs(args.dir)
    if not docs:
        logging.error("No .md files in %s/ - run scrape.py first", args.dir)
        return 1

    sync = VectorStoreSync(
        OpenAI(api_key=api_key),
        vector_store_id=os.getenv("VECTOR_STORE_ID") or None,
        name=os.getenv("VECTOR_STORE_NAME", "optibot-kb"),
    )
    stats = sync.sync(docs, prune=not args.no_prune)
    logging.info(
        "Embedded %d files / ~%d chunks (added=%d updated=%d skipped=%d removed=%d failed=%d). "
        "Store now holds %d files / ~%d chunks.",
        stats["files_embedded"], stats["chunks_embedded"], stats["added"], stats["updated"],
        stats["skipped"], stats["removed"], stats["failed"], stats["total_files"], stats["total_chunks"],
    )
    logging.info("OpenAI reports the store's files as %s, size %s bytes",
                 stats["store_file_counts"], stats["store_usage_bytes"])
    print(json.dumps(stats, indent=2))
    logging.info("Vector store id: %s  (put it in .env as VECTOR_STORE_ID)", stats["vector_store_id"])
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
