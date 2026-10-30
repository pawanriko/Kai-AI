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
│   └── tests.py              26 tests, AI + tools mocked (no network)
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
| GET | `/api/models/` | provider + model catalogue for the picker |
| POST | `/api/chat/` | `{message, conversation_id?, model?, agent?, coding?}` → `{reply, conversation_id, trace}` |
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

Tests: `python manage.py test` (26 tests, no network needed).

## Providers

`ai.py` holds a provider registry — a model is just a name, a provider
is the service hosting it (base URL + key + format). Almost all speak
the OpenAI chat-completions format, so one code path serves them all;
Gemini has its own adapter.

| Provider | Key in `.env` | Models offered |
|---|---|---|
| Groq | `GROQ_API_KEY` | Llama 3.3 70B, GPT OSS 120B/20B, Llama 4 Scout, Qwen3 32B, Llama 3.1 8B |
| OpenRouter | `OPENROUTER_API_KEY` | Nemotron 3 Super 120B (free), MiniMax M2.7 (free), DeepSeek V3.2 |
| NVIDIA NIM | `NVIDIA_API_KEY` | Nemotron Super 49B, DeepSeek V4 Flash |
| DeepSeek | `DEEPSEEK_API_KEY` | DeepSeek Chat, DeepSeek Reasoner |
| Google Gemini | `GEMINI_API_KEY` | Gemini 2.5 Flash |

The UI's model picker is fed by `GET /api/models/` and disables
providers whose key is missing. If the chosen provider fails or is
rate-limited, KAI falls back across the other configured providers;
set `AI_PROVIDER=<name>` in `.env` to pin one and disable fallback.

## Agent mode

Toggle **Agent** in the composer and KAI stops just chatting: the
model can call tools — `calculator` (exact maths, AST-sandboxed),
`current_datetime`, `weather` (Open-Meteo, no key needed) — observe
the results, and keep going for up to 6 steps before answering. Every
tool step is saved with the reply and shown under it ("Agent steps"),
so you can see exactly what it did.

## Coding mode

Toggle **Code** and KAI becomes a coding agent over a longer budget
(14 steps), working Claude-Code-style: explore → edit → run tests →
read failures → fix. Its coding tools — `list_files`, `read_file`,
`write_file`, `edit_file`, `search_code`, `run_command` — are confined
to a single sandbox folder (`agent_workspace/` in the project, or
`KAI_WORKSPACE` in `.env`): every path is checked against that root
and escapes are refused. `run_command` is allowlisted (python + safe
modules, node, npm test/run, git status/diff/log), shell-free, with a
30-second timeout. The agent can never touch the Django project itself
or anything else on the machine.

## Roadmap

Streaming replies (SSE) · voice input + image messages · per-step
approval prompts for file writes · Render deployment.

---

Built by **Pawan Kumar** — [GitHub](https://github.com/pawanriko) ·
[LinkedIn](https://www.linkedin.com/in/pawanriko)
