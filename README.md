# quill-relay

Help-center → Markdown → vector store sync for the OptiBot support assistant.

## Step 1 – Scrape ⇒ Markdown

Articles come from the public Zendesk Help Center API
(`/api/v2/help_center/en-us/articles.json`, 100 per page, `next_page` paging, drafts skipped).
Each article body is cleaned and saved as `articles/<id>-<slug>.md`.

**Cleaning rules (`kbsync/cleaner.py`):**
- Removes scripts, styles, nav/header/footer/aside, forms, and widgets whose class or id marks them as page chrome (breadcrumbs, ads, banners, votes, comments, related articles, share).
- Keeps headings. The article title is the only `#`; any `<h1>` inside the body moves down one level.
- Keeps links and images exactly as written, so relative links stay relative.
- Turns `<pre>` blocks into fenced code blocks and keeps the `language-*` class as the fence language.
- Replaces YouTube/Vimeo iframes with a link. Removes empty `<p>&nbsp;</p>` blocks, zero-width characters and runs of blank lines.
- Puts an `Article URL:` line at the top and bottom of every file, so the assistant can cite the article from any retrieved chunk.

### Setup & run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.sample .env
python scrape.py            # all articles  (use --limit 40 for a quick run)
pytest -q
```
