"""Database models for KAI.

A model is a Python class that Django turns into a database table:
each class attribute becomes a column, each object becomes a row.
These three classes are KAI's entire long-term memory:

- Conversation — one chat thread (v1 kept threads in localStorage).
- Message      — one user/assistant message inside a conversation.
- Memory       — one durable fact KAI has learned about the user
                 (v1 stored these as localStorage JSON; here they are
                 real rows the user can list and delete).
"""

from django.conf import settings
from django.db import models


class SetupGuard(models.Model):
    """Singleton row (pk=1, created by migration 0004).

    First-owner setup UPDATEs this row as the first statement of its
    transaction. That takes the write lock up front (Postgres row
    lock; SQLite database lock with busy timeout), serializing
    concurrent setup attempts — so two racing setup requests can
    never both pass the "no users exist yet" check. Exactly one
    owner can ever be created through the setup endpoint.
    """

    locked_at = models.DateTimeField(auto_now=True)


class Conversation(models.Model):
    # Owner (Phase 1): nullable so pre-auth rows survive the migration
    # untouched. NULL means "legacy" — visible to the signed-in owner
    # and claimed by them on first use. New rows always get a user.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=120, default="New conversation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    class Status(models.TextChoices):
        # COMPLETE is the historical norm: every message saved before
        # Phase 2.1 gets it by default (migration 0005). INCOMPLETE is
        # set only for an assistant reply whose stream was interrupted
        # mid-generation (Phase 2.1): the partial text is kept for the
        # record and shown labelled in the UI, but it is never treated
        # as a finished answer — it stays out of future AI context.
        COMPLETE = "complete", "Complete"
        INCOMPLETE = "incomplete", "Incomplete"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.COMPLETE,
    )
    content = models.TextField()
    # Agent runs record their tool steps here: [{tool, args, result}].
    # Plain chat messages simply keep the empty list.
    trace = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"


class Memory(models.Model):
    class Status(models.TextChoices):
        # Extracted facts start as SUGGESTED (Phase 1 Step 6): they
        # are AI inferences, so they never reach the system prompt
        # until the user confirms them in the Memory panel.
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memories",
        null=True,
        blank=True,
    )
    fact = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SUGGESTED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.fact[:60]
