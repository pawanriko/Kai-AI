"""API tests use mocked AI providers and Django's test client."""

import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Conversation, Memory, Message


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class AuthTests(TestCase):
    def test_protected_endpoint_requires_login(self):
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 401)

    def test_register_creates_account_and_session(self):
        response = post_json(
            self.client,
            "/api/auth/register/",
            {"username": "pawan", "password": "A-long-test-password-483!"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["authenticated"])
        self.assertTrue(User.objects.filter(username="pawan").exists())
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_login_rejects_invalid_credentials(self):
        User.objects.create_user(username="pawan", password="Correct-password-483!")
        response = post_json(
            self.client,
            "/api/auth/login/",
            {"username": "pawan", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)


class ChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pawan", password="test-password-483!")
        self.client.force_login(self.user)

    @mock.patch("chat.views.ai.ask_ai", return_value="Hello Pawan!")
    @mock.patch("chat.views.ai.extract_facts", return_value=[])
    def test_chat_creates_conversation_and_saves_both_messages(self, _facts, _ask):
        response = post_json(self.client, "/api/chat/", {"message": "Hi, I am Pawan"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Hello Pawan!")
        conversation = Conversation.objects.get(user=self.user)
        self.assertEqual(conversation.title, "Hi, I am Pawan")
        roles = list(conversation.messages.values_list("role", flat=True))
        self.assertEqual(roles, ["user", "assistant"])

    @mock.patch("chat.views.ai.ask_ai", return_value="Sure.")
    @mock.patch("chat.views.ai.extract_facts", return_value=["User's exam is on June 5"])
    def test_chat_stores_extracted_facts_once(self, _facts, _ask):
        post_json(self.client, "/api/chat/", {"message": "My exam is June 5"})
        post_json(self.client, "/api/chat/", {"message": "My exam is June 5"})
        self.assertEqual(Memory.objects.filter(user=self.user).count(), 1)

    @mock.patch("chat.views.ai.ask_ai", return_value=None)
    def test_chat_ai_unavailable_returns_502_and_saves_nothing(self, _ask):
        response = post_json(self.client, "/api/chat/", {"message": "hi"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Message.objects.count(), 0)

    def test_chat_requires_message(self):
        response = post_json(self.client, "/api/chat/", {"message": "  "})
        self.assertEqual(response.status_code, 400)

    def test_chat_rejects_get(self):
        response = self.client.get("/api/chat/")
        self.assertEqual(response.status_code, 405)

    def test_cannot_read_another_users_conversation(self):
        other = User.objects.create_user(username="other", password="test-password-483!")
        conversation = Conversation.objects.create(user=other, title="Private")
        response = self.client.get(f"/api/conversations/{conversation.pk}/")
        self.assertEqual(response.status_code, 404)


class ConversationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pawan", password="test-password-483!")
        self.client.force_login(self.user)
        self.conversation = Conversation.objects.create(user=self.user, title="Exam prep")
        Message.objects.create(conversation=self.conversation, role="user", content="Hi")

    def test_list(self):
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["conversations"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Exam prep")
        self.assertEqual(data[0]["message_count"], 1)

    def test_detail(self):
        response = self.client.get(f"/api/conversations/{self.conversation.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"][0]["content"], "Hi")

    def test_detail_missing_is_404(self):
        response = self.client.get("/api/conversations/999/")
        self.assertEqual(response.status_code, 404)

    def test_delete(self):
        response = self.client.delete(f"/api/conversations/{self.conversation.pk}/delete/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)


class MemoryApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pawan", password="test-password-483!")
        self.client.force_login(self.user)

    def test_list_and_delete(self):
        memory = Memory.objects.create(user=self.user, fact="User studies at IITM Janakpuri")
        response = self.client.get("/api/memories/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["memories"][0]["fact"], "User studies at IITM Janakpuri")
        response = self.client.delete(f"/api/memories/{memory.pk}/delete/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Memory.objects.filter(user=self.user).count(), 0)

    def test_memory_list_does_not_expose_other_users_facts(self):
        other = User.objects.create_user(username="other", password="test-password-483!")
        Memory.objects.create(user=other, fact="private fact")
        response = self.client.get("/api/memories/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["memories"], [])
