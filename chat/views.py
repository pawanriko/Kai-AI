"""JSON API for KAI, including session authentication and per-user data isolation."""

import json
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie

from . import ai
from .models import Conversation, Memory, Message

SYSTEM_PROMPT = (
    "You are KAI, a friendly personal AI assistant. Be helpful, clear, "
    "and concise. You remember facts about the user across conversations."
)


def _json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid JSON"}, status=400)


def _authenticated(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication required"}, status=401)
        return view(request, *args, **kwargs)
    return wrapped


def ping(request):
    return JsonResponse({"status": "ok", "message": "pong from Django"})


@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


def auth_me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse({
        "authenticated": True,
        "user": {"id": request.user.pk, "username": request.user.get_username()},
    })


def auth_register(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    body, error = _json_body(request)
    if error:
        return error
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if len(username) < 3 or len(username) > 150:
        return JsonResponse({"error": "username must be 3 to 150 characters"}, status=400)
    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({"error": "username already exists"}, status=409)
    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    user = User.objects.create_user(username=username, password=password)
    login(request, user)
    return JsonResponse({
        "authenticated": True,
        "user": {"id": user.pk, "username": user.get_username()},
    }, status=201)


def auth_login(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    body, error = _json_body(request)
    if error:
        return error
    user = authenticate(
        request,
        username=str(body.get("username") or "").strip(),
        password=str(body.get("password") or ""),
    )
    if user is None:
        return JsonResponse({"error": "invalid username or password"}, status=401)
    login(request, user)
    return JsonResponse({
        "authenticated": True,
        "user": {"id": user.pk, "username": user.get_username()},
    })


def auth_logout(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    logout(request)
    return JsonResponse({"authenticated": False})


def _system_prompt(user):
    facts = list(Memory.objects.filter(user=user).values_list("fact", flat=True))
    if not facts:
        return SYSTEM_PROMPT
    facts_text = "\\n".join(f"- {fact}" for fact in facts)
    return f"{SYSTEM_PROMPT}\\n\\nFacts you know about the user:\\n{facts_text}"


@_authenticated
def chat(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    body, error = _json_body(request)
    if error:
        return error

    user_text = str(body.get("message") or "").strip()
    if not user_text:
        return JsonResponse({"error": "message is required"}, status=400)

    conversation = None
    if body.get("conversation_id"):
        conversation = get_object_or_404(
            Conversation, pk=body["conversation_id"], user=request.user
        )

    history = []
    if conversation is not None:
        history = [
            {"role": message.role, "content": message.content}
            for message in conversation.messages.all()
        ]
    messages = (
        [{"role": "system", "content": _system_prompt(request.user)}]
        + history
        + [{"role": "user", "content": user_text}]
    )

    reply = ai.ask_ai(messages, model=body.get("model") or None)
    if reply is None:
        return JsonResponse({"error": "AI unavailable"}, status=502)

    if conversation is None:
        conversation = Conversation.objects.create(
            user=request.user, title=user_text[:60] or "New conversation"
        )
    Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_text
    )
    Message.objects.create(
        conversation=conversation, role=Message.Role.ASSISTANT, content=reply
    )
    conversation.save(update_fields=["updated_at"])

    known = {
        fact.lower()
        for fact in Memory.objects.filter(user=request.user).values_list("fact", flat=True)
    }
    for fact in ai.extract_facts(user_text, reply):
        fact = str(fact).strip()
        if fact and fact.lower() not in known:
            Memory.objects.create(user=request.user, fact=fact)
            known.add(fact.lower())

    return JsonResponse({"reply": reply, "conversation_id": conversation.pk})


@_authenticated
def conversation_list(request):
    data = [
        {
            "id": conversation.pk,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "message_count": conversation.messages.count(),
        }
        for conversation in Conversation.objects.filter(user=request.user)
    ]
    return JsonResponse({"conversations": data})


@_authenticated
def conversation_detail(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, user=request.user)
    return JsonResponse({
        "id": conversation.pk,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "messages": [
            {
                "id": message.pk,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            for message in conversation.messages.all()
        ],
    })


@_authenticated
def conversation_delete(request, pk):
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    conversation = get_object_or_404(Conversation, pk=pk, user=request.user)
    conversation.delete()
    return JsonResponse({}, status=204)


@_authenticated
def memory_list(request):
    data = [
        {"id": memory.pk, "fact": memory.fact, "created_at": memory.created_at.isoformat()}
        for memory in Memory.objects.filter(user=request.user)
    ]
    return JsonResponse({"memories": data})


@_authenticated
def memory_delete(request, pk):
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    memory = get_object_or_404(Memory, pk=pk, user=request.user)
    memory.delete()
    return JsonResponse({}, status=204)
