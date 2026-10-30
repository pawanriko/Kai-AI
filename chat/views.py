"""HTTP endpoints for KAI — the whole API surface.

    GET    /api/ping/                  → {"status": "ok", ...}
    POST   /api/chat/                  → send a message, get the AI reply
    GET    /api/conversations/         → list conversations (sidebar)
    GET    /api/conversations/<id>/    → one conversation + its messages
    DELETE /api/conversations/<id>/    → delete a conversation
    GET    /api/memories/              → list stored facts about the user
    DELETE /api/memories/<id>/         → forget one fact

Every view follows the same shape: request in → work → JsonResponse out.
Chat flow: load (or create) the conversation, rebuild its messages into
the list-of-dicts shape the AI APIs expect, prepend a system prompt that
carries the stored Memory facts, call ai.ask_ai, save both new messages,
then run fact extraction so KAI keeps learning about the user.
"""

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from . import ai
from .models import Conversation, Memory, Message

SYSTEM_PROMPT = (
    "You are KAI, a friendly personal AI assistant. Be helpful, clear, "
    "and concise. You remember facts about the user across conversations."
)


def ping(request):
    """GET /api/ping/ → a tiny JSON object saying the server is alive."""
    return JsonResponse({"status": "ok", "message": "pong from Django"})


def _system_prompt():
    facts = [m.fact for m in Memory.objects.all()]
    if not facts:
        return SYSTEM_PROMPT
    facts_text = "\n".join(f"- {fact}" for fact in facts)
    return f"{SYSTEM_PROMPT}\n\nFacts you know about the user:\n{facts_text}"


@csrf_exempt
def chat(request):
    """POST /api/chat/  {"message": str, "conversation_id"?: int,
    "model"?: str} → {"reply": str, "conversation_id": int}"""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    user_text = (body.get("message") or "").strip()
    if not user_text:
        return JsonResponse({"error": "message is required"}, status=400)

    conversation = None
    if body.get("conversation_id"):
        conversation = get_object_or_404(
            Conversation, pk=body["conversation_id"]
        )

    history = []
    if conversation is not None:
        history = [
            {"role": m.role, "content": m.content}
            for m in conversation.messages.all()
        ]
    messages = (
        [{"role": "system", "content": _system_prompt()}]
        + history
        + [{"role": "user", "content": user_text}]
    )

    reply = ai.ask_ai(messages, model=body.get("model") or None)
    if reply is None:
        return JsonResponse({"error": "AI unavailable"}, status=502)

    if conversation is None:
        conversation = Conversation.objects.create(
            title=user_text[:60] or "New conversation"
        )
    Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_text
    )
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=reply,
    )
    conversation.save(update_fields=["updated_at"])

    # Best-effort memory: pull durable facts from this exchange.
    known = {m.fact.lower() for m in Memory.objects.all()}
    for fact in ai.extract_facts(user_text, reply):
        if fact.lower() not in known:
            Memory.objects.create(fact=fact)
            known.add(fact.lower())

    return JsonResponse(
        {"reply": reply, "conversation_id": conversation.pk}
    )


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
        for c in Conversation.objects.all()
    ]
    return JsonResponse({"conversations": data})


def conversation_detail(request, pk):
    """GET /api/conversations/<id>/ → the conversation + all messages."""
    conversation = get_object_or_404(Conversation, pk=pk)
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
                    "created_at": m.created_at.isoformat(),
                }
                for m in conversation.messages.all()
            ],
        }
    )


@csrf_exempt
def conversation_delete(request, pk):
    """DELETE /api/conversations/<id>/ → 204, messages go with it."""
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    conversation = get_object_or_404(Conversation, pk=pk)
    conversation.delete()
    return JsonResponse({}, status=204)


def memory_list(request):
    """GET /api/memories/ → every fact KAI has stored about the user."""
    data = [
        {"id": m.pk, "fact": m.fact, "created_at": m.created_at.isoformat()}
        for m in Memory.objects.all()
    ]
    return JsonResponse({"memories": data})


@csrf_exempt
def memory_delete(request, pk):
    """DELETE /api/memories/<id>/ → 204; KAI forgets that one fact."""
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    memory = get_object_or_404(Memory, pk=pk)
    memory.delete()
    return JsonResponse({}, status=204)
