"""Task-based router (Phase 3): classify the user's message, pick a
FREE model from a small policy table.

The classifier is deterministic keyword matching — no extra AI call,
no surprises, and every decision is testable offline. Classification
runs on the latest user message only.

HARD RULE (roadmap Step 3): automatic routing NEVER picks a paid or
metered model. Policy entries are free-tier ids only (OpenRouter
`:free` ids, each already in the catalogue and verified live), and
route resolution additionally refuses any id that is not free and
not in the catalogue — so a policy entry that stops being free is
skipped, never silently escalated. Paid models are used only when
the user picked them explicitly in the picker.

Routing is OPT-IN: it runs only when the model choice is the literal
"auto" (the picker's Auto option). An explicit pick always wins, and
the long-standing default for "no choice given" is unchanged — the
router must never silently override what the user sees selected.
"""

import re

TASKS = ("chat", "reasoning", "coding", "research")

# Word-boundary matched (see classify_task); a code fence anywhere is
# decisive for coding before any keyword is consulted.
_CODING_MARKERS = (
    "python", "django", "javascript", "typescript", "react",
    "function", "traceback", "bug", "debug", "refactor", "implement",
    "code", "script", "compile", "syntax", "regex", "sql",
    "api endpoint", "stack trace", "error",
)
_RESEARCH_MARKERS = (
    "research", "search for", "find out", "latest", "news",
    "compare", "sources", "cite", "what happened", "who is",
    "when did", "look up",
)
_REASONING_MARKERS = (
    "why", "explain", "prove", "analyse", "analyze", "plan",
    "decide", "tradeoff", "trade-off", "pros and cons",
    "step by step", "reasoning", "think through",
)


def _has_marker(text, marker):
    return re.search(r"\b" + re.escape(marker) + r"\b", text) is not None


def classify_task(text):
    """'fix this python function' → 'coding'; 'hello' → 'chat'.

    Precedence is deliberate: coding markers win over research and
    reasoning (a message asking to debug code that mentions "why"
    is still a coding task), research wins over reasoning.
    """
    lowered = (text or "").lower()
    if "```" in lowered:
        return "coding"
    for marker in _CODING_MARKERS:
        if _has_marker(lowered, marker):
            return "coding"
    for marker in _RESEARCH_MARKERS:
        if _has_marker(lowered, marker):
            return "research"
    for marker in _REASONING_MARKERS:
        if _has_marker(lowered, marker):
            return "reasoning"
    return "chat"


def is_free_model(model_id):
    """True only for OpenRouter's explicit free-tier ids. Every other
    id is treated as metered (possibly paid) — the router never
    assumes a model is free."""
    return str(model_id or "").endswith(":free")


# Free models only, each already present in ai.PROVIDERS and verified
# live on OpenRouter's models list. Order within a task is preference
# order; resolution takes the first entry whose provider is
# configured. A second entry exists so one provider outage does not
# strand the task — both entries are the same provider today because
# it is the only one with verified free ids; the table shape allows
# a second provider to be added without code changes.
POLICY = {
    "chat": [
        ("openrouter", "google/gemma-4-26b-a4b-it:free"),
        ("openrouter", "google/gemma-4-31b-it:free"),
    ],
    "reasoning": [
        ("openrouter", "google/gemma-4-31b-it:free"),
        ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ],
    "coding": [
        ("openrouter", "cohere/north-mini-code:free"),
        ("openrouter", "nvidia/nemotron-3.5-lightning:free"),
    ],
    "research": [
        ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        ("openrouter", "google/gemma-4-31b-it:free"),
    ],
}
