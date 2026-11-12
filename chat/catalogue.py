"""Catalogue self-check (Phase 3): validate the picker model ids
against each provider's LIVE models list.

The 2026-11-10 dead-free-model incident (a model id in the catalogue
that the provider no longer serves) becomes a warning, not an
outage: this module only REPORTS. Nothing here changes the
catalogue, and a failed check never breaks chat — providers that
cannot be reached are reported "unchecked", never "dead".

Live-list endpoints (all GET, stdlib urllib, 20 s timeout):

- OpenRouter: public, no key required.
- Groq / NVIDIA / DeepSeek: OpenAI-format /models, Bearer key.
- Gemini: /v1beta/models with ?key=, ids arrive as "models/<id>".
"""

import json
import urllib.request

LIST_URLS = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "nvidia": "https://integrate.api.nvidia.com/v1/models",
    "deepseek": "https://api.deepseek.com/models",
}
GEMINI_LIST_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
)


def fetch_json(url, headers=None, timeout=20):
    """GET + parse JSON. Raises on any failure — the caller decides
    how to report it (unchecked, never fatal)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "KAI/2.0 (catalogue check)", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def live_model_ids(provider, api_key, fetcher=None):
    """The set of model ids the provider serves right now.

    Returns (ids, error): ids is a set (possibly empty) and error is
    None on success, or (set(), "reason") when the list could not be
    fetched — including when the provider needs a key and none is
    configured. The caller must treat the error case as
    "unchecked", never as "every id is dead". `fetcher` defaults to
    fetch_json resolved at CALL time (not as a default argument),
    so tests can substitute it by patching catalogue.fetch_json.
    """
    if fetcher is None:
        fetcher = fetch_json
    if provider == "gemini":
        if not api_key:
            return set(), "no API key configured"
        try:
            data = fetcher(f"{GEMINI_LIST_URL}?key={api_key}&pageSize=100")
        except Exception as exc:
            return set(), f"list fetch failed: {exc}"
        names = {
            str(m.get("name", "")).removeprefix("models/")
            for m in data.get("models", [])
        }
        return names, None
    url = LIST_URLS.get(provider)
    if url is None:
        return set(), f"no live-list endpoint known for {provider}"
    if provider != "openrouter" and not api_key:
        return set(), "no API key configured"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        data = fetcher(url, headers)
    except Exception as exc:
        return set(), f"list fetch failed: {exc}"
    return {str(m.get("id", "")) for m in data.get("data", [])}, None


def check_ids(catalogue_ids, live_ids):
    """Pure comparison: (alive, dead) — catalogue ids present in the
    live list, and catalogue ids missing from it. No I/O, so the
    comparison itself is trivially testable."""
    catalogue = set(catalogue_ids)
    alive = sorted(catalogue & set(live_ids))
    dead = sorted(catalogue - set(live_ids))
    return alive, dead


def check_provider(provider, catalogue_ids, api_key, fetcher=None):
    """One provider's verdict: a dict with status 'ok' | 'dead' |
    'unchecked', the alive/dead id lists, and a human reason when
    unchecked. Never raises for provider-side failures."""
    live_ids, error = live_model_ids(provider, api_key, fetcher)
    if error is not None:
        return {
            "provider": provider,
            "status": "unchecked",
            "alive": [],
            "dead": [],
            "reason": error,
        }
    alive, dead = check_ids(catalogue_ids, live_ids)
    return {
        "provider": provider,
        "status": "dead" if dead else "ok",
        "alive": alive,
        "dead": dead,
        "reason": "",
    }
