"""Ask OptiBot a question from the terminal (Responses API + file_search on the vector store).

Usage:  python ask.py "How do I add a YouTube video?"
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.txt").read_text(encoding="utf-8")


def ask(client: OpenAI, question: str, vector_store_id: str, model: str) -> str:
    resp = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=question,
        tools=[{"type": "file_search", "vector_store_ids": [vector_store_id], "max_num_results": 5}],
    )
    return resp.output_text


def main() -> int:
    load_dotenv()
    question = " ".join(sys.argv[1:]) or "How do I add a YouTube video?"
    store = os.getenv("VECTOR_STORE_ID")
    if not store:
        print("Set VECTOR_STORE_ID in .env (printed by upload.py)", file=sys.stderr)
        return 2
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY"))
    print(ask(client, question, store, os.getenv("OPENAI_MODEL", "gpt-4.1-mini")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
