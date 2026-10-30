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

from django.db import models


class Conversation(models.Model):
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

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"


class Memory(models.Model):
    fact = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.fact[:60]
