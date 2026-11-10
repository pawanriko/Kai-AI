"""AI providers for KAI — the ONLY module that talks to AI APIs.

Multi-provider design: a model is just a name; a PROVIDER is the
service that hosts it (base URL + API key + request format). Almost
every provider now speaks the OpenAI chat-completions format, so one
code path serves Groq, OpenRouter, NVIDIA NIM and DeepSeek; Gemini is
the one odd format and has its own adapter below.

Rules:
- Keys come from the environment (loaded from .env by settings.py).
  No key is ever written in code or sent to the browser.
- The UI identifies a choice as "provider::model" (model ids contain
  slashes, so "::" is the unambiguous separator).
- ask_ai tries the chosen provider first, then falls back across the
  other CONFIGURED providers (free tiers rate-limit; falling back is
  how the app survives that). AI_PROVIDER in .env pins one provider
  and disables fallback.
- Every failure returns None; the caller decides what to show.
  Failures are also written to the server log (provider + error), so
  a broken deploy can be told apart from a broken key.
"""

import http.client
import json
import os
import socket
import sys
import time
import urllib.request

PROVIDERS = {
    "groq": {
        "label": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "format": "openai",
        "models": [
            ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
            ("openai/gpt-oss-120b", "GPT OSS 120B"),
            ("openai/gpt-oss-20b", "GPT OSS 20B"),
            ("meta-llama/llama-4-scout-17b-16e-instruct", "Llama 4 Scout"),
            ("qwen/qwen3-32b", "Qwen3 32B"),
            ("llama-3.1-8b-instant", "Llama 3.1 8B"),
        ],
    },
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "format": "openai",
        "extra_headers": {"X-Title": "KAI"},
        "models": [
            ("nvidia/nemotron-3-super-120b-a12b:free", "Nemotron 3 Super 120B (free)"),
            ("minimax/minimax-m2.7:free", "MiniMax M2.7 (free)"),
            ("meta/muse-ember", "Muse Ember"),
            ("deepseek/deepseek-v3.2", "DeepSeek V3.2"),
            ("tencent/hy4", "Hy4"),
            ("mistralai/mistral-large-4-0", "Mistral Large 4"),
            ("anthropic/claude-opus-4-6", "Opus 4.6"),
        ],
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_env": "NVIDIA_API_KEY",
        "format": "openai",
        "models": [
            ("nvidia/llama-3.3-nemotron-super-49b-v1.5", "Nemotron Super 49B"),
            ("deepseek-ai/deepseek-v4-flash", "DeepSeek V4 Flash"),
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "url": "https://api.deepseek.com/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "format": "openai",
        "models": [
            ("deepseek-chat", "DeepSeek Chat"),
            ("deepseek-reasoner", "DeepSeek Reasoner"),
        ],
    },
    "gemini": {
        "label": "Google Gemini",
        "url": (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent"
        ),
        "key_env": "GEMINI_API_KEY",
        "format": "gemini",
        "models": [
            ("gemini-3.8-flash", "Gemini 3.8 Flash"),
            ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ],
    },
}

DEFAULT_PROVIDER = "groq"
FALLBACK_ORDER = ["groq", "openrouter", "nvidia", "deepseek", "gemini"]


def provider_configured(name):
    """True when the provider's API key exists in the environment."""
    return bool(os.environ.get(PROVIDERS[name]["key_env"]))


def catalog():
    """The provider/model catalogue for the UI's model picker."""
    return [
        {
            "provider": name,
            "label": cfg["label"],
            "configured": provider_configured(name),
            "models": [
                {"id": model_id, "label": label}
                for model_id, label in cfg["models"]
            ],
        }
        for name, cfg in PROVIDERS.items()
    ]


def default_model(provider):
    return PROVIDERS[provider]["models"][0][0]


def parse_choice(choice):
    """'nvidia::deepseek-ai/...' → ('nvidia', 'deepseek-ai/...').

    A bare model id (no '::') is treated as a Groq model, which keeps
    old clients working. None → (default provider, its default model).
    """
    if not choice:
        return DEFAULT_PROVIDER, default_model(DEFAULT_PROVIDER)
    if "::" in choice:
        provider, model = choice.split("::", 1)
        if provider in PROVIDERS:
            return provider, model
    return DEFAULT_PROVIDER, choice


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials over IPv4 only.

    Some container networks hand back IPv6 addresses whose routes
    blackhole: the dial then stalls until the socket timeout instead
    of failing fast, which looks exactly like the provider being
    down (seen on both Antideploy and Render — chat died at the 25s
    timeout while the same call took 0.4s from a normal network).
    Resolving A records only keeps the dial on the network that
    actually works there. The rest mirrors the stdlib connect(),
    including the proxy-tunnel case.
    """

    def connect(self):
        server_hostname = self._tunnel_host or self.host
        infos = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )
        self.sock = socket.create_connection(
            infos[0][4], self.timeout, self.source_address
        )
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=server_hostname
        )


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


_OPENER = urllib.request.build_opener(_IPv4HTTPSHandler())


def _log_failure(provider, exc):
    """One stderr line per failed provider call (Render: Logs tab)."""
    print(
        f"[kai] {provider} call failed: {type(exc).__name__}: {exc}",
        file=sys.stderr,
        flush=True,
    )


def _post_json(url, payload, headers, timeout=25):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with _OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _ask_openai(provider, messages, model):
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(cfg.get("extra_headers", {}))
    try:
        data = _post_json(
            cfg["url"], {"model": model, "messages": messages}, headers
        )
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        _log_failure(provider, exc)
        return None


def _ask_gemini(messages, model):
    """Gemini adapter: roles are 'user'/'model'; the system prompt
    travels separately as system_instruction."""
    cfg = PROVIDERS["gemini"]
    api_key = os.environ.get(cfg["key_env"])
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
            cfg["url"].format(model=model),
            payload,
            {"x-goog-api-key": api_key},
        )
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts) or None
    except Exception as exc:
        _log_failure("gemini", exc)
        return None


def _ask(provider, messages, model):
    if PROVIDERS[provider]["format"] == "gemini":
        return _ask_gemini(messages, model)
    return _ask_openai(provider, messages, model)


def chat_completion(provider, messages, model, tools=None):
    """One raw chat-completions call (OpenAI-format providers only).

    Returns the full assistant message dict — which may carry
    `tool_calls` instead of text — or None on any failure. The agent
    loop uses this; plain chat uses ask_ai.
    """
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key or cfg["format"] != "openai":
        return None
    payload = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(cfg.get("extra_headers", {}))
    try:
        data = _post_json(cfg["url"], payload, headers, timeout=30)
        return data["choices"][0]["message"]
    except Exception as exc:
        _log_failure(provider, exc)
        return None


def agent_provider(choice):
    """Pick (provider, model) for an agent run: the user's choice when
    it's a configured OpenAI-format provider, else the first configured
    OpenAI-format provider in fallback order. (Gemini's tool-calling
    format differs, so agent runs stay on OpenAI-format providers.)"""
    provider, model = parse_choice(choice)
    if (
        PROVIDERS[provider]["format"] == "openai"
        and provider_configured(provider)
    ):
        return provider, model
    for other in FALLBACK_ORDER:
        if (
            PROVIDERS[other]["format"] == "openai"
            and provider_configured(other)
        ):
            return other, default_model(other)
    return provider, model


def ask_ai(messages, model=None):
    """Ask the chosen provider; fall back across configured providers.

    `model` is a 'provider::model' choice (or a bare Groq model id).
    Returns the reply text, or None when every attempt failed.
    """
    provider, model_id = parse_choice(model)
    pinned = os.environ.get("AI_PROVIDER", "").strip().lower()
    if pinned in PROVIDERS:
        # A pinned provider still gets model fallback WITHIN itself:
        # a hot model can answer 503 ("service unavailable") for
        # minutes at a time while its sibling model is fine (seen
        # live: gemini-3.8-flash 503ing while pinned). Try the
        # default model first, then the provider's other models,
        # with a short pause between attempts.
        models = [default_model(pinned)] + [
            model_id
            for model_id, _label in PROVIDERS[pinned]["models"]
            if model_id != default_model(pinned)
        ]
        for attempt, attempt_model in enumerate(models):
            if attempt:
                time.sleep(2)
            reply = _ask(pinned, messages, attempt_model)
            if reply is not None:
                return reply
        return None

    attempts = [(provider, model_id)]
    for other in FALLBACK_ORDER:
        if other != provider:
            attempts.append((other, default_model(other)))
    for attempt_provider, attempt_model in attempts:
        if not provider_configured(attempt_provider):
            continue
        reply = _ask(attempt_provider, messages, attempt_model)
        if reply is not None:
            return reply
    return None


def extract_facts(user_text, assistant_text):
    """Ask the AI to pull durable facts about the user from one exchange.

    Returns a list of short fact strings (possibly empty). Facts are
    about the USER (name, college, exams, goals, preferences) — never
    about the assistant. Any failure returns []: memory extraction is
    best-effort and must never break the chat itself. Uses a small fast
    Groq model when available; otherwise the normal fallback chain.
    """
    prompt = (
        "From this exchange, extract durable facts about the USER only "
        "(name, college/course, exams, goals, projects, preferences, "
        "important dates). Reply with ONLY a JSON list of short strings, "
        "e.g. [\"User's exam is on June 5\"]. If there are no durable "
        "facts, reply with [].\n\n"
        f"User: {user_text}\nAssistant: {assistant_text}"
    )
    choice = "groq::llama-3.1-8b-instant" if provider_configured("groq") else None
    raw = ask_ai([{"role": "user", "content": prompt}], model=choice)
    if not raw:
        return []
    try:
        start, end = raw.index("["), raw.rindex("]") + 1
        facts = json.loads(raw[start:end])
        return [str(f).strip() for f in facts if str(f).strip()][:5]
    except Exception:
        return []
