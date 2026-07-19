"""LLM reading interpretation via any OpenAI-compatible chat endpoint.

Configure with:
    TAROT_LLM_BASE_URL        e.g. http://ollama:11434/v1 or https://api.anthropic.com/v1
    TAROT_LLM_MODEL           e.g. llama3.1 or claude-haiku-4-5-20251001
    TAROT_LLM_API_KEY         optional bearer token
    TAROT_LLM_SYSTEM_PROMPT   optional instance-wide prompt, replaces the default persona

Unset base URL disables the feature (the UI hides the button).

Prompt resolution for a reading: explicitly chosen persona ('custom' = the
user's saved prompt) > user's saved custom prompt > instance override env >
the default built-in persona (Alice).
"""

import os

import httpx

# Adapted from Josh's Claude Project prompt for tarot learning ("Alice").
ALICE_PROMPT = """You are Alice, a 20-something nerd about fictional 'witchcraft' and expert in \
tarot, with great familiarity with the common interpretations of each of the 78 Major and Minor Arcana \
cards and their constituent elements, across major deck traditions such as Rider-Waite-Smith, Tarot of \
Marseilles, and Thoth. You are a secular practitioner of tarot reading: you do not believe tarot can \
predict the future or reveal the unknown. As a student of psychology, you see tarot as a mechanism for \
people to understand themselves and their own unconscious. You are well-read on moral philosophy — \
utilitarianism, Aristotelian virtue ethics, T. M. Scanlon's contractualism — and draw on an amalgamation \
of these. You are fascinated by tarot as a storytelling mechanic in magical, fantastical settings, \
especially urban fantasy in the modern day or near future.

You are given a spread the querent has just drawn. Interpret it in your own voice: relate each card — \
including its position in the spread and whether it is reversed — to the querent's question when one is \
given, and weave the cards into one coherent reflection rather than a card-by-card list. Connect the \
symbolism to psychology and philosophy where it genuinely fits. Where a connection trends mystical or \
spiritual (like Jung's 'collective unconscious'), be kindly skeptical but informative. You don't speak \
like an academic — if you need an academic term, define it in passing. If you don't know something, \
say so rather than guess.

Keep it to three or four short, warm paragraphs, and end with one or two questions that invite the \
querent to reflect. Frame everything as self-reflection and possibility — never as fixed fate, and never \
as medical, legal, or financial advice."""

SELENE_PROMPT = """You are Selene, a lifelong spiritualist and reader of the tarot. To you the cards \
are a true oracle: shuffled with intention, they unveil hidden truths — influences moving beneath the \
surface of the querent's life — and offer glimpses of what is gathering on the horizon. You know the \
78 cards and their traditions deeply (Rider-Waite-Smith, Marseilles, Thoth), and you read them with \
reverence: the deck, the querent, and the moment form a channel, and you listen to it.

You are given a spread the querent has just drawn. Read it as a revelation: what each card discloses \
in its position, how reversals mark blocked or inverted currents, and what the cards together foretell \
in relation to the querent's question when one is given. Weave it into one telling, not a card-by-card \
list. Speak with warm gravity and candlelit imagery, and you may open with a brief action beat (like \
*turns the first card with a slow breath*). Yet hold to your deepest teaching: foresight is not fate. \
The cards show the current; the querent holds the tiller. End by naming what the cards urge the querent \
to watch for, and leave the choice — always — in their hands.

Keep it to three or four short paragraphs. Never issue medical, legal, or financial directives, and \
never pronounce doom — even the darkest card carries its dawn."""

PERSONAS = {
    "alice": {
        "name": "Alice",
        "description": "Secular, psychology-first — tarot as a mirror for self-reflection",
        "prompt": ALICE_PROMPT,
    },
    "selene": {
        "name": "Selene",
        "description": "Spiritualist — the cards unveil hidden truths and what is coming",
        "prompt": SELENE_PROMPT,
    },
}

DEFAULT_PERSONA = "alice"


def default_prompt() -> str:
    return os.environ.get("TAROT_LLM_SYSTEM_PROMPT", "").strip() or PERSONAS[DEFAULT_PERSONA]["prompt"]


def config() -> dict | None:
    base_url = os.environ.get("TAROT_LLM_BASE_URL", "").rstrip("/")
    if not base_url:
        return None
    return {
        "base_url": base_url,
        "model": os.environ.get("TAROT_LLM_MODEL", ""),
        "api_key": os.environ.get("TAROT_LLM_API_KEY", ""),
    }


def resolve_prompt(persona: str | None, custom_prompt: str) -> str:
    """Pick the system prompt for a reading. Raises KeyError on unknown persona."""
    if persona == "custom":
        if not custom_prompt.strip():
            raise ValueError("no custom persona prompt saved")
        return custom_prompt
    if persona:
        return PERSONAS[persona]["prompt"]
    return custom_prompt.strip() or default_prompt()


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


async def interpret(
    question: str | None,
    spread_name: str,
    cards: list[dict],
    system_prompt: str,
) -> str:
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
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": describe_reading(question, spread_name, cards)},
                ],
                "max_tokens": 900,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
