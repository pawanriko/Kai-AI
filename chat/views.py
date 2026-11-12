"""HTTP endpoints for KAI — the whole API surface.

    GET    /api/ping/                  → {"status": "ok", ...}  (public)
    GET    /api/auth/me/               → session state (+ CSRF cookie)
    POST   /api/auth/setup/            → create the owner (bootstrap
                                         token required; only while
                                         zero users exist, then closed)
    POST   /api/auth/login/            → start a Django session
    POST   /api/auth/logout/           → end it
    GET    /api/models/                → provider catalogue   (login)
    GET    /api/usage/                 → cost-ledger readout  (login)
    POST   /api/chat/                  → send a message       (login)
    POST   /api/chat/plan/              → plan a request, no
                                         tools run            (login)
    POST   /api/chat/stream/           → send a message, reply
                                         streamed as NDJSON     (login)
    GET    /api/conversations/         → list conversations   (login)
    GET    /api/conversations/<id>/    → one conversation     (login)
    GET    /api/conversations/<id>/report/ → Markdown research
                                         report with sources  (login)
    DELETE /api/conversations/<id>/delete/                    (login)
    GET    /api/memories/              → stored facts         (login)
    POST   /api/memories/add/          → add a fact directly  (login)
    GET    /api/memories/duplicates/   → near-duplicate groups(login)
    POST   /api/memories/merge/        → merge a group        (login)
    GET    /api/memories/export/       → JSON/Markdown export (login)
    POST   /api/memories/<id>/confirm/ → approve a suggestion (login)
    POST   /api/memories/<id>/reject/  → drop a suggestion    (login)
    POST   /api/memories/<id>/scope/   → set project scope    (login)
    DELETE /api/memories/<id>/delete/                         (login)
    POST   /api/automation/propose/    → propose an action    (login)
    GET    /api/automation/actions/    → list actions         (login)
    POST   /api/automation/actions/<id>/approve/              (login)
    POST   /api/automation/actions/<id>/deny/                 (login)
    POST   /api/automation/actions/<id>/execute/              (login)
    GET    /api/automation/audit/      → audit trail          (login)

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
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import (
    agent,
    ai,
    automation,
    bundles,
    coding_tools,
    dedupe,
    ledger,
    reports,
    router,
)
from .models import (
    AuditLog,
    AutomationAction,
    Conversation,
    Memory,
    Message,
    SetupGuard,
    Usage,
)
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


@login_required_json
def usage_list(request):
    """GET /api/usage/ → cost-ledger readout (Phase 3): totals plus
    the 20 most recent calls. Token totals count only rows whose
    provider reported counts; `unknown_cost_calls` counts rows with
    no verified price (their cost is unknown, not zero). Only the
    signed-in user's rows are ever visible."""
    from django.db.models import Count, Q, Sum

    rows = Usage.objects.filter(user=request.user)
    totals = rows.aggregate(
        calls=Count("id"),
        total_prompt=Sum("prompt_tokens"),
        total_completion=Sum("completion_tokens"),
        total_cost=Sum("estimated_cost_usd"),
        unknown_cost_calls=Count("id", filter=Q(estimated_cost_usd__isnull=True)),
        unknown_token_calls=Count(
            "id", filter=Q(prompt_tokens__isnull=True)
        ),
    )
    return JsonResponse(
        {
            "totals": {
                "calls": totals["calls"],
                "prompt_tokens": totals["total_prompt"] or 0,
                "completion_tokens": totals["total_completion"] or 0,
                "estimated_cost_usd": totals["total_cost"],
                "unknown_cost_calls": totals["unknown_cost_calls"],
                "unknown_token_calls": totals["unknown_token_calls"],
            },
            "recent": [
                {
                    "id": u.pk,
                    "provider": u.provider,
                    "model": u.model,
                    "task": u.task,
                    "kind": u.kind,
                    "prompt_tokens": u.prompt_tokens,
                    "completion_tokens": u.completion_tokens,
                    "estimated_cost_usd": u.estimated_cost_usd,
                    "created_at": u.created_at.isoformat(),
                }
                for u in rows[:20]
            ],
        }
    )


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
    # here, before any agent or tool code runs. The coding tool
    # bundle (Phase 6) is gated exactly like the coding flag: both
    # reach the same workspace tools.
    if body.get("coding") or body.get("bundle") == "coding":
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


def _save_exchange(
    request, conversation, user_text, reply, trace,
    status=Message.Status.COMPLETE,
):
    """Save one exchange's messages. Returns the conversation
    (created here when None). No memory harvesting happens here —
    the caller decides when (or whether) facts are extracted, so
    the streaming endpoint can yield 'done' before the extraction
    call runs (Phase 2.4, finding F4)."""
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
    return conversation


def _harvest_memories(request, user_text, reply, on_usage=None):
    """Best-effort memory: new facts land as SUGGESTIONS (Step 6) —
    they reach future system prompts only after the user confirms
    them in the Memory panel. A second AI call, so the streaming
    endpoint runs it only AFTER yielding 'done' (Phase 2.4, F4).
    `on_usage` is forwarded to extract_facts for the cost ledger."""
    visible = _visible_memories(request)
    if visible.count() >= MAX_MEMORIES_PER_USER:
        return
    known = {m.fact.lower() for m in visible}
    known_facts = [m.fact for m in visible]
    for fact in ai.extract_facts(user_text, reply, on_usage=on_usage):
        fact = fact.strip()[:MAX_FACT_CHARS]
        lowered = fact.lower()
        if not fact or lowered in known:
            continue
        if any(marker in lowered for marker in _INSTRUCTION_MARKERS):
            continue
        # Phase 4: skip near-duplicates too — a fact KAI already
        # knows in slightly different words must not spawn a second
        # suggestion the user then has to merge by hand.
        if any(
            dedupe.is_near_duplicate(fact, known_fact)
            for known_fact in known_facts
        ):
            continue
        Memory.objects.create(
            fact=fact,
            user=request.user,
            status=Memory.Status.SUGGESTED,
        )
        known.add(lowered)
        known_facts.append(fact)


def _persist_exchange(
    request, conversation, user_text, reply, trace,
    status=Message.Status.COMPLETE,
    on_usage=None,
):
    """Save one exchange and (for completed replies) harvest memories.

    Used by the atomic /api/chat/ endpoint and by the streaming
    endpoint's interruption path. The streaming success path instead
    calls _save_exchange, yields 'done', and only then harvests —
    see chat_stream. `status` is Message.Status.INCOMPLETE only when
    the streaming endpoint saves a partial reply after a mid-stream
    provider failure (Phase 2.1) — the text is kept, explicitly
    flagged, and no facts are harvested from it: partial text is not
    a trustworthy source about the user.
    """
    conversation = _save_exchange(
        request, conversation, user_text, reply, trace, status=status
    )
    if status == Message.Status.COMPLETE:
        _harvest_memories(request, user_text, reply, on_usage=on_usage)
    return conversation


def _usage_callback(request, task, kind):
    """A cost-ledger callback for one exchange: the AI layer calls
    it with (provider, model, usage) per provider call, and it
    records one Usage row owned by the signed-in user. The task
    classification is computed once per exchange (it describes the
    user's message, not the individual call)."""

    def record(provider, model, usage):
        ledger.record_usage(request.user, provider, model, task, kind, usage)

    return record


@login_required_json
@rate_limit("chat", 30, 60)
def chat(request):
    """POST /api/chat/  {"message": str, "conversation_id"?: int,
    "model"?: str, "agent"?: bool, "coding"?: bool,
    "confirm_commands"?: bool, "bundle"?: str, "plan"?: [str],
    "plan_approved"?: bool} → {"reply", "conversation_id", "trace"}

    Phase 6: `bundle` restricts the agent's tools to a named set
    (unknown names are 400); `plan` carries an already-approved
    step list and requires `plan_approved: true` plus agent mode
    — an unapproved plan never executes.
    """
    error, body, user_text, conversation, messages = _chat_context(request)
    if error is not None:
        return error

    bundle = body.get("bundle") or None
    if bundle is not None:
        try:
            bundles.schemas_for(bundle)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    plan = body.get("plan") or None
    if plan is not None:
        if not body.get("agent") and not body.get("coding"):
            return JsonResponse(
                {"error": "a plan requires agent mode"}, status=400
            )
        if not body.get("plan_approved"):
            return JsonResponse(
                {"error": "approve the plan before executing it"},
                status=400,
            )
        if not isinstance(plan, list) or not all(
            isinstance(s, str) for s in plan
        ):
            return JsonResponse(
                {"error": "plan must be a list of steps"}, status=400
            )

    task = router.classify_task(user_text)
    trace = []
    if body.get("coding"):
        reply, trace = agent.run_agent(
            messages,
            body.get("model") or None,
            coding=True,
            on_usage=_usage_callback(request, task, Usage.Kind.AGENT),
            plan=plan,
            bundle=bundle,
        )
    elif body.get("agent"):
        reply, trace = agent.run_agent(
            messages,
            body.get("model") or None,
            on_usage=_usage_callback(request, task, Usage.Kind.AGENT),
            plan=plan,
            bundle=bundle,
        )
    else:
        reply = ai.ask_ai(
            messages,
            model=body.get("model") or None,
            on_usage=_usage_callback(request, task, Usage.Kind.CHAT),
        )
    if reply is None:
        return JsonResponse({"error": "AI unavailable"}, status=502)

    conversation = _persist_exchange(
        request,
        conversation,
        user_text,
        reply,
        trace,
        on_usage=_usage_callback(request, task, Usage.Kind.EXTRACT),
    )
    return JsonResponse(
        {"reply": reply, "conversation_id": conversation.pk, "trace": trace}
    )


def _stream_events(request, body, user_text, conversation, messages,
                   on_usage=None, extract_usage=None):
    """The NDJSON event generator behind /api/chat/stream/.

    Kept as a module-level generator (not a closure) so tests can
    iterate it manually and assert event ORDERING — in particular
    that 'done' is yielded before memory extraction runs (Phase
    2.4, F4). The view only wraps it in a StreamingHttpResponse.
    `on_usage` records the streamed call in the cost ledger;
    `extract_usage` records the memory-extraction call (a separate
    row, kind EXTRACT).
    """
    parts = []
    try:
        for chunk in ai.ask_ai_stream(
            messages, model=body.get("model") or None, on_usage=on_usage
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
    saved = _save_exchange(request, conversation, user_text, reply, [])
    yield json.dumps(
        {"type": "done", "conversation_id": saved.pk, "trace": []}
    ) + "\n"
    # Phase 2.4 (F4): 'done' is already on its way to the client
    # before this line runs — memory extraction is a second AI
    # call that used to delay 'done' by seconds. It still runs
    # before the response closes, so facts are never lost as
    # long as the client reads to the end of the stream (the
    # SPA does). The 2.1 interruption path above is unchanged:
    # it persists INCOMPLETE and never harvests.
    _harvest_memories(
        request, user_text, reply, on_usage=extract_usage
    )


@login_required_json
@rate_limit("chat", 30, 60)
def chat_plan(request):
    """POST /api/chat/plan/  {"message", "conversation_id"?: int,
    "model"?: str, "bundle"?: str} → {"plan": {"steps": [...]},
    "bundle", "conversation_id"}. Plan-then-execute, step 1: the
    model breaks the request into steps with NO tools running and
    nothing saved. The UI shows the steps; execution happens only
    when the user approves and /api/chat/ is called with the plan
    plus plan_approved. Shares the chat rate-limit bucket — a plan
    is an AI call like any other."""
    error, body, user_text, conversation, messages = _chat_context(request)
    if error is not None:
        return error

    bundle = body.get("bundle") or None
    if bundle is not None:
        try:
            bundles.schemas_for(bundle)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    task = router.classify_task(user_text)
    steps = agent.make_plan(
        messages,
        body.get("model") or None,
        bundle=bundle,
        on_usage=_usage_callback(request, task, Usage.Kind.AGENT),
    )
    if steps is None:
        return JsonResponse({"error": "AI unavailable"}, status=502)
    return JsonResponse(
        {
            "plan": {"steps": steps},
            "bundle": bundle,
            "conversation_id": conversation.pk if conversation else None,
        }
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
        task = router.classify_task(user_text)
        yield from _stream_events(
            request,
            body,
            user_text,
            conversation,
            messages,
            on_usage=_usage_callback(request, task, Usage.Kind.STREAM),
            extract_usage=_usage_callback(
                request, task, Usage.Kind.EXTRACT
            ),
        )

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
def conversation_report(request, pk):
    """GET /api/conversations/<id>/report/ → the conversation as a
    Markdown file, with a Sources section built ONLY from the stored
    agent traces (Phase 5: citations or it didn't happen)."""
    conversation = _claim(
        get_object_or_404(_visible_conversations(request), pk=pk),
        request,
    )
    markdown = reports.build_report(
        conversation.title, conversation.messages.all()
    )
    response = HttpResponse(markdown, content_type="text/markdown")
    response["Content-Disposition"] = (
        f'attachment; filename="kai-research-{conversation.pk}.md"'
    )
    return response


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


def _memory_dict(memory):
    return {
        "id": memory.pk,
        "fact": memory.fact,
        "status": memory.status,
        "origin": memory.origin,
        "project": memory.project,
        "created_at": memory.created_at.isoformat(),
    }


def _json_body(request):
    """Parsed JSON body, or None when the body is not JSON."""
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None


@login_required_json
def memory_list(request):
    """GET /api/memories/ → every visible fact, with its status.

    Phase 4 filters: ?q=<text> searches fact text (case-insensitive
    substring), ?project=<name> keeps one project scope (blank
    keeps only unscoped facts), ?status=suggested|confirmed.
    """
    rows = _visible_memories(request)
    query = request.GET.get("q", "").strip()
    if query:
        rows = rows.filter(fact__icontains=query)
    if "project" in request.GET:
        rows = rows.filter(project__iexact=request.GET["project"].strip())
    status = request.GET.get("status", "").strip()
    if status:
        if status not in Memory.Status.values:
            return JsonResponse(
                {"error": f"unknown status: {status}"}, status=400
            )
        rows = rows.filter(status=status)
    return JsonResponse({"memories": [_memory_dict(m) for m in rows]})


@login_required_json
@require_POST
def memory_add(request):
    """POST /api/memories/add/ {"fact", "project"?} → the fact, saved.

    The user typed it themselves, so it lands CONFIRMED with origin
    STATED — the confirmation gate exists for AI inferences, not
    for the user's own words. Empty facts, facts that duplicate
    (near or exact) a visible fact, and the memory cap are all
    refused with 400 rather than silently creating noise.
    """
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    fact = str(body.get("fact", "")).strip()[:MAX_FACT_CHARS]
    if not fact:
        return JsonResponse({"error": "fact is required"}, status=400)
    project = str(body.get("project", "")).strip()[:60]
    visible = _visible_memories(request)
    if visible.count() >= MAX_MEMORIES_PER_USER:
        return JsonResponse(
            {"error": "memory is full — forget something first"},
            status=400,
        )
    if any(
        dedupe.is_near_duplicate(fact, m.fact) for m in visible
    ):
        return JsonResponse(
            {"error": "a similar fact is already remembered"},
            status=400,
        )
    memory = Memory.objects.create(
        fact=fact,
        user=request.user,
        status=Memory.Status.CONFIRMED,
        origin=Memory.Origin.STATED,
        project=project,
    )
    return JsonResponse(_memory_dict(memory), status=201)


@login_required_json
@require_POST
def memory_scope(request, pk):
    """POST /api/memories/<id>/scope/ {"project"} → the fact, rescoped.

    An empty project clears the scope (the fact becomes global).
    """
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    memory = _claim(
        get_object_or_404(_visible_memories(request), pk=pk), request
    )
    memory.project = str(body.get("project", "")).strip()[:60]
    memory.save(update_fields=["project"])
    return JsonResponse(_memory_dict(memory))


@login_required_json
def memory_duplicates(request):
    """GET /api/memories/duplicates/ → near-duplicate groups.

    Each group names the keeper (confirmed first, then oldest) and
    lists every member. Advisory only — nothing merges until the
    user posts to /merge/.
    """
    groups = []
    for group in dedupe.group_duplicates(_visible_memories(request)):
        keeper = dedupe.pick_keeper(group)
        groups.append(
            {
                "keeper": _memory_dict(keeper),
                "members": [_memory_dict(m) for m in group],
            }
        )
    return JsonResponse({"groups": groups})


@login_required_json
@require_POST
def memory_merge(request):
    """POST /api/memories/merge/ {"keep_id", "drop_ids": [...]} →
    {"kept": id, "deleted": n}. Every id must be a visible memory;
    the keeper is never deleted. Explicit user action only — the
    duplicates endpoint never merges on its own.
    """
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    keep_id = body.get("keep_id")
    drop_ids = body.get("drop_ids") or []
    if not keep_id or not isinstance(drop_ids, list) or not drop_ids:
        return JsonResponse(
            {"error": "keep_id and a non-empty drop_ids list required"},
            status=400,
        )
    if keep_id in drop_ids:
        return JsonResponse(
            {"error": "keep_id must not be in drop_ids"}, status=400
        )
    visible = _visible_memories(request)
    keeper = _claim(get_object_or_404(visible, pk=keep_id), request)
    drops = []
    for drop_id in drop_ids:
        drops.append(get_object_or_404(visible, pk=drop_id))
    for memory in drops:
        memory.delete()
    return JsonResponse({"kept": keeper.pk, "deleted": len(drops)})


@login_required_json
def memory_export(request):
    """GET /api/memories/export/?format=json|md[&project=...] →
    the visible facts as a downloadable file. JSON is the full
    record; Markdown groups by status for reading. Owner-filtered
    like every other memory endpoint.
    """
    fmt = request.GET.get("format", "json").strip().lower()
    if fmt not in ("json", "md"):
        return JsonResponse(
            {"error": "format must be json or md"}, status=400
        )
    rows = _visible_memories(request)
    if "project" in request.GET:
        rows = rows.filter(project__iexact=request.GET["project"].strip())
    memories = list(rows)
    if fmt == "json":
        payload = json.dumps(
            {"memories": [_memory_dict(m) for m in memories]},
            indent=2,
        )
        response = HttpResponse(payload, content_type="application/json")
        response["Content-Disposition"] = (
            'attachment; filename="kai-memories.json"'
        )
        return response
    lines = ["# KAI memories", ""]
    for status in (Memory.Status.CONFIRMED, Memory.Status.SUGGESTED):
        lines.append(f"## {status.capitalize()}")
        lines.append("")
        group = [m for m in memories if m.status == status]
        if not group:
            lines.append("_None._")
            lines.append("")
            continue
        for memory in group:
            scope = f" [{memory.project}]" if memory.project else ""
            lines.append(f"- {memory.fact}{scope}")
        lines.append("")
    response = HttpResponse("\n".join(lines), content_type="text/markdown")
    response["Content-Disposition"] = (
        'attachment; filename="kai-memories.md"'
    )
    return response


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


# ---------------------------------------------------------------- automation
# Phase 8: audit log + per-action approvals FIRST. Every endpoint is
# owner-scoped (strict user filter — no legacy visibility), and
# execution is default-deny: the service layer refuses anything
# that is not APPROVED, and these views map that refusal to 403.


def _automation_dict(action):
    return {
        "id": action.pk,
        "target": action.target,
        "action": action.action,
        "payload": action.payload,
        "description": action.description,
        "status": action.status,
        "result": action.result,
        "created_at": action.created_at.isoformat(),
        "decided_at": action.decided_at.isoformat() if action.decided_at else None,
        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
    }


def _audit_dict(entry):
    return {
        "id": entry.pk,
        "action_pk": entry.action_pk,
        "target": entry.target,
        "action_name": entry.action_name,
        "description": entry.description,
        "event": entry.event,
        "detail": entry.detail,
        "created_at": entry.created_at.isoformat(),
    }


@login_required_json
@require_POST
@rate_limit("automation", 30, 60)
def automation_propose(request):
    """POST /api/automation/propose/ {"target", "action", "payload",
    "description"} → 201 + the PENDING action. Proposing never
    executes anything."""
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    try:
        action = automation.propose_action(
            request.user,
            body.get("target"),
            body.get("action"),
            body.get("payload"),
            body.get("description"),
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_automation_dict(action), status=201)


@login_required_json
def automation_list(request):
    """GET /api/automation/actions/ → the owner's actions, newest
    first. ?status= filters to one status."""
    rows = AutomationAction.objects.filter(user=request.user)
    status = request.GET.get("status", "").strip()
    if status:
        if status not in AutomationAction.Status.values:
            return JsonResponse(
                {"error": f"unknown status: {status}"}, status=400
            )
        rows = rows.filter(status=status)
    return JsonResponse({"actions": [_automation_dict(a) for a in rows]})


def _owned_action(request, pk):
    return get_object_or_404(
        AutomationAction.objects.filter(user=request.user), pk=pk
    )


@login_required_json
@require_POST
@rate_limit("automation", 30, 60)
def automation_approve(request, pk):
    """POST /api/automation/actions/<id>/approve/ → the APPROVED
    action. Approval alone executes nothing."""
    action = _owned_action(request, pk)
    try:
        automation.decide_action(action, approve=True)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_automation_dict(action))


@login_required_json
@require_POST
@rate_limit("automation", 30, 60)
def automation_deny(request, pk):
    """POST /api/automation/actions/<id>/deny/ → the DENIED action."""
    action = _owned_action(request, pk)
    try:
        automation.decide_action(action, approve=False)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_automation_dict(action))


@login_required_json
@require_POST
@rate_limit("automation", 30, 60)
def automation_execute(request, pk):
    """POST /api/automation/actions/<id>/execute/ → the EXECUTED
    (or FAILED) action with its result. Default-deny: an action
    that was never approved is 403 and its runner is never
    touched."""
    action = _owned_action(request, pk)
    try:
        automation.execute_action(action)
    except PermissionError as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_automation_dict(action))


@login_required_json
def automation_audit(request):
    """GET /api/automation/audit/ → the owner's audit trail, newest
    first. ?event= filters to one event type. Append-only: there
    is no endpoint that modifies or deletes entries."""
    rows = AuditLog.objects.filter(user=request.user)
    event = request.GET.get("event", "").strip()
    if event:
        if event not in AuditLog.Event.values:
            return JsonResponse(
                {"error": f"unknown event: {event}"}, status=400
            )
        rows = rows.filter(event=event)
    return JsonResponse({"entries": [_audit_dict(e) for e in rows]})
