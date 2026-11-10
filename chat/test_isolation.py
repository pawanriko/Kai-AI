"""Cross-account isolation tests (Phase 1 follow-up, 2026-11-11).

KAI is a single-owner app, but ownership must hold even if a second
account ever exists (created via admin/shell): every data endpoint
scopes through _visible_conversations / _visible_memories, so another
user's rows must be invisible and unreachable (404), never leaked or
modifiable. Legacy NULL-owner rows are the documented exception:
visible to any authenticated user until the owner claims them by
first use (opening a conversation claims it; these tests pin that
behaviour so it can never change silently).
"""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from chat.models import Conversation, Memory, Message


class CrossAccountIsolationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="owner_a", password="OwnerPass#123"
        )
        self.other = User.objects.create_user(
            username="other_b", password="OtherPass#123"
        )
        self.conv = Conversation.objects.create(
            user=self.owner, title="Owner private chat"
        )
        Message.objects.create(
            conversation=self.conv, role="user", content="owner secret msg"
        )
        self.mem = Memory.objects.create(
            user=self.owner,
            fact="Owner private fact",
            status=Memory.Status.CONFIRMED,
        )
        self.legacy_conv = Conversation.objects.create(
            user=None, title="Legacy ownerless chat"
        )
        self.legacy_mem = Memory.objects.create(
            user=None,
            fact="Legacy ownerless fact",
            status=Memory.Status.CONFIRMED,
        )
        self.as_owner = Client()
        self.as_owner.force_login(self.owner)
        self.as_other = Client()
        self.as_other.force_login(self.other)

    # --- the other account must NOT reach the owner's data ----------

    def test_other_list_excludes_owner_conversation(self):
        data = self.as_other.get("/api/conversations/").json()
        titles = [c["title"] for c in data["conversations"]]
        self.assertNotIn("Owner private chat", titles)

    def test_other_get_owner_conversation_is_404(self):
        r = self.as_other.get(f"/api/conversations/{self.conv.pk}/")
        self.assertEqual(r.status_code, 404)

    def test_other_delete_owner_conversation_is_404_and_intact(self):
        r = self.as_other.delete(f"/api/conversations/{self.conv.pk}/delete/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Conversation.objects.filter(pk=self.conv.pk).exists())

    def test_other_chat_into_owner_conversation_is_404(self):
        with mock.patch(
            "chat.views.ai.chat_completion",
            return_value=("x", "gemini", "m"),
        ), mock.patch("chat.views.ai.extract_facts", return_value=[]):
            r = self.as_other.post(
                "/api/chat/",
                data=json.dumps(
                    {"message": "hi", "conversation_id": self.conv.pk}
                ),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 404)

    def test_other_list_excludes_owner_memory(self):
        data = self.as_other.get("/api/memories/").json()
        facts = [m["fact"] for m in data["memories"]]
        self.assertNotIn("Owner private fact", facts)

    def test_other_cannot_confirm_reject_delete_owner_memory(self):
        for action in ("confirm", "reject"):
            r = self.as_other.post(f"/api/memories/{self.mem.pk}/{action}/")
            self.assertEqual(r.status_code, 404, action)
        r = self.as_other.delete(f"/api/memories/{self.mem.pk}/delete/")
        self.assertEqual(r.status_code, 404)
        mem = Memory.objects.get(pk=self.mem.pk)
        self.assertEqual(mem.status, Memory.Status.CONFIRMED)

    # --- the owner reaches their own data ---------------------------

    def test_owner_sees_own_data(self):
        data = self.as_owner.get("/api/conversations/").json()
        titles = [c["title"] for c in data["conversations"]]
        self.assertIn("Owner private chat", titles)
        r = self.as_owner.get(f"/api/conversations/{self.conv.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["messages"][0]["content"], "owner secret msg")

    # --- legacy NULL rows: the documented design caveat -------------

    def test_other_sees_legacy_until_owner_claims(self):
        data = self.as_other.get("/api/conversations/").json()
        titles = [c["title"] for c in data["conversations"]]
        self.assertIn("Legacy ownerless chat", titles)  # by design (NULL)
        mems = self.as_other.get("/api/memories/").json()
        facts = [m["fact"] for m in mems["memories"]]
        self.assertIn("Legacy ownerless fact", facts)  # by design (NULL)
        # Owner opens the legacy conversation -> claimed -> B loses it.
        r = self.as_owner.get(f"/api/conversations/{self.legacy_conv.pk}/")
        self.assertEqual(r.status_code, 200)
        data = self.as_other.get("/api/conversations/").json()
        titles = [c["title"] for c in data["conversations"]]
        self.assertNotIn("Legacy ownerless chat", titles)
