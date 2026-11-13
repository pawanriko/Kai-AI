"""Cloud text-to-speech via the Gemini API (AI Studio key).

Why the Gemini API and NOT Google Cloud Text-to-Speech: Cloud TTS
has no API-key auth — it needs OAuth service-account credentials
and a client library. The Gemini API speaks the same
``x-goog-api-key`` header KAI already uses for chat, needs no
billing for its free tier, and its TTS models are free of charge
within free-tier limits (3 requests/min). One user clicking
read-aloud fits comfortably inside that.

Model: ``gemini-3.8-flash-tts`` (override with GEMINI_TTS_MODEL).
The older 2.5/3.1 TTS previews shut down 17 Nov 2026 — do not
point this at them. Voice: ``Kore`` (override with
GEMINI_TTS_VOICE), one of the prebuilt multilingual voices; the
model follows the language of the text, so the same voice reads
English and Hindi replies.

The API returns raw 16-bit PCM at 24 kHz, mono, base64 inside the
JSON response — browsers cannot play raw PCM, so it is wrapped in
a WAV header here (pure stdlib, no new dependency).

Only the standard library is used. Failures return None and log
one stderr line (Render: Logs tab); the endpoint turns that into
a 502 and the frontend falls back to the browser voice, so a dead
key or a rate limit never breaks read-aloud outright.
"""

import base64
import json
import os
import struct
import sys
import urllib.error
import urllib.request

TTS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
DEFAULT_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Kore"
MAX_TTS_CHARS = 4000
_SAMPLE_RATE = 24000
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


def pcm_to_wav(pcm, sample_rate=_SAMPLE_RATE):
    """Wrap raw s16le mono PCM in a 44-byte WAV header.

    Pure bytes: the header describes 1 channel, 16-bit samples at
    the given rate, and the data chunk is the PCM untouched.
    """
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,  # PCM format chunk size
        1,  # audio format: PCM
        1,  # channels: mono
        sample_rate,
        sample_rate * 2,  # byte rate: rate * channels * 2 bytes
        2,  # block align: channels * 2 bytes
        16,  # bits per sample
        b"data",
        len(pcm),
    )
    return header + pcm


def _post_json(url, payload, headers, timeout=_TIMEOUT):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }
    try:
        data = _post_json(
            TTS_URL.format(model=model),
            payload,
            {"x-goog-api-key": api_key},
        )
        parts = data["candidates"][0]["content"]["parts"]
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return pcm_to_wav(base64.b64decode(inline["data"]))
        return None
    except Exception as exc:
        # Any provider failure — transport, malformed reply, bad
        # audio payload — degrades to None, exactly like the chat
        # adapters in ai.py: the endpoint maps it to a 502 and the
        # frontend falls back to the browser voice.
        _log_failure(exc)
        return None
