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
            ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra 550B (free)"),
            ("google/gemma-4-31b-it:free", "Gemma 4 31B (free)"),
            ("cohere/north-mini-code:free", "North Mini Code (free)"),
            # Phase 2.2: extra free fallbacks, each ID verified live
            # against OpenRouter's models list (2026-11-12) before
            # adding — a dead ID here fails the whole chain silently
            # (see the Opus 4.6 404 on 2026-11-11).
            ("google/gemma-4-26b-a4b-it:free", "Gemma 4 26B (free)"),
            ("nvidia/nemotron-3.5-lightning:free", "Nemotron 3.5 Lightning (free)"),
            ("meta/muse-ember", "Muse Ember"),
            ("deepseek/deepseek-v3.2", "DeepSeek V3.2"),
            ("tencent/hy4", "Hy4"),
            ("mistralai/mistral-large-4-0", "Mistral Large 4"),
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

# Last-resort default when NO provider is configured. This used to be
# "groq", whose key has returned HTTP 403 since 2026-10-31 — a bare
# model id routed to the one dead provider. parse_choice now prefers
# the first CONFIGURED provider (see _default_provider); this constant
# only names the shape of the answer when nothing is configured.
DEFAULT_PROVIDER = "gemini"
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


def _default_provider():
    """The provider a bare model id routes to: the first CONFIGURED
    one in fallback order, so a dead or keyless provider is never
    the silent default. (This used to hard-route to Groq, whose key
    has returned HTTP 403 since 2026-10-31.) Falls back to
    DEFAULT_PROVIDER when nothing is configured — the call then
    fails cleanly as 'unavailable'."""
    for name in FALLBACK_ORDER:
        if provider_configured(name):
            return name
    return DEFAULT_PROVIDER


def parse_choice(choice):
    """'nvidia::deepseek-ai/...' → ('nvidia', 'deepseek-ai/...').

    A bare model id (no '::') belongs to the default provider (see
    _default_provider). None → (default provider, its default model).
    """
    if not choice:
        provider = _default_provider()
        return provider, default_model(provider)
    if "::" in choice:
        provider, model = choice.split("::", 1)
        if provider in PROVIDERS:
            return provider, model
    return _default_provider(), choice


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


def _openai_usage(data):
    """Token counts from an OpenAI-format response, or None when the
    provider sent no usage block. Callers must treat None as
    'unknown', never as zero."""
    usage = data.get("usage") or {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        return None
    return {"prompt_tokens": prompt, "completion_tokens": completion}


def _gemini_usage(data):
    """Token counts from a Gemini response's usageMetadata, or None."""
    meta = data.get("usageMetadata") or {}
    prompt = meta.get("promptTokenCount")
    completion = meta.get("candidatesTokenCount")
    if prompt is None and completion is None:
        return None
    return {"prompt_tokens": prompt, "completion_tokens": completion}


def _ask_openai(provider, messages, model, usage_out=None):
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
        if usage_out is not None:
            usage_out["usage"] = _openai_usage(data)
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        _log_failure(provider, exc)
        return None


def _ask_gemini(messages, model, usage_out=None):
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
        if usage_out is not None:
            usage_out["usage"] = _gemini_usage(data)
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts) or None
    except Exception as exc:
        _log_failure("gemini", exc)
        return None


def _ask(provider, messages, model, usage_out=None):
    if PROVIDERS[provider]["format"] == "gemini":
        return _ask_gemini(messages, model, usage_out)
    return _ask_openai(provider, messages, model, usage_out)


# ------------------------------------------------------- Gemini tools

_GEMINI_TYPES = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _gemini_schema(schema):
    """JSON Schema → Gemini's Schema dialect: type names are UPPER
    enum values. Recurses into properties/items; every other key
    passes through unchanged (our tool schemas only use type,
    properties, required and description)."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            out[key] = _GEMINI_TYPES.get(value.lower(), value)
        elif key == "properties" and isinstance(value, dict):
            out[key] = {name: _gemini_schema(sub) for name, sub in value.items()}
        elif key == "items":
            out[key] = _gemini_schema(value)
        else:
            out[key] = value
    return out


def _gemini_function_declarations(schemas):
    return [
        {
            "name": s["function"]["name"],
            "description": s["function"].get("description", ""),
            "parameters": _gemini_schema(
                s["function"].get(
                    "parameters", {"type": "object", "properties": {}}
                )
            ),
        }
        for s in schemas
    ]


def _gemini_contents(messages):
    """OpenAI-shaped messages → Gemini contents + system text.

    The agent loop speaks OpenAI shapes throughout (assistant
    messages with tool_calls, tool messages with tool_call_id), so
    this converter is the single place that knowledge of Gemini's
    functionCall/functionResponse parts lives:

    - assistant tool_calls → model parts with functionCall entries
      (JSON-string arguments are parsed back to objects);
    - tool messages → function-role parts with functionResponse
      entries, merged into one content when consecutive (the API
      pairs responses by function name, recovered here from the
      paired tool call's id via a scan of the history).
    """
    id_to_name = {}
    for m in messages:
        for call in (m.get("tool_calls") or []):
            function = call.get("function") or {}
            if call.get("id"):
                id_to_name[call["id"]] = function.get("name", "")
    contents = []
    system_parts = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system_parts.append(m.get("content") or "")
        elif role == "user":
            contents.append(
                {"role": "user", "parts": [{"text": m.get("content", "")}]}
            )
        elif role == "assistant":
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for call in m.get("tool_calls") or []:
                function = call.get("function") or {}
                args = function.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parts.append(
                    {
                        "functionCall": {
                            "name": function.get("name", ""),
                            "args": args,
                        }
                    }
                )
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            part = {
                "functionResponse": {
                    "name": id_to_name.get(m.get("tool_call_id"), ""),
                    "response": {"result": m.get("content", "")},
                }
            }
            if contents and contents[-1].get("role") == "function":
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "function", "parts": [part]})
    return contents, "\n".join(system_parts)


def _chat_completion_gemini(messages, model, tools, usage_out=None):
    """Gemini function calling, normalized to the OpenAI message
    shape the agent loop already speaks: content text plus, when
    the model called tools, tool_calls with JSON-string arguments.
    Tool-call ids are synthesized (Gemini pairs calls by name, not
    id); the converter above recovers names from the history."""
    cfg = PROVIDERS["gemini"]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        return None
    contents, system_text = _gemini_contents(messages)
    payload = {"contents": contents}
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text}]}
    if tools:
        payload["tools"] = [
            {"functionDeclarations": _gemini_function_declarations(tools)}
        ]
        payload["toolConfig"] = {
            "functionCallingConfig": {"mode": "AUTO"}
        }
    try:
        data = _post_json(
            cfg["url"].format(model=model),
            payload,
            {"x-goog-api-key": api_key},
            timeout=30,
        )
        if usage_out is not None:
            usage_out["usage"] = _gemini_usage(data)
        parts = (data["candidates"][0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        tool_calls = []
        for index, part in enumerate(parts):
            call = part.get("functionCall")
            if not call:
                continue
            tool_calls.append(
                {
                    "id": f"gemini-{call.get('name', '')}-{index}",
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("args") or {}),
                    },
                }
            )
        message = {"role": "assistant", "content": text or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message
    except Exception as exc:
        _log_failure("gemini", exc)
        return None


def chat_completion(provider, messages, model, tools=None, on_usage=None):
    """One raw chat-completions call, any provider.

    Returns the full assistant message dict — which may carry
    `tool_calls` instead of text — or None on any failure. Gemini
    answers are normalized to the OpenAI shape (see
    _chat_completion_gemini), so the agent loop stays
    provider-agnostic. `on_usage`, when given, is called with
    (provider, model, usage-dict-or-None) for the cost ledger.
    """
    cfg = PROVIDERS[provider]
    if not os.environ.get(cfg["key_env"]):
        return None
    holder = {}
    if cfg["format"] == "gemini":
        message = _chat_completion_gemini(messages, model, tools, holder)
    else:
        message = _chat_completion_openai(provider, messages, model, tools, holder)
    if message is not None and on_usage is not None:
        on_usage(provider, model, holder.get("usage"))
    return message


def _chat_completion_openai(provider, messages, model, tools, usage_out=None):
    """The OpenAI-format half of chat_completion (unchanged
    behavior, plus usage capture for the ledger)."""
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        return None
    payload = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(cfg.get("extra_headers", {}))
    try:
        data = _post_json(cfg["url"], payload, headers, timeout=30)
        if usage_out is not None:
            usage_out["usage"] = _openai_usage(data)
        return data["choices"][0]["message"]
    except Exception as exc:
        _log_failure(provider, exc)
        return None


def agent_provider(choice):
    """Pick (provider, model) for an agent run: the user's choice when
    it's a configured provider — any format, now that Gemini has
    native tool calling (Phase 3) — else the first configured
    provider in fallback order. 'auto' without message context
    degrades to the default provider's default model; message-aware
    routing lives in run_agent via route_task."""
    if choice == "auto":
        provider = _default_provider()
        return provider, default_model(provider)
    provider, model = parse_choice(choice)
    if provider_configured(provider):
        return provider, model
    for other in FALLBACK_ORDER:
        if provider_configured(other):
            return other, default_model(other)
    return provider, model


def route_task(messages):
    """Resolve an 'auto' choice: classify the latest user message and
    pick the first available FREE policy model (router.POLICY).

    The hard rule lives here: a policy entry is used only when its
    provider is configured, its id is provably free, and the id is
    actually in that provider's catalogue — the router can never
    invent an id or silently escalate into a paid model. When no
    free policy model is available, resolution degrades to the
    long-standing default (first configured provider's default
    model) rather than failing the request."""
    from .router import POLICY, classify_task, is_free_model

    text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            text = m.get("content", "")
            break
    task = classify_task(text)
    for provider, model in POLICY.get(task, []):
        if not provider_configured(provider):
            continue
        if not is_free_model(model):
            continue
        catalogue_ids = {mid for mid, _ in PROVIDERS[provider]["models"]}
        if model not in catalogue_ids:
            continue
        return provider, model
    provider = _default_provider()
    return provider, default_model(provider)


def ask_ai(messages, model=None, on_usage=None):
    """Ask the chosen provider; fall back across configured providers.

    `model` is a 'provider::model' choice (or a bare Groq model id).
    The literal "auto" resolves through the task router (route_task).
    Returns the reply text, or None when every attempt failed.
    `on_usage`, when given, is called once with (provider, model,
    usage-dict-or-None) for the attempt that answered, for the cost
    ledger — failed attempts report nothing.
    """
    if model == "auto":
        provider, model_id = route_task(messages)
    else:
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
            holder = {}
            reply = _ask(pinned, messages, attempt_model, holder)
            if reply is not None:
                if on_usage is not None:
                    on_usage(pinned, attempt_model, holder.get("usage"))
                return reply
        return None

    attempts = [(provider, model_id)]
    if default_model(provider) != model_id:
        # Phase 2.2: a dead picked model must not cost the whole
        # provider — retry it with the provider's default before
        # moving on. (The Opus 4.6 404 took OpenRouter's free
        # models out of the chain with it: the picked provider was
        # never retried with another model.)
        attempts.append((provider, default_model(provider)))
    for other in FALLBACK_ORDER:
        if other != provider:
            attempts.append((other, default_model(other)))
    for attempt_provider, attempt_model in attempts:
        if not provider_configured(attempt_provider):
            continue
        holder = {}
        reply = _ask(attempt_provider, messages, attempt_model, holder)
        if reply is not None:
            if on_usage is not None:
                on_usage(attempt_provider, attempt_model, holder.get("usage"))
            return reply
    return None


def _open_stream(url, payload, headers, timeout=60):
    """Open a streaming POST and yield its raw response lines.

    The connection stays open while the caller iterates; it closes
    when the generator is exhausted or abandoned.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with _OPENER.open(request, timeout=timeout) as response:
        for line in response:
            yield line.decode("utf-8", "replace").strip()


def _sse_payloads(lines):
    """Yield the JSON payloads of a Server-Sent-Events line stream
    (both OpenAI-format providers and Gemini use `data:` lines)."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


def _stream_openai(provider, messages, model):
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        return
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(cfg.get("extra_headers", {}))
    payload = {"model": model, "messages": messages, "stream": True}
    for event in _sse_payloads(_open_stream(cfg["url"], payload, headers)):
        choices = event.get("choices") or []
        if not choices:
            continue
        text = (choices[0].get("delta") or {}).get("content")
        if text:
            yield text


def _stream_gemini(messages, model, usage_out=None):
    cfg = PROVIDERS["gemini"]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        return
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
    url = cfg["url"].format(model=model).replace(
        ":generateContent", ":streamGenerateContent"
    ) + "?alt=sse"
    for event in _sse_payloads(
        _open_stream(url, payload, {"x-goog-api-key": api_key})
    ):
        # Gemini sends usageMetadata (usually on the final event):
        # capture it for the ledger when present, ignore it when not.
        if usage_out is not None:
            found = _gemini_usage(event)
            if found is not None:
                usage_out["usage"] = found
        candidates = event.get("candidates") or []
        if not candidates:
            continue
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if text:
            yield text


def _stream(provider, messages, model, usage_out=None):
    if PROVIDERS[provider]["format"] == "gemini":
        yield from _stream_gemini(messages, model, usage_out)
    else:
        yield from _stream_openai(provider, messages, model)


class StreamInterrupted(Exception):
    """A provider failed AFTER producing at least one chunk.

    Raised by ask_ai_stream instead of silently ending the reply:
    the caller (the streaming endpoint) must be able to tell an
    interrupted reply apart from a completed one, so the partial
    text is never persisted or presented as a successful answer.
    """


def ask_ai_stream(messages, model=None, on_usage=None):
    """Streaming twin of ask_ai: yields reply text chunks.

    Same attempt order and fallback rules as ask_ai, with one honest
    difference: fallback can only happen BEFORE the first chunk. Once
    a provider has produced text, the stream is committed to it — a
    mid-stream failure raises StreamInterrupted instead of splicing
    in a different model's continuation or silently ending the reply
    (Phase 2.1). Yields nothing at all when every attempt fails
    before producing text (the caller then reports 'AI
    unavailable', exactly like ask_ai returning None).

    The literal "auto" resolves through the task router (route_task).
    `on_usage`, when given, is called once with (provider, model,
    usage-dict-or-None) when a stream completes — usage is None for
    OpenAI-format streams (KAI deliberately does not request the
    usage chunk: not every provider accepts the option, and a
    rejected stream option would break chat) and populated for
    Gemini streams when the provider sends usageMetadata.
    """
    if model == "auto":
        provider, model_id = route_task(messages)
    else:
        provider, model_id = parse_choice(model)
    pinned = os.environ.get("AI_PROVIDER", "").strip().lower()
    if pinned in PROVIDERS:
        models = [default_model(pinned)] + [
            mid
            for mid, _label in PROVIDERS[pinned]["models"]
            if mid != default_model(pinned)
        ]
        attempts = [(pinned, mid) for mid in models]
    else:
        attempts = [(provider, model_id)]
        if default_model(provider) != model_id:
            # Phase 2.2: same retry as ask_ai — a dead picked model
            # must not cost the whole provider.
            attempts.append((provider, default_model(provider)))
        attempts += [
            (other, default_model(other))
            for other in FALLBACK_ORDER
            if other != provider
        ]
    for attempt_provider, attempt_model in attempts:
        if not provider_configured(attempt_provider):
            continue
        holder = {}
        stream = _stream(attempt_provider, messages, attempt_model, holder)
        try:
            first = next(stream, None)
        except Exception as exc:
            _log_failure(attempt_provider, exc)
            continue
        if first is None:
            continue
        yield first
        try:
            yield from stream
        except Exception as exc:
            _log_failure(attempt_provider, exc)
            # The reply has already begun, so falling back would
            # splice two models together — and silently returning
            # would let the caller save the partial text as a
            # finished answer. Signal the interruption instead.
            raise StreamInterrupted(
                f"{attempt_provider} stream failed mid-reply"
            ) from exc
        if on_usage is not None:
            on_usage(attempt_provider, attempt_model, holder.get("usage"))
        return


def extract_facts(user_text, assistant_text, on_usage=None):
    """Ask the AI to pull durable facts about the user from one exchange.

    Returns a list of short fact strings (possibly empty). Facts are
    about the USER (name, college, exams, goals, preferences) — never
    about the assistant. Any failure returns []: memory extraction is
    best-effort and must never break the chat itself. Uses a small fast
    Groq model when available; otherwise the normal fallback chain.
    `on_usage` is forwarded to ask_ai for the cost ledger.
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
    raw = ask_ai(
        [{"role": "user", "content": prompt}],
        model=choice,
        on_usage=on_usage,
    )
    if not raw:
        return []
    try:
        start, end = raw.index("["), raw.rindex("]") + 1
        facts = json.loads(raw[start:end])
        return [str(f).strip() for f in facts if str(f).strip()][:5]
    except Exception:
        return []
