"""Persona-voiced audio for readings via an OpenAI-compatible TTS endpoint.

Mirrors interpret.py's split: config resolution (file > admin UI/DB > env)
separate from the API call. Generated audio is cached under
/data/tts-cache/<sha256>.mp3 with an LRU index in SQLite (see db.tts_cache_*),
bounded by `tts.cache_max_mb` (default 256) — evicted pieces regenerate on
demand, so the cache is never authoritative state.

    tts:
      base_url: https://api.openai.com/v1
      model: gpt-4o-mini-tts
      api_key: "..."            # or api_key_env: TAROT_TTS_API_KEY
      cache_max_mb: 256
      voices:
        alice:  {voice: coral, speed: 1.0, instructions: "..."}
        selene: {voice: sage,  speed: 0.95, instructions: "..."}

`instructions` is OpenAI-only steering; compatible servers without it
(e.g. Kokoro's kokoro-fastapi) ignore the field.
"""

import asyncio
import hashlib
import json
import os
import re

import httpx

from tarot import config as cfgfile
from tarot.decks import data_dir

DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_CACHE_MB = 256
TIMEOUT = 60.0
# stay safely under gpt-4o-mini-tts's ~2000-token input cap (~4 chars/token)
MAX_CHUNK_CHARS = 3600

VOICE_DEFAULTS = {
    "alice": {
        "voice": "marin",
        "speed": 1.0,
        "instructions": (
            "Bright, cheerful, and friendly — a sunny barista delighted to "
            "see a favorite regular, sharing her latest book picks with "
            "genuine enthusiasm. Warm and upbeat with a smile you can hear, "
            "playful lilt on the fun parts, softening kindly for the tender "
            "ones. Never flat, brisk, or matter-of-fact."
        ),
    },
    "selene": {
        "voice": "sage",
        "speed": 1.0,
        "instructions": (
            "You speak beside a dying bonfire under a wide night sky, to "
            "your grown child who walked a long way to ask you this. Quiet "
            "gravity and wind-slow pacing; a voice weathered and kind, and "
            "beneath it all a mother's tenderness — proud, protective, "
            "unhurried. Every sentence lands like a stone set down "
            "carefully, and silence does part of the work."
        ),
    },
    "maud": {
        "voice": "shimmer",
        "speed": 0.95,
        "instructions": (
            "An elderly woman in her eighties — a warm great-grandmother "
            "reading cards at her kitchen table over tea. The voice is "
            "audibly aged: thin and papery, gently quavering, softened and "
            "roughened by the years. Cozy, chuckling warmth with a dry "
            "twinkle; slow, comfortable pacing, as if there is all "
            "afternoon. Plainspoken and gentle even when the truth is hard "
            "— wrapping it in a blanket, never scolding."
        ),
    },
}


def cache_dir():
    return data_dir() / "tts-cache"


def config() -> dict | None:
    """TTS connection, resolved config file > admin UI (DB) > environment.

    None when no base_url anywhere — the feature is off and all audio UI hides.
    """
    from tarot import crypto, db

    file_url = cfgfile.get("tts", "base_url")
    base_url = str(
        file_url or db.get_setting("tts_base_url") or os.environ.get("TAROT_TTS_BASE_URL", "")
    ).rstrip("/")
    if not base_url:
        return None

    file_key = cfgfile.tts_api_key()
    if file_key is None:
        stored = db.get_setting("tts_api_key")
        api_key = crypto.decrypt(stored) if stored else os.environ.get("TAROT_TTS_API_KEY", "")
    else:
        api_key = file_key

    return {
        "base_url": base_url,
        "model": str(
            cfgfile.get("tts", "model")
            or db.get_setting("tts_model")
            or os.environ.get("TAROT_TTS_MODEL", "")
            or DEFAULT_MODEL
        ),
        "api_key": api_key,
        "cache_max_bytes": int(cfgfile.get("tts", "cache_max_mb", DEFAULT_CACHE_MB)) * 1024 * 1024,
    }


def _normalize(block: dict | None, base: dict) -> dict:
    """A complete voice block, unknown keys dropped, missing keys from `base`."""
    block = block if isinstance(block, dict) else {}
    out = {}
    out["voice"] = str(block.get("voice") or base["voice"])
    try:
        out["speed"] = float(block.get("speed") or base["speed"])
    except (TypeError, ValueError):
        out["speed"] = base["speed"]
    instructions = block.get("instructions")
    out["instructions"] = str(instructions).strip() if instructions is not None else base["instructions"]
    return out


def resolve_voice(persona: str | None, owner: str) -> dict:
    """The voice block for a persona: file > DB > shipped defaults.

    Unknown/absent persona (including the retired "custom") falls back to
    the instance default persona.
    """
    from tarot import db
    from tarot.interpret import default_persona

    if persona not in VOICE_DEFAULTS:
        persona = default_persona()
    base = VOICE_DEFAULTS[persona]

    stored = db.get_setting(f"tts_voice_{persona}")
    if stored:
        try:
            base = _normalize(json.loads(stored), base)
        except ValueError:
            pass

    file_voices = cfgfile.get("tts", "voices")
    if isinstance(file_voices, dict) and isinstance(file_voices.get(persona), dict):
        base = _normalize(file_voices[persona], base)
    return _normalize({}, base)


_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), " "),        # fenced code
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),   # images
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links -> text
    (re.compile(r"^#{1,6}\s*", re.M), ""),        # headings
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),      # list markers
    (re.compile(r"[*_]{1,3}([^*_]+)[*_]{1,3}"), r"\1"),  # emphasis
]


def strip_markdown(text: str) -> str:
    for pat, repl in _MD_PATTERNS:
        text = pat.sub(repl, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def spoken_intro(card: dict | None) -> str:
    """The eyes-closed lead-in. `card` is a saved-reading card entry
    ({position: {name}, card: {name}, reversed}); None = the whole-spread row.

    Opens with the position name when it carries meaning ("The Crossing
    Card"), else just the card name — the single spread's generic "The Card"
    position sounds absurd spoken aloud."""
    if card is None:
        return "The whole picture."
    name = card["card"]["name"] + (", reversed" if card.get("reversed") else "")
    pos = (card.get("position") or {}).get("name")
    if not pos or pos.strip().lower() == "the card":
        return f"{name}."
    return f"{pos} — {name}."


def build_script(intro: str, text: str) -> str:
    return f"{intro}\n\n{strip_markdown(text)}".strip()


def _chunks(script: str) -> list[str]:
    """Split at paragraph, then sentence, then hard boundaries — never drops text."""
    if len(script) <= MAX_CHUNK_CHARS:
        return [script]
    pieces: list[str] = []
    for para in re.split(r"\n\n+", script):
        if len(para) <= MAX_CHUNK_CHARS:
            pieces.append(para)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            # hard-split anything still over the cap (no sentence breaks)
            pieces.extend(
                sentence[i : i + MAX_CHUNK_CHARS]
                for i in range(0, len(sentence), MAX_CHUNK_CHARS)
            )
    parts: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > MAX_CHUNK_CHARS:
            parts.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current.strip():
        parts.append(current)
    return parts


async def synthesize(script: str, voice: dict, cfg: dict,
                     usage_meta: dict | None = None) -> bytes:
    """Generate MP3 for the script, splitting over-cap text and concatenating
    the segments (same codec params -> a valid stream). With `usage_meta`
    ({owner, kind, reading_id?}), writes one ledger row per provider call —
    cache hits never reach here, so only real spend is recorded."""
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    out = b""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for chunk in _chunks(script):
            body = {
                "model": cfg["model"],
                "voice": voice["voice"],
                "input": chunk,
                "speed": voice["speed"],
                "response_format": "mp3",
            }
            if voice.get("instructions"):
                body["instructions"] = voice["instructions"]
            resp = await client.post(f"{cfg['base_url']}/audio/speech", json=body, headers=headers)
            resp.raise_for_status()
            out += resp.content
            if usage_meta:
                from starlette.concurrency import run_in_threadpool

                from tarot import db

                try:
                    await run_in_threadpool(
                        db.record_usage,
                        owner=usage_meta["owner"], component="tts",
                        kind=usage_meta.get("kind", "speak"), model=cfg["model"],
                        reading_id=usage_meta.get("reading_id"),
                        characters=len(chunk), audio_bytes=len(resp.content),
                    )
                except Exception:
                    pass  # accounting must never break playback
    return out


def cache_key(script: str, voice: dict, model: str) -> str:
    payload = json.dumps({"script": script, "voice": voice, "model": model}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# One generation per piece even under concurrent requests; the dict itself is
# guarded so lock creation can't race.
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(key: str) -> asyncio.Lock:
    async with _locks_guard:
        return _locks.setdefault(key, asyncio.Lock())


def _evict(budget_bytes: int) -> None:
    """Drop least-recently-played entries until the cache fits the budget,
    and clean up any orphan files (crash leftovers) not in the index."""
    from tarot import db

    directory = cache_dir()
    known = db.tts_cache_all()
    indexed = {row["hash"] for row in known}
    if directory.is_dir():
        for f in directory.glob("*.mp3"):
            if f.stem not in indexed:
                f.unlink(missing_ok=True)
    total = sum(row["size_bytes"] for row in known)
    for row in known:  # ordered oldest-played first
        if total <= budget_bytes:
            break
        (directory / f"{row['hash']}.mp3").unlink(missing_ok=True)
        db.tts_cache_delete(row["hash"])
        total -= row["size_bytes"]


async def get_or_generate(script: str, voice: dict, cfg: dict,
                          usage_meta: dict | None = None):
    """Path to cached-or-fresh MP3 for this script+voice+model."""
    from fastapi.concurrency import run_in_threadpool

    from tarot import db

    key = cache_key(script, voice, cfg["model"])
    path = cache_dir() / f"{key}.mp3"
    lock = await _lock_for(key)
    async with lock:
        if path.is_file():
            await run_in_threadpool(db.tts_cache_touch, key)
            return path
        db.tts_cache_delete(key)  # stale row without a file (evicted/crashed)
        audio = await synthesize(script, voice, cfg, usage_meta=usage_meta)

        def persist():
            cache_dir().mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(audio)
            tmp.replace(path)
            db.tts_cache_upsert(key, len(audio))
            _evict(cfg["cache_max_bytes"])

        await run_in_threadpool(persist)
        return path
