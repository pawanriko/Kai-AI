"""Cloud TTS tests: the Gemini call is mocked — tests never touch
the network. Covers the Interactions API contract (payload shape,
audio extraction, failure modes) and the /api/tts/ endpoint
(auth, validation, configured/unconfigured, failure mapping)."""

import base64
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from . import tts

# A minimal valid WAV: 44-byte RIFF header, no frames. The
# Interactions API returns complete WAV bytes; synthesize must pass
# them through untouched, never re-wrap them.
FAKE_WAV = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    b"\x80\x5d\x00\x00\x00\xbb\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


def _interactions_audio_response(wav_bytes):
    return {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "audio",
                        "data": base64.b64encode(wav_bytes).decode("ascii"),
                    }
                ],
            }
        ]
    }


class ExtractAudioTests(TestCase):
    def test_returns_decoded_bytes_from_last_audio_block(self):
        first = base64.b64encode(b"first-wav").decode("ascii")
        second = base64.b64encode(b"second-wav").decode("ascii")
        data = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "data": first},
                        {"type": "text", "text": "ignored"},
                        {"type": "audio", "data": second},
                    ],
                }
            ]
        }
        self.assertEqual(tts._extract_audio(data), b"second-wav")

    def test_skips_non_model_output_steps(self):
        data = {
            "steps": [
                {
                    "type": "tool_call",
                    "content": [
                        {
                            "type": "audio",
                            "data": base64.b64encode(b"nope").decode("ascii"),
                        }
                    ],
                }
            ]
        }
        self.assertIsNone(tts._extract_audio(data))

    def test_output_audio_fallback_and_empty_responses(self):
        data = {"output_audio": {"data": base64.b64encode(b"wav").decode("ascii")}}
        self.assertEqual(tts._extract_audio(data), b"wav")
        self.assertIsNone(tts._extract_audio({}))
        self.assertIsNone(tts._extract_audio({"steps": []}))
        self.assertIsNone(
            tts._extract_audio(
                {"steps": [{"type": "model_output", "content": []}]}
            )
        )


class SynthesizeTests(TestCase):
    def test_posts_interactions_request_and_returns_wav_untouched(self):
        with (
            mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.tts._post_json",
                return_value=_interactions_audio_response(FAKE_WAV),
            ) as post,
        ):
            result = tts.synthesize("Hello there")
        self.assertEqual(result, FAKE_WAV)
        url, payload, headers = post.call_args.args
        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/interactions",
        )
        self.assertEqual(headers, {"x-goog-api-key": "gem-key"})
        self.assertEqual(payload["model"], "gemini-3.8-flash-tts")
        self.assertEqual(payload["response_format"], {"type": "audio"})
        self.assertEqual(
            payload["generation_config"]["speech_config"],
            [{"voice": "Kore"}],
        )
        user_input = payload["input"][0]
        self.assertEqual(user_input["type"], "user_input")
        self.assertEqual(
            user_input["content"], [{"type": "text", "text": "Hello there"}]
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
                return_value=_interactions_audio_response(FAKE_WAV),
            ) as post,
        ):
            self.assertIsNotNone(tts.synthesize("hi"))
        _url, payload, _headers = post.call_args.args
        self.assertEqual(payload["model"], "gemini-3.8-flash-lite-tts")
        self.assertEqual(
            payload["generation_config"]["speech_config"],
            [{"voice": "Charon"}],
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
            mock.patch("chat.tts._post_json", return_value={"steps": []}),
        ):
            self.assertIsNone(tts.synthesize("Hello"))


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
