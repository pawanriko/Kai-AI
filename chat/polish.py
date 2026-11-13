"""Prompt polish: rewrite a draft message into a clearer prompt.

Why this exists: a vague prompt gets a vague reply, and dictated
drafts (see the push-to-talk input in ChatInput) are often rambling.
The user taps Polish, a model rewrites the draft into a specific,
well-formed prompt, and the rewrite is SHOWN — never auto-sent.
The user picks Use (replace the draft) or Discard (keep the
original). The draft is never modified server-side and nothing is
persisted: drafts leave no record.

Routing: no new model IDs. The rewrite goes through ai.ask_ai with
the model from KAI_POLISH_MODEL (a 'provider::model' choice) when
set, else the default routing — the default provider's default
model, with the usual fallback chain across configured providers.
A dead key or a 503 therefore degrades to the next provider
instead of failing the polish outright, exactly like chat.

Failures return None and log one stderr line (Render: Logs tab);
the endpoint turns that into a 502 and the frontend keeps the
user's original draft untouched.
"""

import os
import sys

from . import ai

MAX_POLISH_CHARS = 4000

SYSTEM_PROMPT = (
    "You rewrite the user's draft message into a clearer, more "
    "specific prompt for an AI assistant. Rules: keep the user's "
    "intent and language — if the draft is in Hindi or Hinglish, "
    "keep it in Hindi or Hinglish; if it is in English, keep it in "
    "English. Make vague requests specific using only details "
    "present in or clearly implied by the draft — never invent "
    "requirements, facts, or constraints the user did not state. "
    "Keep it about the same length; do not pad. If the draft is "
    "already clear, return it nearly unchanged. Do NOT answer the "
    "draft. Do NOT explain. Return ONLY the rewritten prompt, with "
    "no preamble, no quotes, and no code fences."
)


def polish_available():
    """True when at least one provider has an API key configured."""
    return any(ai.provider_configured(name) for name in ai.PROVIDERS)


def _clean_reply(reply):
    """Strip the model's wrapping, if it added any despite the
    instruction: surrounding whitespace, and one code fence around
    the whole reply. The words themselves are never touched."""
    text = reply.strip()
    if text.startswith("```") and text.endswith("```") and len(text) > 6:
        inner = text[3:-3].strip()
        # A fenced block may carry a language tag on its first line.
        if "\n" in inner:
            first, rest = inner.split("\n", 1)
            if " " not in first.strip():
                inner = rest.strip()
        text = inner
    return text


def polish(text, on_usage=None):
    """Rewrite `text` into a clearer prompt, or None on failure.

    `on_usage`, when given, is forwarded to ask_ai so the call is
    recorded in the cost ledger like any other provider call.
    """
    choice = os.environ.get("KAI_POLISH_MODEL", "").strip() or None
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        reply = ai.ask_ai(messages, model=choice, on_usage=on_usage)
    except Exception as exc:  # never crash the endpoint on a provider bug
        print(f"[kai] prompt polish call failed: {exc!r}", file=sys.stderr)
        return None
    if reply is None:
        print("[kai] prompt polish: all providers failed", file=sys.stderr)
        return None
    return _clean_reply(reply) or None
