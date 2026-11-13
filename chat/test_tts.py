"""Cloud TTS tests: the Gemini call is mocked — tests never touch
the network. Covers the WAV wrapping, the synthesize contract
(payload shape, failure modes) and the /api/tts/ endpoint
(auth, validation, configured/unconfigured, failure mapping)."""

import base64
import io
import json
import wave
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from . import tts


def _gemini_audio_response(pcm):
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/L16;codec=pcm;rate=24000",
                                "data": base64.b64encode(pcm).decode("ascii"),
                            }
                        }
                    ]
                }
            }
        ]
    }


class PcmToWavTests(TestCase):
    def test_wav_header_describes_24khz_mono_16bit(self):
        pcm = b"\x00\x01\x02\x03" * 100
        wav_bytes = tts.pcm_to_wav(pcm)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getnframes(), len(pcm) // 2)
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)

    def test_empty_pcm_is_header_only(self):
        wav_bytes = tts.pcm_to_wav(b"")
        self.assertEqual(len(wav_bytes), 44)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getnframes(), 0)


class SynthesizeTests(TestCase):
    def test_posts_audio_request_and_returns_wav(self):
        pcm = b"\x10\x20" * 50
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.tts._post_json",
                return_value=_gemini_audio_response(pcm),
            ) as post,
        ):
            result = tts.synthesize("Hello there")
        self.assertIsNotNone(result)
        with wave.open(io.BytesIO(result), "rb") as wav:
            self.assertEqual(wav.getnframes(), len(pcm) // 2)
        url, payload, headers = post.call_args.args
        self.assertIn("gemini-3.8-flash-tts", url)
        self.assertIn(":generateContent", url)
        self.assertEqual(headers, {"x-goog-api-key": "gem-key"})
        self.assertEqual(
            payload["generationConfig"]["responseModalities"], ["AUDIO"]
        )
        voice = payload["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(
            voice["prebuiltVoiceConfig"]["voiceName"], "Kore"
        )
        self.assertEqual(
            payload["contents"][0]["parts"][0]["text"], "Hello there"
        )

    def test_model_and_voice_come_from_env(self):
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "GEMINI_API_KEY": "gem-key",
                    "GEMINI_TTS_MODEL": "gemini-3.8-flash-lite-tts",
                    "GEMINI_TTS_VOICE": "Charon",
                },
            ),
            mock.patch(
                "chat.tts._post_json",
                return_value=_gemini_audio_response(b"\x00\x00"),
            ) as post,
        ):
            self.assertIsNotNone(tts.synthesize("hi"))
        url, payload, _headers = post.call_args.args
        self.assertIn("gemini-3.8-flash-lite-tts", url)
        voice = payload["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(
            voice["prebuiltVoiceConfig"]["voiceName"], "Charon"
        )

    def test_no_key_or_empty_text_returns_none_without_calling(self):
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}),
            mock.patch("chat.tts._post_json") as post,
        ):
            self.assertIsNone(tts.synthesize("Hello"))
            self.assertFalse(post.called)
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch("chat.tts._post_json") as post,
        ):
            self.assertIsNone(tts.synthesize("   "))
            self.assertFalse(post.called)

    def test_provider_errors_and_empty_replies_return_none(self):
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.tts._post_json", side_effect=RuntimeError("boom")
            ),
        ):
            self.assertIsNone(tts.synthesize("Hello"))
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.tts._post_json",
                return_value={"candidates": [{"content": {"parts": []}}]},
            ),
        ):
            self.assertIsNone(tts.synthesize("Hello"))

    def test_snake_case_inline_data_is_accepted(self):
        pcm = b"\x01\x02" * 10
        response = _gemini_audio_response(pcm)
        part = response["candidates"][0]["content"]["parts"][0]
        part["inline_data"] = part.pop("inlineData")
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch("chat.tts._post_json", return_value=response),
        ):
            result = tts.synthesize("Hello")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 44 + len(pcm))


class TtsEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="pawan", password="<redacted>"
        )
        self.client.force_login(self.user)

    def _post(self, payload, raw=None):
        return self.client.post(
            "/api/tts/",
            data=raw if raw is not None else json.dumps(payload),
            content_type="application/json",
        )

    def test_anonymous_gets_401(self):
        self.client.logout()
        response = self._post({"text": "Hello"})
        self.assertEqual(response.status_code, 401)

    def test_unconfigured_key_gets_503(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            response = self._post({"text": "Hello"})
        self.assertEqual(response.status_code, 503)

    def test_success_returns_wav_bytes(self):
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.views.tts.synthesize", return_value=b"fake-wav-bytes"
            ) as synth,
        ):
            response = self._post({"text": "Hello there"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "audio/wav")
        self.assertEqual(response.content, b"fake-wav-bytes")
        synth.assert_called_once_with("Hello there")

    def test_synthesis_failure_gets_502(self):
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch("chat.views.tts.synthesize", return_value=None),
        ):
            response = self._post({"text": "Hello"})
        self.assertEqual(response.status_code, 502)

    def test_missing_text_and_invalid_json_get_400(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}):
            self.assertEqual(self._post({}).status_code, 400)
            self.assertEqual(self._post({"text": "  "}).status_code, 400)
            self.assertEqual(self._post(None, raw="{nope").status_code, 400)

    def test_over_long_text_gets_400(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}):
            response = self._post({"text": "x" * (tts.MAX_TTS_CHARS + 1)})
        self.assertEqual(response.status_code, 400)

    def test_me_reports_tts_configured_flag(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}):
            response = self.client.get("/api/auth/me/")
        self.assertTrue(response.json()["tts_configured"])
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            response = self.client.get("/api/auth/me/")
        self.assertFalse(response.json()["tts_configured"])
