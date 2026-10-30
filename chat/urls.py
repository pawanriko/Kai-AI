"""URL map for the chat app.

The project-level map (config/urls.py) hands everything under /api/
to this file; each line here binds one address to one view function.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("models/", views.model_catalog, name="model-catalog"),
    path("chat/", views.chat, name="chat"),
    path("conversations/", views.conversation_list, name="conversation-list"),
    path(
        "conversations/<int:pk>/",
        views.conversation_detail,
        name="conversation-detail",
    ),
    path(
        "conversations/<int:pk>/delete/",
        views.conversation_delete,
        name="conversation-delete",
    ),
    path("memories/", views.memory_list, name="memory-list"),
    path(
        "memories/<int:pk>/delete/",
        views.memory_delete,
        name="memory-delete",
    ),
]
