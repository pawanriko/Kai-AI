"""Prompt polish tests: the provider call is mocked — tests never
touch the network. Covers the rewrite helper (cleaning, routing,
failure modes) and the /api/polish/ endpoint (auth, validation,
configured/unconfigured, failure mapping, cost-ledger recording,
rate limit)."""

import json
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from . import polish
from .models import Usage


class CleanReplyTests(TestCase):
    def test_plain_reply_passes_through(self):
        self.assertEqual(polish._clean_reply("  Make it clear. "), "Make it clear.")

    def test_unwraps_a_whole_reply_code_fence(self):
        self.assertEqual(
            polish._clean_reply("```\nMake it clear.\n```"), "Make it clear."
        )

    def test_unwraps_a_fence_with_a_language_tag(self):
        self.assertEqual(
            polish._clean_reply("```text\nMake it clear.\n```"), "Make it clear."
        )

    def test_keeps_inline_fences_inside_the_prompt(self):
        text = "Fix `foo()` in `bar.py`."
        self.assertEqual(polish._clean_reply(text), text)


class PolishAvailableTests(TestCase):
    def test_false_when_no_provider_configured(self):
        with mock.patch("chat.polish.ai.provider_configured", return_value=False):
            self.assertFalse(polish.polish_available())

    def test_true_when_any_provider_configured(self):
        def configured(name):
            return name == "gemini"

        with mock.patch("chat.polish.ai.provider_configured", side_effect=configured):
            self.assertTrue(polish.polish_available())


class PolishHelperTests(TestCase):
    def test_returns_cleaned_reply_and_default_routing(self):
        with mock.patch(
            "chat.polish.ai.ask_ai", return_value="  Clearer draft. "
        ) as ask:
            with mock.patch.dict(os.environ):
                os.environ.pop("KAI_POLISH_MODEL", None)
                result = polish.polish("rough draft")
        self.assertEqual(result, "Clearer draft.")
        messages = ask.call_args.args[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1], {"role": "user", "content": "rough draft"})
        self.assertIsNone(ask.call_args.kwargs["model"])

    def test_env_choice_is_passed_through(self):
        with (
            mock.patch.dict(
                os.environ, {"KAI_POLISH_MODEL": "openrouter::some-model"}
            ),
            mock.patch("chat.polish.ai.ask_ai", return_value="ok") as ask,
        ):
            polish.polish("rough draft")
        self.assertEqual(ask.call_args.kwargs["model"], "openrouter::some-model")

    def test_on_usage_is_forwarded(self):
        callback = mock.Mock()
        with mock.patch("chat.polish.ai.ask_ai", return_value="ok") as ask:
            polish.polish("rough draft", on_usage=callback)
        self.assertIs(ask.call_args.kwargs["on_usage"], callback)

    def test_none_when_every_provider_failed(self):
        with mock.patch("chat.polish.ai.ask_ai", return_value=None):
            self.assertIsNone(polish.polish("rough draft"))

    def test_none_when_provider_call_raises(self):
        with mock.patch(
            "chat.polish.ai.ask_ai", side_effect=RuntimeError("boom")
        ):
            self.assertIsNone(polish.polish("rough draft"))

    def test_none_when_reply_cleans_to_empty(self):
        with mock.patch("chat.polish.ai.ask_ai", return_value="   \n  "):
            self.assertIsNone(polish.polish("rough draft"))


class PolishEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="pawan", password="pw123456"
        )
        self.client.force_login(self.user)

    def _post(self, payload, raw=None):
        return self.client.post(
            "/api/polish/",
            data=raw if raw is not None else json.dumps(payload),
            content_type="application/json",
        )

    def test_anonymous_gets_401(self):
        self.client.logout()
        response = self._post({"text": "rough draft"})
        self.assertEqual(response.status_code, 401)

    def test_invalid_json_gets_400(self):
        response = self._post(None, raw="{not json")
        self.assertEqual(response.status_code, 400)

    def test_empty_text_gets_400(self):
        response = self._post({"text": "   "})
        self.assertEqual(response.status_code, 400)

    def test_oversize_text_gets_400(self):
        response = self._post({"text": "x" * (polish.MAX_POLISH_CHARS + 1)})
        self.assertEqual(response.status_code, 400)

    def test_unconfigured_providers_get_503(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            response = self._post({"text": "rough draft"})
        self.assertEqual(response.status_code, 503)

    def test_provider_failure_gets_502(self):
        with (
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.views.polish.polish", return_value=None
            ),
        ):
            response = self._post({"text": "rough draft"})
        self.assertEqual(response.status_code, 502)

    def test_success_returns_polished_text_and_records_usage(self):
        def fake_ask(messages, model=None, on_usage=None):
            if on_usage is not None:
                on_usage(
                    "gemini",
                    "gemini-3.8-flash",
                    {"prompt_tokens": 5, "completion_tokens": 7},
                )
            return "Clearer draft."

        with (
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "gem-key"}),
            mock.patch("chat.ai.ask_ai", side_effect=fake_ask),
        ):
            response = self._post({"text": "rough draft"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"polished": "Clearer draft."})
        row = Usage.objects.get()
        self.assertEqual(row.kind, Usage.Kind.POLISH)
        self.assertEqual(row.provider, "gemini")
        self.assertEqual(row.model, "gemini-3.8-flash")
        self.assertEqual(row.prompt_tokens, 5)
        self.assertEqual(row.completion_tokens, 7)
        self.assertEqual(row.user, self.user)

    def test_rate_limit_returns_429_after_ten_per_minute(self):
        with (
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "gem-key"}),
            mock.patch(
                "chat.views.polish.polish", return_value="Clearer draft."
            ),
        ):
            statuses = [
                self._post({"text": "rough draft"}).status_code
                for _ in range(11)
            ]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10], 429)
