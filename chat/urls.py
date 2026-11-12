"""URL map for the chat app.

The project-level map (config/urls.py) hands everything under /api/
to this file; each line here binds one address to one view function.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("auth/me/", views.me, name="auth-me"),
    path("auth/setup/", views.setup, name="auth-setup"),
    path("auth/login/", views.login_view, name="auth-login"),
    path("auth/logout/", views.logout_view, name="auth-logout"),
    path("models/", views.model_catalog, name="model-catalog"),
    path("usage/", views.usage_list, name="usage-list"),
    path("chat/", views.chat, name="chat"),
    path("chat/plan/", views.chat_plan, name="chat-plan"),
    path("chat/stream/", views.chat_stream, name="chat-stream"),
    path("conversations/", views.conversation_list, name="conversation-list"),
    path(
        "conversations/<int:pk>/",
        views.conversation_detail,
        name="conversation-detail",
    ),
    path(
        "conversations/<int:pk>/report/",
        views.conversation_report,
        name="conversation-report",
    ),
    path(
        "conversations/<int:pk>/delete/",
        views.conversation_delete,
        name="conversation-delete",
    ),
    path("memories/", views.memory_list, name="memory-list"),
    path("memories/add/", views.memory_add, name="memory-add"),
    path(
        "memories/duplicates/",
        views.memory_duplicates,
        name="memory-duplicates",
    ),
    path("memories/merge/", views.memory_merge, name="memory-merge"),
    path("memories/export/", views.memory_export, name="memory-export"),
    path(
        "memories/<int:pk>/confirm/",
        views.memory_confirm,
        name="memory-confirm",
    ),
    path(
        "memories/<int:pk>/scope/",
        views.memory_scope,
        name="memory-scope",
    ),
    path(
        "memories/<int:pk>/reject/",
        views.memory_reject,
        name="memory-reject",
    ),
    path(
        "memories/<int:pk>/delete/",
        views.memory_delete,
        name="memory-delete",
    ),
    path(
        "automation/propose/",
        views.automation_propose,
        name="automation-propose",
    ),
    path(
        "automation/actions/",
        views.automation_list,
        name="automation-list",
    ),
    path(
        "automation/actions/<int:pk>/approve/",
        views.automation_approve,
        name="automation-approve",
    ),
    path(
        "automation/actions/<int:pk>/deny/",
        views.automation_deny,
        name="automation-deny",
    ),
    path(
        "automation/actions/<int:pk>/execute/",
        views.automation_execute,
        name="automation-execute",
    ),
    path("automation/audit/", views.automation_audit, name="automation-audit"),
]
