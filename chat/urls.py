"""URL map for KAI API endpoints."""

from django.urls import path

from . import views

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("csrf/", views.csrf_token, name="csrf-token"),
    path("auth/me/", views.auth_me, name="auth-me"),
    path("auth/register/", views.auth_register, name="auth-register"),
    path("auth/login/", views.auth_login, name="auth-login"),
    path("auth/logout/", views.auth_logout, name="auth-logout"),
    path("chat/", views.chat, name="chat"),
    path("conversations/", views.conversation_list, name="conversation-list"),
    path("conversations/<int:pk>/", views.conversation_detail, name="conversation-detail"),
    path("conversations/<int:pk>/delete/", views.conversation_delete, name="conversation-delete"),
    path("memories/", views.memory_list, name="memory-list"),
    path("memories/<int:pk>/delete/", views.memory_delete, name="memory-delete"),
]
