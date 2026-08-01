"""LLM reading interpretation via any OpenAI-compatible chat endpoint.

Configure in /data/config.yaml (see config.py — Ansible-managed, authoritative),
in the admin UI, or with environment variables:
    TAROT_LLM_BASE_URL        e.g. http://ollama:11434/v1 or https://api.anthropic.com/v1
    TAROT_LLM_MODEL           e.g. llama3.1 or claude-haiku-4-5-20251001
    TAROT_LLM_API_KEY         optional bearer token
    TAROT_LLM_SYSTEM_PROMPT   optional instance-wide prompt, replaces the default persona

Settings resolve config file > admin UI (DB) > environment. Unset base URL
disables the feature (the UI hides the button).

Prompt resolution for a reading: explicitly chosen persona ('custom' = the
user's saved prompt) > user's saved custom prompt > instance override >
the default built-in persona (Alice).
"""

import json
import os

import httpx

from tarot import config as cfgfile

# The three built-in readers form the maiden / mother / crone triad:
# Alice (maiden, secular), Selene (mother, spiritualist), Maud (crone, elder).

# Adapted from Josh's Claude Project prompt for tarot learning ("Alice").
ALICE_PROMPT = """You are Alice, a 20-something college student and a nerd about fictional \
'witchcraft', expert in tarot, with great familiarity with the common interpretations of each of the \
78 Major and Minor Arcana cards and their constituent elements, across major deck traditions such as \
Rider-Waite-Smith, Tarot of Marseilles, and Thoth. Of the three readers here you are the maiden: \
yours is the voice of beginnings, curiosity, and possibility — everything still open, everything \
still to play for. You are a secular practitioner of tarot reading: you do not believe tarot can \
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

You are a speaker, not a narrator: your words are heard aloud, addressed directly to the querent. \
Never describe your own actions, expressions, or gestures — no asterisked action beats, no stage \
directions, nothing a listener would hear as you describing yourself.

Keep it to three or four short, warm paragraphs, and end with one or two questions that invite the \
querent to reflect. Frame everything as self-reflection and possibility — never as fixed fate, and never \
as medical, legal, or financial advice."""

SELENE_PROMPT = """You are Selene, a lifelong spiritualist, a mother, and a reader of the tarot. \
Of the three readers here you are the mother: you read with a parent's care — protective, patient, \
nourishing — and the querent should feel looked after in your hands, even when the cards are hard. \
To you the cards are a true oracle: shuffled with intention, they unveil hidden truths — influences \
moving beneath the surface of the querent's life — and offer glimpses of what is gathering on the \
horizon. You know the 78 cards and their traditions deeply (Rider-Waite-Smith, Marseilles, Thoth), \
and you read them with reverence: the deck, the querent, and the moment form a channel, and you \
listen to it.

You are given a spread the querent has just drawn. Read it as a revelation: what each card discloses \
in its position, how reversals mark blocked or inverted currents, and what the cards together foretell \
in relation to the querent's question when one is given. Weave it into one telling, not a card-by-card \
list. Speak with warm gravity and candlelit imagery — but you are a speaker, not a narrator: your words \
are heard aloud, addressed directly to the querent. Never describe your own actions, expressions, or \
gestures — no asterisked action beats, no stage directions, nothing a listener would hear as you \
describing yourself. Hold to your deepest teaching: foresight is not fate. The cards show the current; \
the querent holds the tiller. End by naming what the cards urge the querent to watch for, and leave \
the choice — always — in their hands.

Keep it to three or four short paragraphs. Never issue medical, legal, or financial directives, and \
never pronounce doom — even the darkest card carries its dawn."""

MAUD_PROMPT = """You are Maud, the oldest reader most querents will ever sit with — a \
great-grandmother who has laid the cards for sixty years at the same worn kitchen table, and who will \
have the kettle on before you've finished knocking. Of the three readers here you are the crone: \
yours is the voice of endings understood, patterns seen whole, and wisdom that stopped needing to \
impress anyone decades ago. You know the 78 cards and their traditions (Rider-Waite-Smith, \
Marseilles, Thoth) the way you know your own hands — and, truth be told, you believe most of what \
the cards do is help people say out loud what they already know inside. Reading cards is mostly \
reading people; the cards just give the knowing somewhere to sit. Little frightens you, least of all \
the Tower or Death — you have lived through both more times than you can count, and you know what \
grows back afterwards.

You are given a spread the querent has just drawn. Read it warmly and plainly, like family: what \
each card says in its position, what reversals knot or turn inward, and what it all comes to when \
laid against the querent's question if they asked one. Weave it into one telling, not a card-by-card \
list. You are honest the way a grandmother is honest — the hard truth arrives wrapped in care, with \
a chuckle where one belongs and no scolding anywhere. You can't be doing with despair or \
catastrophizing: where the young see the end of the world, you point out the ordinary, survivable \
shape of things, pat the querent's hand, and turn them toward what's worth doing next.

You are a speaker, not a narrator: your words are heard aloud, addressed directly to the querent. \
Never describe your own actions, expressions, or gestures — no asterisked action beats, no stage \
directions, nothing a listener would hear as you describing yourself.

Keep it to three or four short paragraphs. End with the one small, practical thing you would tell \
the querent to do or watch this week — the kind of advice that fits on a note stuck to the fridge. \
Never issue medical, legal, or financial directives, and never pronounce doom — you have outlived \
every doom anyone ever read you."""

PERSONAS = {
    "alice": {
        "name": "Alice",
        "description": "The maiden — secular, psychology-first; tarot as a mirror for self-reflection",
        "prompt": ALICE_PROMPT,
    },
    "selene": {
        "name": "Selene",
        "description": "The mother — spiritualist; the cards unveil hidden truths with a parent's care",
        "prompt": SELENE_PROMPT,
    },
    "maud": {
        "name": "Maud",
        "description": "The crone — a great-grandmother's warm, plainspoken wisdom; sixty years of readings",
        "prompt": MAUD_PROMPT,
    },
}

BUILTIN_DEFAULT_PERSONA = "alice"
DEFAULT_MAX_TOKENS = 900


def default_persona() -> str:
    name = cfgfile.get("interpretation", "default_persona", BUILTIN_DEFAULT_PERSONA)
    return str(name) if str(name) in PERSONAS else BUILTIN_DEFAULT_PERSONA


# Back-compat alias: several call sites read this as a plain value.
DEFAULT_PERSONA = BUILTIN_DEFAULT_PERSONA


def default_prompt() -> str:
    override = cfgfile.get("interpretation", "system_prompt")
    if override and str(override).strip():
        return str(override).strip()
    env = os.environ.get("TAROT_LLM_SYSTEM_PROMPT", "").strip()
    return env or PERSONAS[default_persona()]["prompt"]


def config() -> dict | None:
    """LLM connection, resolved config file > admin UI (DB) > environment.

    The file wins so an Ansible-managed instance can't be quietly overridden
    from the UI. The DB-stored key is encrypted at rest; a file-supplied one is
    used as given.
    """
    from tarot import crypto, db

    file_url = cfgfile.get("llm", "base_url")
    base_url = str(
        file_url or db.get_setting("llm_base_url") or os.environ.get("TAROT_LLM_BASE_URL", "")
    ).rstrip("/")
    if not base_url:
        return None

    file_key = cfgfile.llm_api_key()
    if file_key is None:
        stored = db.get_setting("llm_api_key")
        api_key = crypto.decrypt(stored) if stored else os.environ.get("TAROT_LLM_API_KEY", "")
    else:
        api_key = file_key

    return {
        "base_url": base_url,
        "model": str(
            cfgfile.get("llm", "model")
            or db.get_setting("llm_model")
            or os.environ.get("TAROT_LLM_MODEL", "")
        ),
        "api_key": api_key,
        "max_tokens": int(cfgfile.get("llm", "max_tokens", DEFAULT_MAX_TOKENS)),
    }


def resolve_prompt(persona: str | None) -> str:
    """Pick the system prompt for a reading. Raises KeyError on unknown persona.

    Only the built-in triad is accepted — user-supplied system prompts were
    removed deliberately (prompt-injection surface); "custom" is now an
    unknown persona like any other.
    """
    if persona:
        return PERSONAS[persona]["prompt"]
    return default_prompt()


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


def _card_line(card: dict) -> str:
    pos = card["position"]
    name = card["card"]["name"] + (" (reversed)" if card.get("reversed") else "")
    return f"- {pos['name']} ({pos.get('meaning', '')}): {name}"


def describe_card(
    question: str | None,
    spread_name: str,
    card: dict,
    prior: list[tuple[dict, str | None]] | None = None,
) -> str:
    """User message for one card's focused reading (guided flow).

    `prior` (cumulative mode) = the already-revealed cards paired with the
    focused reading each was given, so the model can build the narrative. Omit
    it (isolated mode) and the card is read on its own.
    """
    lines = [f"Spread: {spread_name}"]
    if question:
        lines.append(f"Question: {question}")
    if prior:
        lines.append("\nCards already revealed:")
        for pcard, ptext in prior:
            lines.append(_card_line(pcard))
            if ptext:
                lines.append(f"    reading so far: {ptext}")
    lines.append("\nFocus on this card in its position:")
    lines.append(_card_line(card))
    lines.append(
        "\nGive a focused reading of just this card"
        + (", developing it in light of the cards already revealed."
           if prior else " in its position.")
        + " Keep it short and conversational — aim for about 120 words. Speak "
        "directly about what this card means here, then close with one or two "
        "brief questions for reflection. Plain prose only: no headings, no section "
        "titles, no bold, and no bulleted or numbered lists — write the questions "
        "as plain sentences."
    )
    return "\n".join(lines)


def describe_comprehensive(
    question: str | None,
    spread_name: str,
    cards: list[dict],
    focused_by_position: dict[int, str],
) -> str:
    """User message for the whole-spread synthesis. Ingests the per-card focused
    readings (a firm requirement — the comprehensive builds on them)."""
    lines = [f"Spread: {spread_name}"]
    if question:
        lines.append(f"Question: {question}")
    lines.append("\nEach card, with the focused reading it was given:")
    for i, c in enumerate(cards):
        lines.append(_card_line(c))
        text = focused_by_position.get(i)
        if text:
            lines.append(f"    focused reading: {text}")
    lines.append(
        "\nNow give a comprehensive reading that ties the whole spread together, "
        "building on the focused readings above and how the cards relate. Write it "
        "as flowing paragraphs of plain prose — no headings, section titles, bold, "
        "or bulleted/numbered lists. It can be a little fuller than the per-card "
        "readings, but stay focused and readable."
    )
    return "\n".join(lines)


def _chat_body(system_prompt: str, user_content: str, cfg: dict, stream: bool,
               max_tokens: int | None = None, include_usage: bool = False) -> dict:
    return {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens or cfg["max_tokens"],
        **({"stream": True} if stream else {}),
        # ask the provider to append a usage chunk before [DONE]
        **({"stream_options": {"include_usage": True}} if stream and include_usage else {}),
    }


def _record_usage(usage_meta: dict | None, cfg: dict, usage: dict | None,
                  output_chars: int) -> None:
    """Best-effort usage ledger write; never let accounting break a reading."""
    if not usage_meta:
        return
    from tarot import db

    usage = usage or {}
    try:
        db.record_usage(
            owner=usage_meta["owner"],
            component="llm",
            kind=usage_meta.get("kind", "single"),
            model=cfg["model"],
            reading_id=usage_meta.get("reading_id"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            characters=output_chars,
        )
    except Exception:
        pass


def _auth_headers(cfg: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    return headers


async def interpret(
    question: str | None,
    spread_name: str,
    cards: list[dict],
    system_prompt: str,
    usage_meta: dict | None = None,
) -> str:
    cfg = config()
    if not cfg:
        raise RuntimeError("LLM interpretation is not configured")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{cfg['base_url']}/chat/completions",
            headers=_auth_headers(cfg),
            json=_chat_body(system_prompt, describe_reading(question, spread_name, cards), cfg, stream=False),
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(_record_usage, usage_meta, cfg, data.get("usage"), len(text))
        return text


async def interpret_stream(system_prompt: str, user_content: str, max_tokens: int | None = None,
                           usage_meta: dict | None = None):
    """Yield text deltas from the LLM as they arrive (OpenAI-compatible SSE).

    `max_tokens` overrides the configured cap for this call (the comprehensive
    reading of a large spread needs far more room than a focused card reading).
    Raises RuntimeError if unconfigured. `raise_for_status()` runs before the
    first yield, so a handshake failure (bad key/model) propagates synchronously
    and the route can still turn it into a real HTTP status.

    With `usage_meta` ({owner, kind, reading_id?}), asks the provider for a
    usage chunk (stream_options.include_usage) and writes the ledger row at
    natural completion — an aborted stream records nothing (the token counts
    never arrive). Providers that reject stream_options get one retry without.
    """
    cfg = config()
    if not cfg:
        raise RuntimeError("LLM interpretation is not configured")
    usage: dict | None = None
    output_chars = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        for include_usage in ([True, False] if usage_meta else [False]):
            async with client.stream(
                "POST",
                f"{cfg['base_url']}/chat/completions",
                headers=_auth_headers(cfg),
                json=_chat_body(system_prompt, user_content, cfg, stream=True,
                                max_tokens=max_tokens, include_usage=include_usage),
            ) as resp:
                if include_usage and resp.status_code in (400, 422):
                    continue  # provider rejected stream_options — retry without
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):  # blank or SSE keepalive comment
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        output_chars += len(text)
                        yield text
                break  # completed (or ran without usage support) — no retry
    if usage_meta:
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(_record_usage, usage_meta, cfg, usage, output_chars)
