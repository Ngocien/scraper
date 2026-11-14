import json
from pathlib import Path

from kbsync.cleaner import html_to_markdown
from kbsync.scraper import HelpCenterClient, render_article, save_articles, slugify

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


class FakeResp:
    def __init__(self, data):
        self._data, self.status_code, self.headers = data, 200, {}

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages, self.headers, self.calls = pages, {}, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        return FakeResp(self.pages.pop(0))


def article_md():
    return render_article(load("page1.json")["articles"][0]).markdown


def test_removes_nav_ads_scripts_and_widgets():
    md = article_md()
    for junk in ("BUY NOW", "track()", "Was this helpful", "Home"):
        assert junk not in md


def test_headings_title_is_only_h1():
    md = article_md()
    assert md.startswith("# How to add a YouTube video\n")
    assert md.count("\n# ") == 0  # body h1 demoted
    assert "## Overview" in md and "### Steps" in md


def test_relative_links_and_images_preserved():
    md = article_md()
    assert "[Apps page](/hc/en-us/articles/123-Apps)" in md
    assert "![YouTube app](/hc/article_attachments/1/yt.png)" in md


def test_code_block_fenced_with_language_and_unescaped():
    md = article_md()
    assert '```json\n{"autoplay": true, "my_key": 1}\n```' in md
    assert "`pair_code`" in html_to_markdown("<p><code>pair_code</code></p>")


def test_iframe_becomes_link_and_lists_tables_kept():
    md = article_md()
    assert "[Embedded video](https://www.youtube.com/embed/abc123)" in md
    assert "1. Open the" in md
    assert "| Plan | Supported |" in md


def test_article_url_in_header_and_footer_and_no_blank_runs():
    md = article_md()
    assert md.count("Article URL: https://support.optisigns.com/hc/en-us/articles/360051014954") == 2
    assert "\n\n\n" not in md


def test_hash_is_stable():
    raw = load("page1.json")["articles"][0]
    assert render_article(raw).content_hash == render_article(raw).content_hash


def test_slugify():
    assert slugify("Pairing a Screen – Quick Start!") == "pairing-a-screen-quick-start"


def test_pagination_skips_drafts_and_respects_limit(tmp_path):
    client = HelpCenterClient("https://h", session=FakeSession([load("page1.json"), load("page2.json")]))
    arts = client.fetch_articles()
    assert [a.id for a in arts] == [360051014954, 3]
    assert len(client.session.calls) == 2

    client = HelpCenterClient("https://h", session=FakeSession([load("page1.json")]))
    assert len(client.fetch_articles(limit=1)) == 1

    paths = save_articles(arts, tmp_path)
    assert sorted(p.name for p in paths) == ["3-pairing-a-screen-quick-start.md",
                                              "360051014954-how-to-add-a-youtube-video.md"]
