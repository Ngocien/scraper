"""End-to-end test of main.py with the Zendesk API and OpenAI faked out."""
import json
from pathlib import Path

import pytest

import main as job
from kbsync import scraper
from tests.test_scraper import FakeSession, load
from tests.test_vector_store import FakeOpenAI


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for var in ("VECTOR_STORE_ID", "MAX_ARTICLES", "OUTPUT_DIR", "LOG_DIR"):
        monkeypatch.delenv(var, raising=False)
    pages = {"value": []}
    monkeypatch.setattr(scraper.requests, "Session",
                        lambda: FakeSession(list(pages["value"])))
    openai = FakeOpenAI()
    return tmp_path, pages, openai


def run_job(pages, openai, raw_pages):
    pages["value"] = raw_pages
    code = job.main([], client_factory=lambda api_key: openai)
    return code, json.loads(Path("logs/last_run.json").read_text())


def test_daily_runs_upload_only_the_delta(env):
    tmp, pages, openai = env
    p1, p2 = load("page1.json"), load("page2.json")

    code, r = run_job(pages, openai, [p1, p2])
    assert code == 0 and r["status"] == "ok"
    assert (r["added"], r["updated"], r["skipped"]) == (2, 0, 0)
    assert len(list((tmp / "articles").glob("*.md"))) == 2
    assert "added=2 updated=0 skipped=0" in (tmp / "logs/last_run.log").read_text()

    code, r = run_job(pages, openai, [load("page1.json"), load("page2.json")])
    assert (r["added"], r["updated"], r["skipped"]) == (0, 0, 2)

    p2 = load("page2.json")
    p2["articles"][0]["body"] = "<p>Enter the new code.</p>"
    p1 = load("page1.json")
    p1["articles"].append({"id": 7, "html_url": "https://h/7", "title": "New one", "draft": False,
                           "body": "<p>new</p>"})
    code, r = run_job(pages, openai, [p1, p2])
    assert (r["added"], r["updated"], r["skipped"]) == (1, 1, 1)


def test_removed_article_is_pruned_from_store_and_disk(env):
    tmp, pages, openai = env
    run_job(pages, openai, [load("page1.json"), load("page2.json")])
    p1 = load("page1.json")
    p1["next_page"] = None
    code, r = run_job(pages, openai, [p1])
    assert r["removed"] == 1
    assert [p.name for p in (tmp / "articles").glob("*.md")] == ["360051014954-how-to-add-a-youtube-video.md"]


def test_missing_key_fails_with_artefact(env, monkeypatch):
    _, pages, openai = env
    monkeypatch.delenv("OPENAI_API_KEY")
    pages["value"] = [load("page1.json"), load("page2.json")]
    assert job.main([]) == 1
    r = json.loads(Path("logs/last_run.json").read_text())
    assert r["status"] == "error" and "API_KEY" in r["error"]


def test_api_key_alias_and_scrape_only(env, monkeypatch):
    _, pages, openai = env
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("API_KEY", "sk-alias")
    seen = {}
    pages["value"] = [load("page1.json"), load("page2.json")]
    assert job.main([], client_factory=lambda api_key: seen.setdefault("k", api_key) and openai) == 0
    assert seen["k"] == "sk-alias"

    pages["value"] = [load("page1.json"), load("page2.json")]
    assert job.main(["--scrape-only"]) == 0
