# KAI v2 — Personal AI Assistant (Django + React)

KAI v1 was a single `index.html`: the browser held the Groq API key and
talked to Groq directly, and memory lived in `localStorage` — gone when
the browser data went. **v2 is a real full-stack app:**

- **Django backend** holds the API keys server-side (`.env`, never in
  git, never in the browser), calls Groq/Gemini, and stores everything
  in a database.
- **React frontend** is just the face: it talks to Django with JSON.
- **Real memory**: conversations and messages are database rows, and
  after every exchange KAI extracts durable facts about the user into a
  `Memory` table that feeds future system prompts — and can be viewed
  and deleted in the UI.

## Architecture

```
Browser (React, :5173 dev) ──JSON──► Django API (:8000) ──HTTPS──► Groq / Gemini
                                          │
                                          ▼
                                   SQLite (dev) → Postgres
```

One message's journey: React POSTs `/api/chat/` → Django loads the
conversation's history from the DB → rebuilds the list-of-dicts the AI
APIs expect → prepends a system prompt carrying the stored facts →
calls the provider → saves both messages → extracts new facts → JSON
reply back to React.

## Project map

```
kai-v2/
├── manage.py                 Django's command tool
├── requirements.txt          Django + python-dotenv (pinned)
├── .env.example              template for the secrets file (copy to .env)
├── config/                   project settings + master URL map
├── chat/                     the app that is KAI
│   ├── models.py             Conversation / Message / Memory tables
│   ├── ai.py                 the ONLY module that talks to Groq/Gemini
│   ├── views.py              the API endpoints
│   ├── urls.py               /api/ route table
│   └── tests.py              11 tests, AI mocked (no network)
└── frontend/                 Vite + React
    └── src/
        ├── api.js            every backend call in one place
        ├── App.jsx           state conductor
        └── components/       Sidebar, MessageList, ChatInput, MemoryPanel
```

## API

| Method | Path | What |
|---|---|---|
| GET | `/api/ping/` | health check |
| POST | `/api/chat/` | `{message, conversation_id?, model?}` → `{reply, conversation_id}` |
| GET | `/api/conversations/` | list conversations |
| GET | `/api/conversations/<id>/` | conversation + messages |
| DELETE | `/api/conversations/<id>/delete/` | delete conversation |
| GET | `/api/memories/` | list stored facts |
| DELETE | `/api/memories/<id>/delete/` | forget one fact |

## Run it locally

Backend (terminal 1):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env    # then put your GROQ_API_KEY in .env
python manage.py migrate
python manage.py runserver
```

Frontend (terminal 2):

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — the Vite dev server proxies `/api` calls
to Django on :8000.

Tests: `python manage.py test` (11 tests, no network needed).

## Providers

`ai.py` tries Groq first when `GROQ_API_KEY` is set, then Gemini when
`GEMINI_API_KEY` is set. Set `AI_PROVIDER=groq` or `AI_PROVIDER=gemini`
in `.env` to pin one provider. The model picker in the UI lists the six
Groq models from v1.

## Roadmap

Streaming replies (SSE) · voice input + image messages · tool calling
(calculator / weather / search) with a trace UI · Render deployment.

---

Built by **Pawan Kumar** — [GitHub](https://github.com/pawanriko) ·
[LinkedIn](https://www.linkedin.com/in/pawanriko)
