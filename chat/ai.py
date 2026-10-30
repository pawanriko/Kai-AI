"""AI provider calls for KAI — the ONLY module that talks to Groq/Gemini.

Design rules (same discipline as the HireSense backend):
- Keys come from the environment (loaded from .env by settings.py).
  No key is ever written in code, and none ever reaches the browser.
- Stdlib urllib only — no extra packages.
- Every failure returns None; the caller decides what to show.
- Provider order: if AI_PROVIDER is set ("groq"/"gemini"), only that
  provider is tried. Otherwise Groq first when its key exists, then
  Gemini. A provider with no key is skipped.
"""

import json
import os
import urllib.error
import urllib.request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# The model ids the UI offers (same six as KAI v1, all Groq-hosted).
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]


def _post_json(url, payload, headers, timeout=60):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ask_groq(messages, model=DEFAULT_GROQ_MODEL):
    """One chat-completions call to Groq. Returns reply text or None."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        data = _post_json(
            GROQ_URL,
            {"model": model, "messages": messages},
            {"Authorization": f"Bearer {api_key}"},
        )
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def ask_gemini(messages, model=DEFAULT_GEMINI_MODEL):
    """One generateContent call to Gemini. Returns reply text or None.

    Gemini's format differs from Groq's: roles are "user"/"model" and
    the system prompt travels separately as system_instruction.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    system_text = "\n".join(
        m["content"] for m in messages if m.get("role") == "system"
    )
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
        if m.get("role") != "system"
    ]
    payload = {"contents": contents}
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text}]}
    try:
        data = _post_json(
            GEMINI_URL.format(model=model),
            payload,
            {"x-goog-api-key": api_key},
        )
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts) or None
    except Exception:
        return None


def ask_ai(messages, model=None):
    """Ask whichever provider is configured. Returns text or None.

    `model` only applies to Groq (the UI's model picker lists Groq
    models); Gemini always uses its default model.
    """
    pinned = os.environ.get("AI_PROVIDER", "").strip().lower()
    if pinned == "groq":
        return ask_groq(messages, model or DEFAULT_GROQ_MODEL)
    if pinned == "gemini":
        return ask_gemini(messages)
    if os.environ.get("GROQ_API_KEY"):
        reply = ask_groq(messages, model or DEFAULT_GROQ_MODEL)
        if reply is not None:
            return reply
    return ask_gemini(messages)


def extract_facts(user_text, assistant_text):
    """Ask the AI to pull durable facts about the user from one exchange.

    Returns a list of short fact strings (possibly empty). This is the
    server-side version of v1's browser-side extractFacts(): facts are
    about the USER (name, college, exams, goals, preferences) — never
    about the assistant. Any failure returns []: memory extraction is
    best-effort and must never break the chat itself.
    """
    prompt = (
        "From this exchange, extract durable facts about the USER only "
        "(name, college/course, exams, goals, projects, preferences, "
        "important dates). Reply with ONLY a JSON list of short strings, "
        "e.g. [\"User's exam is on June 5\"]. If there are no durable "
        "facts, reply with [].\n\n"
        f"User: {user_text}\nAssistant: {assistant_text}"
    )
    raw = ask_ai(
        [{"role": "user", "content": prompt}],
        model="llama-3.1-8b-instant",
    )
    if not raw:
        return []
    try:
        start, end = raw.index("["), raw.rindex("]") + 1
        facts = json.loads(raw[start:end])
        return [str(f).strip() for f in facts if str(f).strip()][:5]
    except Exception:
        return []
