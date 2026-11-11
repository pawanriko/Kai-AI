"""HTTP endpoints for KAI — the whole API surface.

    GET    /api/ping/                  → {"status": "ok", ...}  (public)
    GET    /api/auth/me/               → session state (+ CSRF cookie)
    POST   /api/auth/setup/            → create the owner (bootstrap
                                         token required; only while
                                         zero users exist, then closed)
    POST   /api/auth/login/            → start a Django session
    POST   /api/auth/logout/           → end it
    GET    /api/models/                → provider catalogue   (login)
    POST   /api/chat/                  → send a message       (login)
    POST   /api/chat/stream/           → send a message, reply
                                         streamed as NDJSON     (login)
    GET    /api/conversations/         → list conversations   (login)
    GET    /api/conversations/<id>/    → one conversation     (login)
    DELETE /api/conversations/<id>/delete/                    (login)
    GET    /api/memories/              → stored facts         (login)
    POST   /api/memories/<id>/confirm/ → approve a suggestion (login)
    POST   /api/memories/<id>/reject/  → drop a suggestion    (login)
    DELETE /api/memories/<id>/delete/                         (login)

Phase 1 security shape: everything except ping + the auth endpoints
requires a logged-in session; every state-changing request requires
a valid CSRF token (no csrf_exempt anywhere); conversations and
memories carry an owner and are filtered by it. Rows created before
auth existed have user=NULL ("legacy") — they stay visible to the
signed-in owner and are claimed on first use, so no data is lost.

Chat flow: load (or create) the conversation, rebuild its messages,
prepend a system prompt carrying the user's CONFIRMED memories,
call ai.ask_ai (or the agent), save both messages, then extract new
facts as SUGGESTIONS the user can confirm or reject.
"""

import hmac
import json
import os
import time
from functools import wraps

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import agent, ai, coding_tools
from .models import Conversation, Memory, Message, SetupGuard
from .ratelimit import rate_limit

SYSTEM_PROMPT = (
    "You are KAI, a friendly personal AI assistant. Be helpful, clear, "
    "and concise. You remember facts about the user across conversations."
)

MAX_MESSAGE_CHARS = 8000        # Step 4: reject oversized messages
MAX_HISTORY_MESSAGES = 40       # Step 4: cap history sent upstream
MAX_FACT_CHARS = 300            # Step 6: facts are one line, not essays
MAX_MEMORIES_PER_USER = 250     # Step 6: extraction stops at the cap

# Extracted "facts" that read like orders to the assistant are dropped:
# memory must never become a back-door system prompt (Step 6). The
# confirmation gate is the real control; this is a cheap first filter.
_INSTRUCTION_MARKERS = (
    "ignore previous",
    "ignore all",
    "system prompt",
    "you must always",
    "always obey",
    "instruction:",
)


def login_required_json(view):
    """401 JSON instead of a redirect — this API has no login page."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "Login required."}, status=401
            )
        return view(request, *args, **kwargs)

    return wrapped


# ------------------------------------------------------------------ auth

def ping(request):
    """GET /api/ping/ → a tiny JSON object saying the server is alive."""
    return JsonResponse({"status": "ok", "message": "pong from Django"})


def _setup_token():
    """The deployment-only bootstrap secret (env var KAI_SETUP_TOKEN).

    Read at request time so deployments and tests can set it without
    a restart. Empty means web setup is DISABLED — the endpoint then
    refuses everyone, and the owner is created with
    `createsuperuser` instead. The token is never stored in the
    database and never logged."""
    return os.environ.get("KAI_SETUP_TOKEN", "")


@ensure_csrf_cookie
def me(request):
    """GET /api/auth/me/ → who am I? Also plants the CSRF cookie the
    SPA needs before any POST (login included)."""
    user = request.user
    return JsonResponse(
        {
            "authenticated": user.is_authenticated,
            "username": user.username if user.is_authenticated else None,
            "needs_setup": not get_user_model().objects.exists(),
            "setup_enabled": bool(_setup_token()),
            "coding_enabled": coding_tools.execution_enabled(),
        }
    )


@require_POST
@rate_limit("setup", 5, 300)
def setup(request):
    """POST /api/auth/setup/ {"username", "password", "setup_token"}
    → create the owner account.

    Three independent locks, because this endpoint is public until
    the first user exists and the whole instance is the prize:

    1. Bootstrap secret: the caller must present KAI_SETUP_TOKEN,
       a secret that exists only in the deployment's environment
       (compared in constant time). No token configured → web setup
       is disabled outright.
    2. Atomicity: creation runs in one transaction that locks and
       touches the SetupGuard singleton row first, serializing
       concurrent attempts on Postgres and SQLite alike — the
       "no users yet" check and the insert can never interleave.
    3. Permanent close: the moment any user exists, setup is over,
       token or not.
    """
    expected = _setup_token()
    if not expected:
        return JsonResponse(
            {
                "error": "Web setup is disabled on this server. "
                "Set KAI_SETUP_TOKEN in the server environment to "
                "enable it, or create the owner with createsuperuser."
            },
            status=403,
        )
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    provided = body.get("setup_token") or ""
    if not hmac.compare_digest(provided, expected):
        return JsonResponse({"error": "Invalid setup token."}, status=403)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return JsonResponse(
            {"error": "username and password are required"}, status=400
        )
    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)

    user, state = _create_owner_atomically(username, password)
    if state == "closed":
        return JsonResponse(
            {"error": "Setup is already complete."}, status=403
        )
    if state == "busy":
        return JsonResponse(
            {"error": "Setup is busy — try again in a moment."},
            status=503,
        )
    login(request, user)
    return JsonResponse({"ok": True, "username": user.username})


def _create_owner_atomically(username, password):
    """Create the first user, serialized against racing requests.

    Returns (user, None) on success, (None, "closed") when a user
    already exists, (None, "busy") if the database stayed locked.

    The transaction WRITES the SetupGuard row as its first statement:
    on Postgres that takes the row lock, on a file SQLite database
    the write lock — either way a racer waits for this transaction
    to commit, then sees the user that now exists. SQLite's
    shared-cache mode (used by Django's test runner) raises
    'table is locked' instead of waiting, so lock contention is
    retried a few times; on Postgres the retry simply never fires.
    The exists-check lives INSIDE the transaction, so a retry can
    never create a second owner. The password is hashed BEFORE the
    transaction (PBKDF2 is deliberately slow — it must not run while
    the write lock is held).
    """
    user_model = get_user_model()
    user = user_model(username=username, is_staff=True, is_superuser=True)
    user.set_password(password)
    for attempt in range(5):
        try:
            with transaction.atomic():
                if not SetupGuard.objects.filter(pk=1).exists():
                    SetupGuard.objects.create(pk=1)
                SetupGuard.objects.filter(pk=1).update(
                    locked_at=timezone.now()
                )
                if user_model.objects.exists():
                    return None, "closed"
                user.save()
                return user, None
        except (OperationalError, IntegrityError) as exc:
            if isinstance(exc, OperationalError) and (
                "locked" not in str(exc).lower()
            ):
                raise
            if attempt == 4:
                return None, "busy"
            time.sleep(0.1 * (attempt + 1))
    return None, "busy"


@require_POST
@rate_limit("login", 10, 300)
def login_view(request):
    """POST /api/auth/login/ {"username", "password"} → session."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    user = authenticate(
        request,
        username=(body.get("username") or "").strip(),
        password=body.get("password") or "",
    )
    if user is None:
        return JsonResponse(
            {"error": "Invalid username or password."}, status=401
        )
    login(request, user)
    return JsonResponse({"ok": True, "username": user.username})


@require_POST
@login_required_json
def logout_view(request):
    """POST /api/auth/logout/ → end the session."""
    logout(request)
    return JsonResponse({"ok": True})


# ------------------------------------------------------------------ data

def _visible_conversations(request):
    """Conversations the signed-in user may see: theirs, plus legacy
    (ownerless, pre-auth) rows that nobody has claimed yet."""
    return Conversation.objects.filter(
        Q(user=request.user) | Q(user__isnull=True)
    )


def _visible_memories(request):
    return Memory.objects.filter(
        Q(user=request.user) | Q(user__isnull=True)
    )


def _claim(obj, request):
    """Adopt a legacy row on first use so ownership becomes exact."""
    if obj.user_id is None:
        obj.user = request.user
        obj.save(update_fields=["user"])
    return obj


@login_required_json
def model_catalog(request):
    """GET /api/models/ → providers + models for the UI picker.

    Each provider is flagged `configured` (its API key exists in .env)
    so the UI can disable choices that would only fail.
    """
    return JsonResponse({"providers": ai.catalog()})


def _system_prompt(request):
    facts = [
        m.fact
        for m in _visible_memories(request).filter(
            status=Memory.Status.CONFIRMED
        )
    ]
    if not facts:
        return SYSTEM_PROMPT
    facts_text = "\n".join(f"- {fact}" for fact in facts)
    return f"{SYSTEM_PROMPT}\n\nFacts you know about the user:\n{facts_text}"


def _chat_context(request):
    """Shared pre-flight for /api/chat/ and /api/chat/stream/.

    Validates the body, enforces the coding kill switch, resolves
    (and claims) the conversation and builds the provider message
    list. Returns (error_response, body, user_text, conversation,
    messages) — error_response is None when the caller may proceed.
    Keeping ONE implementation means the streaming endpoint can never
    drift weaker than the plain one.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405), None, "", None, []
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400), None, "", None, []

    user_text = (body.get("message") or "").strip()
    if not user_text:
        return JsonResponse({"error": "message is required"}, status=400), None, "", None, []
    if len(user_text) > MAX_MESSAGE_CHARS:
        return (
            JsonResponse(
                {"error": f"Message too long (limit {MAX_MESSAGE_CHARS} characters)."},
                status=400,
            ),
            None, "", None, [],
        )

    # Step 0 containment: coding execution is a server-side decision.
    # The client toggle means nothing on its own — with the kill
    # switch off (always, in production) the request is rejected
    # here, before any agent or tool code runs.
    if body.get("coding"):
        if not coding_tools.execution_enabled():
            return (
                JsonResponse(
                    {"error": "Coding mode is disabled on this server."},
                    status=403,
                ),
                None, "", None, [],
            )
        if not body.get("confirm_commands"):
            return (
                JsonResponse(
                    {
                        "error": "Coding mode runs commands on the server. "
                        "Confirm the session first (confirm_commands)."
                    },
                    status=400,
                ),
                None, "", None, [],
            )

    conversation = None
    if body.get("conversation_id"):
        conversation = _claim(
            get_object_or_404(
                _visible_conversations(request),
                pk=body["conversation_id"],
            ),
            request,
        )

    history = []
    if conversation is not None:
        history = [
            {"role": m.role, "content": m.content}
            for m in conversation.messages.all()
            # An interrupted (Phase 2.1) assistant reply is partial
            # text, not a finished answer: never feed it back to the
            # AI as trusted context. The user's own messages around
            # it still count.
            if not (
                m.role == Message.Role.ASSISTANT
                and m.status == Message.Status.INCOMPLETE
            )
        ][-MAX_HISTORY_MESSAGES:]
    messages = (
        [{"role": "system", "content": _system_prompt(request)}]
        + history
        + [{"role": "user", "content": user_text}]
    )
    return None, body, user_text, conversation, messages


def _persist_exchange(
    request, conversation, user_text, reply, trace,
    status=Message.Status.COMPLETE,
):
    """Save one exchange and (for completed replies) harvest memories.

    Shared by the plain and streaming chat endpoints so both persist
    identically. Returns the conversation (created here when None).
    `status` is Message.Status.INCOMPLETE only when the streaming
    endpoint saves a partial reply after a mid-stream provider
    failure (Phase 2.1) — the text is kept, explicitly flagged, and
    no facts are harvested from it: partial text is not a trustworthy
    source about the user.
    """
    if conversation is None:
        conversation = Conversation.objects.create(
            title=user_text[:60] or "New conversation",
            user=request.user,
        )
    Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_text
    )
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=reply,
        trace=trace,
        status=status,
    )
    conversation.save(update_fields=["updated_at"])

    # Best-effort memory: new facts land as SUGGESTIONS (Step 6) —
    # they reach future system prompts only after the user confirms
    # them in the Memory panel.
    visible = _visible_memories(request)
    if status == Message.Status.COMPLETE and visible.count() < MAX_MEMORIES_PER_USER:
        known = {m.fact.lower() for m in visible}
        for fact in ai.extract_facts(user_text, reply):
            fact = fact.strip()[:MAX_FACT_CHARS]
            lowered = fact.lower()
            if not fact or lowered in known:
                continue
            if any(marker in lowered for marker in _INSTRUCTION_MARKERS):
                continue
            Memory.objects.create(
                fact=fact,
                user=request.user,
                status=Memory.Status.SUGGESTED,
            )
            known.add(lowered)
    return conversation


@login_required_json
@rate_limit("chat", 30, 60)
def chat(request):
    """POST /api/chat/  {"message": str, "conversation_id"?: int,
    "model"?: str, "agent"?: bool, "coding"?: bool,
    "confirm_commands"?: bool} → {"reply", "conversation_id", "trace"}"""
    error, body, user_text, conversation, messages = _chat_context(request)
    if error is not None:
        return error

    trace = []
    if body.get("coding"):
        reply, trace = agent.run_agent(
            messages, body.get("model") or None, coding=True
        )
    elif body.get("agent"):
        reply, trace = agent.run_agent(messages, body.get("model") or None)
    else:
        reply = ai.ask_ai(messages, model=body.get("model") or None)
    if reply is None:
        return JsonResponse({"error": "AI unavailable"}, status=502)

    conversation = _persist_exchange(
        request, conversation, user_text, reply, trace
    )
    return JsonResponse(
        {"reply": reply, "conversation_id": conversation.pk, "trace": trace}
    )


@login_required_json
@rate_limit("chat", 30, 60)
def chat_stream(request):
    """POST /api/chat/stream/ — plain chat with a streamed reply.

    Same validation, auth, CSRF, rate limit and persistence as
    /api/chat/ (shared helpers above); the reply arrives as NDJSON
    events, one per line:
        {"type": "chunk", "text": "..."}        (zero or more)
        {"type": "done", "conversation_id": N}  (success, at the end)
        {"type": "error", "error": "AI unavailable"}
        {"type": "error", "error": "AI response interrupted",
         "interrupted": true, "conversation_id": N}
            (Phase 2.1: the provider failed AFTER producing text.
            The partial reply has been saved with status INCOMPLETE —
            never as a finished answer — and no 'done' follows.)
    Agent and coding modes are NOT streamed — they keep using
    /api/chat/ so their step traces stay atomic. Once the stream has
    started the HTTP status is committed, so a provider that fails
    before producing any text surfaces as an error EVENT, not a 502.
    """
    error, body, user_text, conversation, messages = _chat_context(request)
    if error is not None:
        return error
    if body.get("agent") or body.get("coding"):
        return JsonResponse(
            {"error": "Agent and coding modes use /api/chat/."},
            status=400,
        )

    def events():
        parts = []
        try:
            for chunk in ai.ask_ai_stream(
                messages, model=body.get("model") or None
            ):
                parts.append(chunk)
                yield json.dumps({"type": "chunk", "text": chunk}) + "\n"
        except ai.StreamInterrupted:
            # Provider died mid-reply: persist the partial text
            # flagged INCOMPLETE and report the interruption. The
            # client keeps the partial bubble, labelled — it is
            # never presented as a completed answer.
            saved = _persist_exchange(
                request,
                conversation,
                user_text,
                "".join(parts),
                [],
                status=Message.Status.INCOMPLETE,
            )
            yield json.dumps(
                {
                    "type": "error",
                    "error": "AI response interrupted",
                    "interrupted": True,
                    "conversation_id": saved.pk,
                }
            ) + "\n"
            return
        reply = "".join(parts)
        if not reply:
            yield json.dumps(
                {"type": "error", "error": "AI unavailable"}
            ) + "\n"
            return
        saved = _persist_exchange(request, conversation, user_text, reply, [])
        yield json.dumps(
            {"type": "done", "conversation_id": saved.pk, "trace": []}
        ) + "\n"

    response = StreamingHttpResponse(events(), content_type="application/x-ndjson")
    response["X-Accel-Buffering"] = "no"
    return response


@login_required_json
def conversation_list(request):
    """GET /api/conversations/ → sidebar data, newest activity first."""
    data = [
        {
            "id": c.pk,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "message_count": c.messages.count(),
        }
        for c in _visible_conversations(request)
    ]
    return JsonResponse({"conversations": data})


@login_required_json
def conversation_detail(request, pk):
    """GET /api/conversations/<id>/ → the conversation + all messages."""
    conversation = _claim(
        get_object_or_404(_visible_conversations(request), pk=pk),
        request,
    )
    return JsonResponse(
        {
            "id": conversation.pk,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "messages": [
                {
                    "id": m.pk,
                    "role": m.role,
                    "content": m.content,
                    "status": m.status,
                    "trace": m.trace,
                    "created_at": m.created_at.isoformat(),
                }
                for m in conversation.messages.all()
            ],
        }
    )


@login_required_json
def conversation_delete(request, pk):
    """DELETE /api/conversations/<id>/delete/ → 204, messages go too."""
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    conversation = get_object_or_404(
        _visible_conversations(request), pk=pk
    )
    conversation.delete()
    return JsonResponse({}, status=204)


@login_required_json
def memory_list(request):
    """GET /api/memories/ → every visible fact, with its status."""
    data = [
        {
            "id": m.pk,
            "fact": m.fact,
            "status": m.status,
            "created_at": m.created_at.isoformat(),
        }
        for m in _visible_memories(request)
    ]
    return JsonResponse({"memories": data})


@login_required_json
@require_POST
def memory_confirm(request, pk):
    """POST /api/memories/<id>/confirm/ → a suggestion becomes a
    confirmed fact and starts reaching the system prompt."""
    memory = _claim(
        get_object_or_404(_visible_memories(request), pk=pk), request
    )
    memory.status = Memory.Status.CONFIRMED
    memory.save(update_fields=["status"])
    return JsonResponse({"id": memory.pk, "status": memory.status})


@login_required_json
@require_POST
def memory_reject(request, pk):
    """POST /api/memories/<id>/reject/ → drop a suggestion for good."""
    memory = get_object_or_404(_visible_memories(request), pk=pk)
    memory.delete()
    return JsonResponse({}, status=204)


@login_required_json
def memory_delete(request, pk):
    """DELETE /api/memories/<id>/delete/ → 204; KAI forgets the fact."""
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    memory = get_object_or_404(_visible_memories(request), pk=pk)
    memory.delete()
    return JsonResponse({}, status=204)
