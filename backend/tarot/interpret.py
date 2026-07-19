"""LLM reading interpretation via any OpenAI-compatible chat endpoint.

Configure with:
    TAROT_LLM_BASE_URL  e.g. http://ollama:11434/v1 or https://api.anthropic.com/v1
    TAROT_LLM_MODEL     e.g. llama3.1 or claude-haiku-4-5-20251001
    TAROT_LLM_API_KEY   optional bearer token

Unset base URL disables the feature (the UI hides the button).
"""

import os

import httpx

SYSTEM_PROMPT = """You are a thoughtful tarot reader. Given a spread, interpret the cards \
in relation to each position and to each other, weaving them into one coherent narrative. \
Be specific to the cards drawn — including reversals — and to the querent's question when \
given. Speak warmly and plainly, in 3 short paragraphs at most. Frame the reading as \
reflection and possibility, never as fixed fate, medical, legal, or financial advice."""


def config() -> dict | None:
    base_url = os.environ.get("TAROT_LLM_BASE_URL", "").rstrip("/")
    if not base_url:
        return None
    return {
        "base_url": base_url,
        "model": os.environ.get("TAROT_LLM_MODEL", ""),
        "api_key": os.environ.get("TAROT_LLM_API_KEY", ""),
    }


def describe_reading(question: str | None, spread_name: str, cards: list[dict]) -> str:
    lines = [f"Spread: {spread_name}"]
    if question:
        lines.append(f"Question: {question}")
    lines.append("Cards:")
    for c in cards:
        pos = c["position"]
        name = c["card"]["name"] + (" (reversed)" if c.get("reversed") else "")
        lines.append(f"- {pos['name']} ({pos.get('meaning', '')}): {name}")
    return "\n".join(lines)


async def interpret(question: str | None, spread_name: str, cards: list[dict]) -> str:
    cfg = config()
    if not cfg:
        raise RuntimeError("LLM interpretation is not configured")
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{cfg['base_url']}/chat/completions",
            headers=headers,
            json={
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": describe_reading(question, spread_name, cards)},
                ],
                "max_tokens": 700,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
