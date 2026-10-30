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
