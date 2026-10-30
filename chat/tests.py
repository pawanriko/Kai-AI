"""API tests. The AI call is mocked — tests never touch the network."""

import json
from unittest import mock

from django.test import TestCase

from .models import Conversation, Memory, Message


def post_json(client, url, payload):
    return client.post(
        url, data=json.dumps(payload), content_type="application/json"
    )


class PingTests(TestCase):
    def test_ping(self):
        response = self.client.get("/api/ping/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class ChatTests(TestCase):
    @mock.patch("chat.views.ai.ask_ai", return_value="Hello Pawan!")
    @mock.patch("chat.views.ai.extract_facts", return_value=[])
    def test_chat_creates_conversation_and_saves_both_messages(
        self, _facts, _ask
    ):
        response = post_json(
            self.client, "/api/chat/", {"message": "Hi, I am Pawan"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Hello Pawan!")
        conversation = Conversation.objects.get()
        self.assertEqual(conversation.title, "Hi, I am Pawan")
        roles = list(
            conversation.messages.values_list("role", flat=True)
        )
        self.assertEqual(roles, ["user", "assistant"])

    @mock.patch("chat.views.ai.ask_ai", return_value="Sure.")
    @mock.patch(
        "chat.views.ai.extract_facts",
        return_value=["User's exam is on June 5"],
    )
    def test_chat_stores_extracted_facts_once(self, _facts, _ask):
        post_json(self.client, "/api/chat/", {"message": "My exam is June 5"})
        post_json(self.client, "/api/chat/", {"message": "My exam is June 5"})
        self.assertEqual(Memory.objects.count(), 1)

    @mock.patch("chat.views.ai.ask_ai", return_value=None)
    def test_chat_ai_unavailable_returns_502_and_saves_nothing(self, _ask):
        response = post_json(self.client, "/api/chat/", {"message": "hi"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)

    def test_chat_requires_message(self):
        response = post_json(self.client, "/api/chat/", {"message": "  "})
        self.assertEqual(response.status_code, 400)

    def test_chat_rejects_get(self):
        response = self.client.get("/api/chat/")
        self.assertEqual(response.status_code, 405)


class ConversationApiTests(TestCase):
    def setUp(self):
        self.conversation = Conversation.objects.create(title="Exam prep")
        Message.objects.create(
            conversation=self.conversation, role="user", content="Hi"
        )

    def test_list(self):
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["conversations"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Exam prep")
        self.assertEqual(data[0]["message_count"], 1)

    def test_detail(self):
        response = self.client.get(
            f"/api/conversations/{self.conversation.pk}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"][0]["content"], "Hi")

    def test_detail_missing_is_404(self):
        response = self.client.get("/api/conversations/999/")
        self.assertEqual(response.status_code, 404)

    def test_delete(self):
        response = self.client.delete(
            f"/api/conversations/{self.conversation.pk}/delete/"
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)


class ModelCatalogTests(TestCase):
    def test_catalog_lists_all_providers(self):
        response = self.client.get("/api/models/")
        self.assertEqual(response.status_code, 200)
        providers = {
            p["provider"]: p for p in response.json()["providers"]
        }
        self.assertEqual(
            set(providers),
            {"groq", "openrouter", "nvidia", "deepseek", "gemini"},
        )
        for provider in providers.values():
            self.assertTrue(provider["models"])
            # No keys exist in the test environment.
            self.assertFalse(provider["configured"])


class ProviderRoutingTests(TestCase):
    def test_parse_choice(self):
        from . import ai

        self.assertEqual(
            ai.parse_choice("nvidia::deepseek-ai/deepseek-v4-flash"),
            ("nvidia", "deepseek-ai/deepseek-v4-flash"),
        )
        self.assertEqual(
            ai.parse_choice("llama-3.1-8b-instant"),
            ("groq", "llama-3.1-8b-instant"),
        )

    @mock.patch.dict("os.environ", {"NVIDIA_API_KEY": "nv-key"})
    @mock.patch("chat.ai._post_json")
    def test_ask_ai_routes_to_chosen_provider(self, post):
        from . import ai

        post.return_value = {
            "choices": [{"message": {"content": "from nvidia"}}]
        }
        reply = ai.ask_ai(
            [{"role": "user", "content": "hi"}],
            model="nvidia::nvidia/llama-3.3-nemotron-super-49b-v1.5",
        )
        self.assertEqual(reply, "from nvidia")
        self.assertIn("integrate.api.nvidia.com", post.call_args[0][0])

    @mock.patch.dict(
        "os.environ", {"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": "o"}
    )
    @mock.patch("chat.ai._post_json")
    def test_ask_ai_falls_back_when_chosen_provider_fails(self, post):
        from . import ai

        def flaky(url, payload, headers):
            if "groq" in url:
                raise RuntimeError("rate limited")
            return {"choices": [{"message": {"content": "from openrouter"}}]}

        post.side_effect = flaky
        reply = ai.ask_ai([{"role": "user", "content": "hi"}])
        self.assertEqual(reply, "from openrouter")

    @mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gem"})
    @mock.patch("chat.ai._post_json")
    def test_ask_ai_gemini_adapter(self, post):
        from . import ai

        post.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "from gemini"}]}}
            ]
        }
        reply = ai.ask_ai(
            [{"role": "user", "content": "hi"}],
            model="gemini::gemini-2.5-flash",
        )
        self.assertEqual(reply, "from gemini")


class ToolTests(TestCase):
    def test_calculator_arithmetic(self):
        from . import tools

        self.assertEqual(tools.calculator("45000 * 0.18"), "45000 * 0.18 = 8100")
        self.assertEqual(tools.calculator("(2 + 3) * 4"), "(2 + 3) * 4 = 20")

    def test_calculator_rejects_code(self):
        from . import tools

        for bad in ("__import__('os')", "open('x')", "x + 1", "[1,2][0]"):
            self.assertIn("error", tools.calculator(bad).lower())

    def test_run_tool_unknown_and_datetime(self):
        from . import tools

        self.assertIn("unknown tool", tools.run_tool("nope", {}))
        self.assertIn("Today is", tools.run_tool("current_datetime", {}))


class AgentLoopTests(TestCase):
    @mock.patch("chat.agent.ai.chat_completion")
    def test_loop_runs_tool_then_answers(self, completion):
        from . import agent

        completion.side_effect = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression": "45000 * 0.18"}',
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "That is 8100."},
        ]
        reply, trace = agent.run_agent(
            [
                {"role": "system", "content": "You are KAI."},
                {"role": "user", "content": "What is 18% of 45000?"},
            ]
        )
        self.assertEqual(reply, "That is 8100.")
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["tool"], "calculator")
        self.assertIn("8100", trace[0]["result"])

    @mock.patch("chat.agent.ai.chat_completion")
    def test_loop_plain_answer_no_tools(self, completion):
        from . import agent

        completion.return_value = {"role": "assistant", "content": "Hi!"}
        reply, trace = agent.run_agent([{"role": "user", "content": "hi"}])
        self.assertEqual(reply, "Hi!")
        self.assertEqual(trace, [])


class ChatAgentEndpointTests(TestCase):
    @mock.patch(
        "chat.views.agent.run_agent",
        return_value=(
            "It is 8100.",
            [{"tool": "calculator", "args": {}, "result": "45000 * 0.18 = 8100"}],
        ),
    )
    @mock.patch("chat.views.ai.extract_facts", return_value=[])
    def test_agent_chat_saves_and_returns_trace(self, _facts, _run):
        response = post_json(
            self.client,
            "/api/chat/",
            {"message": "18% of 45000?", "agent": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["trace"]), 1)
        assistant = Message.objects.get(role="assistant")
        self.assertEqual(assistant.trace[0]["tool"], "calculator")


class MemoryApiTests(TestCase):
    def test_list_and_delete(self):
        memory = Memory.objects.create(fact="User studies at IITM Janakpuri")
        response = self.client.get("/api/memories/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["memories"][0]["fact"],
            "User studies at IITM Janakpuri",
        )
        response = self.client.delete(f"/api/memories/{memory.pk}/delete/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Memory.objects.count(), 0)
