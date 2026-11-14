"""Chunking strategy shared by the uploader and the logs.

OpenAI vector stores do the actual chunking server-side; we pass an explicit *static*
strategy so the behaviour is fixed and documented, and we replicate the same
sliding-window math locally to log how many chunks were embedded (the API does not
return a per-file chunk count).
"""
from __future__ import annotations

import math
from functools import lru_cache

# Support articles are short (most < 1,000 tokens) and cover one task each.
# 800-token chunks keep a whole procedure (heading + numbered steps) together;
# 200 tokens of overlap stop a step list being cut without context.
MAX_CHUNK_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 200

CHUNKING_STRATEGY = {
    "type": "static",
    "static": {
        "max_chunk_size_tokens": MAX_CHUNK_TOKENS,
        "chunk_overlap_tokens": CHUNK_OVERLAP_TOKENS,
    },
}


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("o200k_base")
    except Exception:  # offline / encoding not downloadable -> approximate
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(text))
    return math.ceil(len(text) / 4)  # ~4 chars per token for English prose


def estimate_chunks(text: str, max_tokens: int = MAX_CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP_TOKENS) -> int:
    tokens = count_tokens(text)
    if tokens == 0:
        return 0
    if tokens <= max_tokens:
        return 1
    stride = max_tokens - overlap
    return 1 + math.ceil((tokens - max_tokens) / stride)
