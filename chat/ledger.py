"""Cost ledger (Phase 3): one Usage row per provider call.

Recording is honest about what is unknown:

- Token counts come from the provider's own usage block. Streamed
  calls on OpenAI-format providers send no usage block (KAI does not
  ask for one — see ai.py), so those rows carry NULL tokens: the
  call happened, the counts are unknown. Never estimate tokens from
  text length and present them as measured.
- Estimated cost is 0.0 for `:free` models and NULL for everything
  else. Provider pricing is NOT hardcoded: no price in this file has
  been verified against a live pricing page, and an invented price
  would silently misstate what KAI costs. When a price is verified,
  add it to PRICING (per million tokens) and the estimate becomes
  real for that model.
"""

from .models import Usage

# Verified per-million-token prices, (input, output) in USD. Empty
# until a price is checked against the provider's own pricing page —
# see the module docstring. Format: {"provider::model": (in, out)}.
PRICING = {}


def estimate_cost_usd(provider, model_id, prompt_tokens, completion_tokens):
    """0.0 for free-tier ids; a computed estimate for models with a
    verified price; None when the price is unknown or the counts are
    missing. Never invents a price."""
    from .router import is_free_model

    if is_free_model(model_id):
        return 0.0
    price = PRICING.get(f"{provider}::{model_id}")
    if price is None or prompt_tokens is None or completion_tokens is None:
        return None
    input_price, output_price = price
    return round(
        prompt_tokens * input_price / 1_000_000
        + completion_tokens * output_price / 1_000_000,
        6,
    )


def record_usage(user, provider, model, task, kind, usage):
    """Persist one Usage row. `usage` is the provider's usage block
    {'prompt_tokens': int|None, 'completion_tokens': int|None} or
    None when the provider reported nothing (e.g. a streamed call).
    `task` is the router classification for the exchange (or None
    when the call had no user text to classify)."""
    usage = usage or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    return Usage.objects.create(
        user=user,
        provider=provider,
        model=model,
        task=task,
        kind=kind,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimate_cost_usd(
            provider, model, prompt_tokens, completion_tokens
        ),
    )
