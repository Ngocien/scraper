"""HTML -> clean Markdown conversion for Zendesk help-center article bodies.

Goals:
  * keep headings, lists, tables, images, code blocks and links (relative links stay relative)
  * drop navigation, ads, scripts, share/vote widgets and other page chrome
  * produce stable output so the same article always hashes the same
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Tag
from markdownify import MarkdownConverter

# Tags that never carry article content.
DROP_TAGS = [
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "button", "input", "select", "textarea", "svg", "link", "meta",
]

# class/id fragments that mark page chrome or ads.
CHROME_PATTERN = re.compile(
    r"(^|[-_\s])(nav|navbar|breadcrumbs?|sidebar|ads?|advert\w*|banner|promo\w*|cookie\w*|"
    r"share|social|vote|votes|comments?|related\w*|recent-articles|subscribe|"
    r"article-footer|article-relatives|search)([-_\s]|$)",
    re.I,
)

VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "wistia", "loom.com")
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)


class _Converter(MarkdownConverter):
    """markdownify converter with fenced code blocks that keep their language."""

    def convert_pre(self, el, text, parent_tags):
        lang = _code_language(el)
        code = el.get_text()  # raw text, no markdown escaping inside code
        code = code.strip("\n")
        return f"\n\n```{lang}\n{code}\n```\n\n"


def _code_language(el: Tag) -> str:
    for node in [el, *el.find_all("code")]:
        for cls in node.get("class", []) or []:
            m = re.match(r"(?:language|lang)-([\w+#-]+)", cls)
            if m:
                return m.group(1).lower()
    return ""


def _is_chrome(tag: Tag) -> bool:
    if tag.attrs is None:
        return False
    if tag.get("role") in {"navigation", "banner", "complementary", "contentinfo"}:
        return True
    marker = " ".join(tag.get("class", []) or []) + " " + (tag.get("id") or "")
    return bool(marker.strip()) and bool(CHROME_PATTERN.search(marker))


def clean_html(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")

    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.parent is not None and _is_chrome(tag):
            tag.decompose()

    # Embedded videos/iframes -> a plain link so the information survives.
    for iframe in soup.find_all(["iframe", "video", "embed"]):
        src = iframe.get("src") or ""
        if not src:
            source = iframe.find("source")
            src = source.get("src", "") if source else ""
        if src.startswith("//"):
            src = "https:" + src
        if src:
            label = "Embedded video" if any(h in src for h in VIDEO_HOSTS) else "Embedded content"
            a = soup.new_tag("a", href=src)
            a.string = label
            p = soup.new_tag("p")
            p.append(a)
            iframe.replace_with(p)
        else:
            iframe.decompose()

    # Article title is rendered separately as the only H1 -> demote body headings if needed.
    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    if any(h.name == "h1" for h in headings):
        for h in headings:
            h.name = f"h{min(int(h.name[1]) + 1, 6)}"

    # Drop empty paragraphs / headings (Zendesk editor leaves lots of <p>&nbsp;</p>).
    for tag in soup.find_all(["p", "h2", "h3", "h4", "h5", "h6", "div", "span", "strong", "em"]):
        if not tag.get_text(strip=True).replace("\xa0", "") and not tag.find(["img", "a", "iframe", "table", "pre"]):
            tag.decompose()

    return soup


def html_to_markdown(html: str) -> str:
    soup = clean_html(html)
    md = _Converter(
        heading_style="ATX",
        bullets="-",
        escape_underscores=False,
        strip=["span", "font", "u"],
        table_infer_header=True,
    ).convert_soup(soup)
    return normalize_markdown(md)


def normalize_markdown(md: str) -> str:
    md = md.translate(ZERO_WIDTH).replace("\xa0", " ")
    out, in_code = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        out.append(line if in_code else line.rstrip())
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)  # collapse blank runs
    return md.strip() + "\n"
