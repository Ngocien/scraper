FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/app/.tiktoken

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Bake the tokenizer into the image so runs don't download it (falls back to an estimate if offline).
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" || echo "tiktoken encoding not cached"

COPY kbsync/ kbsync/
COPY prompts/ prompts/
COPY main.py scrape.py upload.py ask.py ./

RUN useradd --create-home --uid 10001 app && mkdir -p articles logs && chown -R app /app
USER app

# Runs once and exits (0 = success). Pass OPENAI_API_KEY or API_KEY with -e.
ENTRYPOINT ["python", "main.py"]
