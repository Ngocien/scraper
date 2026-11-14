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

## Step 2 – Upload to the OpenAI vector store (API only)

```bash
cp .env.sample .env        # set OPENAI_API_KEY
python scrape.py
python upload.py           # prints the vector store id; put it in .env as VECTOR_STORE_ID
python ask.py "How do I add a YouTube video?"
```

`upload.py` creates (or reuses by name) the vector store and uploads each `.md` file with
`files.create(purpose="assistants")`. It then attaches the file with `vector_stores.files.create_and_poll`.
Each file carries the attributes `article_id`, `content_hash`, `url` and `title`.

**Only changes are uploaded.** The store keeps the hashes as file attributes, so no local state file is needed. Each run compares the scraped files with the store:
- new article: uploaded
- changed hash: the new version is uploaded, then the old file is deleted
- same hash: skipped
- article gone from the site: removed

The log shows `added / updated / skipped / removed`, plus how many files and chunks were embedded.

**Chunking strategy:** static chunks of 800 tokens with 200 tokens of overlap (`kbsync/chunking.py`).
- **Chunk size:** support articles are short and each covers one task. 800 tokens keeps a heading and its numbered steps in one chunk, so answers don't lose steps.
- **Overlap:** 200 tokens keeps context when a long procedure has to be split.
- **Citations:** every file has `Article URL:` at the top and bottom, so most chunks contain a citable URL.
- **Chunk counts:** the API doesn't report chunks per file, so the count in the log is calculated locally with the same sliding-window rule.

**Assistant:** in the [OpenAI Playground](https://platform.openai.com/playground), create an assistant or prompt.
Paste `prompts/system_prompt.txt` as the system instructions, enable **File search** and select the `optibot-kb` vector store.
`ask.py` runs the same setup through the Responses API.
