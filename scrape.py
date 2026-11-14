"""Step 1: scrape the help center and write one clean Markdown file per article.

Usage:  python scrape.py [--limit N] [--out DIR]
"""
import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from kbsync.scraper import HelpCenterClient, save_articles


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=int(os.getenv("MAX_ARTICLES", "0")), help="0 = all")
    ap.add_argument("--out", default=os.getenv("OUTPUT_DIR", "articles"))
    ap.add_argument("--base-url", default=os.getenv("HELP_CENTER_URL", "https://support.optisigns.com"))
    ap.add_argument("--locale", default=os.getenv("HELP_CENTER_LOCALE", "en-us"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = HelpCenterClient(args.base_url, args.locale)
    articles = client.fetch_articles(limit=args.limit)
    paths = save_articles(articles, args.out)
    logging.info("Scraped %d articles -> %s/", len(paths), args.out)
    return 0 if paths else 1


if __name__ == "__main__":
    sys.exit(main())
