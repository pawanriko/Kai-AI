"""Cloud text-to-speech via the Gemini API (AI Studio key).

Why the Gemini API and NOT Google Cloud Text-to-Speech: Cloud TTS
has no API-key auth — it needs OAuth service-account credentials
and a client library. The Gemini API speaks the same
``x-goog-api-key`` header KAI already uses for chat, needs no
billing for its free tier, and its TTS models are free of charge
within free-tier limits (3 requests/min). One user clicking
read-aloud fits comfortably inside that.

API surface: the Interactions API (``POST /v1beta/interactions``),
which is the surface Google documents for the Gemini 3.8 TTS
models. The older ``generateContent`` shape (``responseModalities``
+ ``speechConfig.voiceConfig.prebuiltVoiceConfig``) was the
contract for the 2.5/3.1 TTS previews — those shut down 17 Nov
2026 — and the 3.8 models are not documented on it. Calling the
old shape is why every cloud read-aloud failed and fell back to
the browser voice (found 2026-11-13 from the official docs, after
the first build shipped the legacy shape).

Model: ``gemini-3.8-flash-tts`` (override with GEMINI_TTS_MODEL).
Voice: ``Kore`` (override with GEMINI_TTS_VOICE), one of the
prebuilt multilingual voices; the model follows the language of
the text, so the same voice reads English and Hindi replies. No
style annotation is sent — the docs recommend plain transcripts
first, and most requests need no style instruction at all.

Output: unary Interactions requests return complete WAV audio
(24 kHz, mono, 16-bit PCM with a RIFF header) as base64 in the
last ``audio`` block of the ``model_output`` steps. The bytes are
passed through untouched — no PCM wrapping is needed (that was
the 3.1 preview's headerless format).

Only the standard library is used. Failures return None and log
one stderr line (Render: Logs tab); the endpoint turns that into
a 502 and the frontend falls back to the browser voice, so a dead
key or a rate limit never breaks read-aloud outright.
"""

import base64
import json
import os
import sys
import urllib.request

TTS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Kore"
MAX_TTS_CHARS = 4000
_TIMEOUT = 60


def _log_failure(exc):
    """One stderr line per failed synthesis (Render: Logs tab)."""
    print(
        f"[kai] gemini-tts call failed: {type(exc).__name__}: {exc}",
        file=sys.stderr,
        flush=True,
    )


def tts_configured():
    """True when the shared Gemini API key exists in the environment.

    The TTS call reuses GEMINI_API_KEY — the same key KAI's chat
    provider uses — so no second credential is needed.
    """
    return bool(os.environ.get("GEMINI_API_KEY"))


def _post_json(url, payload, headers, timeout=_TIMEOUT):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_audio(data):
    """The last audio block of the model_output steps, decoded.

    Mirrors the docs' own traversal (the last ``audio`` item in
    ``steps[].content[]``). A top-level ``output_audio.data`` is
    accepted as a fallback — the SDKs surface the same bytes
    there. Returns None when the response carries no audio.
    """
    audio_data = None
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if (
                isinstance(item, dict)
                and item.get("type") == "audio"
                and item.get("data")
            ):
                audio_data = item["data"]
    if audio_data is None:
        output = data.get("output_audio") or {}
        audio_data = output.get("data") if isinstance(output, dict) else None
    if not audio_data:
        return None
    return base64.b64decode(audio_data)


def synthesize(text, model=None, voice=None):
    """Synthesize WAV audio bytes for `text`, or None when the cloud
    voice is unavailable (no key, provider error, empty reply).

    `model`/`voice` default to the GEMINI_TTS_MODEL /
    GEMINI_TTS_VOICE env vars so the voice can be swapped without
    a code change. Over-long text is refused by the endpoint, not
    here — this function trusts its caller to cap the input.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    text = (text or "").strip()
    if not text:
        return None
    model = model or os.environ.get("GEMINI_TTS_MODEL", DEFAULT_MODEL)
    voice = voice or os.environ.get("GEMINI_TTS_VOICE", DEFAULT_VOICE)
    payload = {
        "model": model,
        "input": [
            {
                "type": "user_input",
                "content": [{"type": "text", "text": text}],
            }
        ],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    try:
        data = _post_json(
            TTS_URL,
            payload,
            {"x-goog-api-key": api_key},
        )
        return _extract_audio(data)
    except Exception as exc:
        # Any provider failure — transport, malformed reply, bad
        # audio payload — degrades to None, exactly like the chat
        # adapters in ai.py: the endpoint maps it to a 502 and the
        # frontend falls back to the browser voice.
        _log_failure(exc)
        return None
