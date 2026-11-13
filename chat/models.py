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

    class Origin(models.TextChoices):
        # Phase 4: how the fact arrived. INFERRED facts are AI
        # extractions (they start SUGGESTED, behind the confirmation
        # gate); STATED facts were typed by the user themselves
        # (they start CONFIRMED — no gate needed for the user's own
        # words). Existing rows are all AI extractions, hence the
        # default.
        INFERRED = "inferred", "Inferred"
        STATED = "stated", "Stated"

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
    origin = models.CharField(
        max_length=16,
        choices=Origin.choices,
        default=Origin.INFERRED,
    )
    # Phase 4: project scope. Blank means global — the fact applies
    # everywhere. A label (e.g. "kai") scopes the fact to that
    # project for searching, filtering, and export. Scoping is
    # organizational: confirmed facts still reach every system
    # prompt (there is no conversation→project link to filter on),
    # so scope never silently hides knowledge from the AI.
    project = models.CharField(max_length=60, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.fact[:60]


class AutomationAction(models.Model):
    """One proposed automation action (Phase 8), gated by approval.

    Default-deny: an action is created PENDING and NOTHING executes
    until the owner approves it; execution requires status
    APPROVED and moves it to EXECUTED/FAILED in the same step, so
    one approval can never run twice. Ownership is strict
    (non-null user, no legacy NULL rows): automation rows are all
    created post-auth, and no other account may even see them.
    """

    class Target(models.TextChoices):
        BROWSER = "browser", "Browser"
        COMPUTER = "computer", "Computer (Open Interpreter)"
        WORKFLOW = "workflow", "Workflow (n8n)"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        EXECUTED = "executed", "Executed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="automation_actions",
    )
    target = models.CharField(max_length=16, choices=Target.choices)
    action = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    description = models.CharField(max_length=300)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    result = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.target}/{self.action} [{self.status}]"


class AuditLog(models.Model):
    """Append-only audit trail (Phase 8): every automation event,
    denormalized so the trail survives deletion of the action it
    describes. There is intentionally no update or delete path —
    the log is written once and only ever read."""

    class Event(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        EXECUTED = "executed", "Executed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    # The AutomationAction pk at event time (a snapshot, not a
    # foreign key — the entry must outlive the action).
    action_pk = models.IntegerField()
    target = models.CharField(max_length=16)
    action_name = models.CharField(max_length=40)
    description = models.CharField(max_length=300)
    event = models.CharField(max_length=16, choices=Event.choices)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.event} action {self.action_pk}"


class Usage(models.Model):
    """Cost ledger (Phase 3): one row per provider call.

    Token counts and cost are NULL when the provider did not report
    them — a streamed call, or a model with no verified price — so
    NULL always means "unknown", never zero. A zero cost is recorded
    only for ids the router proves free (OpenRouter `:free`).
    `task` is the router's classification of the exchange; `kind`
    says which path made the call. Rows are created only by
    authenticated requests, so the owner FK is never NULL (unlike
    the pre-auth Conversation/Memory rows).
    """

    class Kind(models.TextChoices):
        CHAT = "chat", "Chat"
        STREAM = "stream", "Stream"
        AGENT = "agent", "Agent"
        EXTRACT = "extract", "Memory extraction"
        POLISH = "polish", "Prompt polish"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usage",
    )
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=128)
    task = models.CharField(max_length=16, null=True, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    prompt_tokens = models.IntegerField(null=True, blank=True)
    completion_tokens = models.IntegerField(null=True, blank=True)
    estimated_cost_usd = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider}::{self.model} ({self.kind})"
