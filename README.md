# KAI v2 — my personal AI assistant (Django + React)

The first version of KAI was a single `index.html` file. The browser kept the Groq API key, talked to Groq directly, and the "memory" lived in localStorage — so it forgot everything the day I cleared my browser data. It worked, but it wasn't a real app.

So I rebuilt it properly. v2 is a full-stack app:

- A **Django backend** keeps the API keys on the server (in a `.env` file, never in git, never in the browser), talks to the AI providers, and stores everything in a database.
- A **React frontend** which is just the face — it sends JSON to Django and shows what comes back.
- **Memory that actually lasts**: conversations and messages are database rows. After every exchange, KAI pulls out facts about me (my college, my projects, things like that) and saves them in a `Memory` table. Those facts go into future prompts, and I can see and delete them from the UI.

**Live:** [kai-ai.antideploy.app](https://kai-ai.antideploy.app) — it runs, though the free host's network is slow, so a local run feels much better.

## How it fits together

```
Browser (React, :5173 dev) ──JSON──► Django API (:8000) ──HTTPS──► Groq / Gemini
                                          │
                                          ▼
                                   SQLite (dev) → Postgres
```

What happens when I send one message: React POSTs to `/api/chat/` → Django loads that conversation's history from the DB → puts together the message list the AI APIs expect → adds a system prompt carrying my stored facts → calls the provider → saves both messages → extracts any new facts → sends the reply back to React.

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

Open http://localhost:5173 — the Vite dev server proxies `/api` calls to Django on :8000.

Tests: `python manage.py test` (26 tests, no network needed).

## Providers

In `ai.py` there's a registry of providers. A model is just a name; a provider is the service hosting it (base URL + key + format). Almost all of them speak the OpenAI chat-completions format, so one code path covers them; Gemini has its own adapter because its API is shaped differently.

| Provider | Key in `.env` | Models offered |
|---|---|---|
| Groq | `GROQ_API_KEY` | Llama 3.3 70B, GPT OSS 120B/20B, Llama 4 Scout, Qwen3 32B, Llama 3.1 8B |
| OpenRouter | `OPENROUTER_API_KEY` | Nemotron 3 Super 120B (free), MiniMax M2.7 (free), DeepSeek V3.2 |
| NVIDIA NIM | `NVIDIA_API_KEY` | Nemotron Super 49B, DeepSeek V4 Flash |
| DeepSeek | `DEEPSEEK_API_KEY` | DeepSeek Chat, DeepSeek Reasoner |
| Google Gemini | `GEMINI_API_KEY` | Gemini 3.8 Flash, Gemini 2.5 Flash |

The model picker in the UI is fed by `GET /api/models/`, and providers whose key I haven't set are greyed out. If the provider I pick fails or hits a rate limit, KAI quietly tries the other configured ones. If I want only one provider, I set `AI_PROVIDER=<name>` in `.env` and the fallback stops.

## Agent mode

There's an **Agent** toggle in the message box. With it on, KAI doesn't just answer — the model can use tools: a `calculator` (exact maths, run through a sandboxed expression parser), `current_datetime`, and `weather` (Open-Meteo, needs no key). It can call a tool, look at the result, and call another, up to 6 steps, before it replies. Every step it took is saved with the reply and shown under it ("Agent steps"), so I can see exactly what it did instead of trusting it blindly.

## Coding mode

The **Code** toggle makes KAI a coding agent with a bigger budget (14 steps). It works the way coding agents do: look around → edit → run the tests → read the failure → fix it. Its tools (`list_files`, `read_file`, `write_file`, `edit_file`, `search_code`, `run_command`) only work inside one sandbox folder — `agent_workspace/` in the project, or whatever `KAI_WORKSPACE` points to in `.env`. Every file path is checked against that folder and anything trying to escape gets refused. `run_command` has an allowlist (python and its safe modules, node, npm test/run, git status/diff/log), runs without a shell, and times out after 30 seconds. It can't touch the Django project itself or anything else on the machine. That limit is deliberate — I wanted to see what an agent does when it can actually break things, without letting it break mine.

## What's next

Streaming replies (SSE) · voice input and image messages · asking my approval before the coding agent writes a file.

---

Built by **Pawan Kumar** — [GitHub](https://github.com/pawanriko) · [LinkedIn](https://www.linkedin.com/in/pawanriko)
