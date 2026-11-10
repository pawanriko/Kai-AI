# KAI — Architecture (audited 2026-11-10)

Verified against the code at repo `pawanriko/Kai-AI` main `fb372253`
(local tree identical for all audited files). Test suite executed for
this audit: **26 tests, OK** (`python manage.py test`, SQLite mode).

> **Phase 1 update (2026-11-10):** this document describes the
> audited baseline above. Session authentication, per-user
> ownership, CSRF protection, rate limits, memory confirmation and
> the coding kill switch have since been implemented and pushed
> (Units 1–4, up to `803661d2`); production deployment is pending.
> Statements below about missing authentication describe the
> baseline, not the current code — see SECURITY_AUDIT.md's Phase 1
> resolution status and the README for the current state.

## Shape

One Django app (`chat`) + one React SPA. Django serves the built SPA
itself in production (WhiteNoise), so the whole product is a single
web service — no separate frontend deployment, no CORS surface.

```
Browser (React 19 + Vite 8 SPA)
   │  fetch /api/* (api.js, provider::model choices)
   ▼
Django 5.2 (config/) ── WhiteNoise serves frontend/dist at /
   │
   ├─ chat/views.py    HTTP endpoints (the whole API surface)
   ├─ chat/ai.py       ONLY module that talks to AI providers
   ├─ chat/agent.py    tool-calling loop (6 steps, coding 14)
   ├─ chat/tools.py    calculator / datetime / weather
   ├─ chat/coding_tools.py  sandboxed file + shell tools
   └─ chat/models.py   Conversation / Message / Memory
   │
   ├─ DB: SQLite local · Neon Postgres in production (DATABASE_URL)
   └─ Providers: Groq, OpenRouter, NVIDIA NIM, DeepSeek (OpenAI
      format, one code path) + Gemini (own adapter)
```

## API surface (chat/urls.py, all under /api/)

| Endpoint | Purpose |
|---|---|
| GET ping/ | health |
| GET models/ | provider catalogue + `configured` flags for the picker |
| POST chat/ | send message → reply; body flags: `agent`, `coding` |
| GET conversations/ · GET conversations/<id>/ · DELETE …/delete/ | history |
| GET memories/ · DELETE memories/<id>/delete/ | stored facts |

There is **no authentication on any endpoint** (see SECURITY_AUDIT).

## AI layer (chat/ai.py, 368 lines)

- Registry pattern: each provider = base URL + key env var + format +
  model list. Choices travel as `provider::model`.
- `ask_ai`: chosen provider first, then fallback across *configured*
  providers (`FALLBACK_ORDER = groq, openrouter, nvidia, deepseek,
  gemini`). `AI_PROVIDER` env pins one provider and switches the
  fallback to *within-provider model fallback* (added 2026-11-10
  after live 503s; proven in production logs).
- All provider calls go through `_post_json` (urllib, 25 s timeout,
  IPv4-forced opener — added 2026-11-10; container IPv6 routes
  blackholed and stalled calls to the full timeout). Failures are
  logged to stderr (`[kai] <provider> call failed: …`), never shown
  raw to the user (uniform "AI unavailable", HTTP 502).
- `extract_facts`: after each exchange, a model call distils durable
  user facts; stored in `Memory`, deduped case-insensitively, and
  injected into every system prompt (`views._system_prompt`).

## Agent layer (chat/agent.py, 111 lines)

Classic tool-calling loop: send schemas → execute `tool_calls` →
append results → repeat, capped (6 steps plain, 14 coding); final
round forces a no-tools answer. Every step is recorded in a `trace`
(saved on the assistant `Message`, rendered in the UI).
**Tool calling exists only for OpenAI-format providers** —
`agent_provider` routes around Gemini, whose function-calling format
the Gemini adapter does not implement.

## Coding tools (chat/coding_tools.py, 338 lines)

Six tools (`list_files`, `read_file`, `write_file`, `edit_file`,
`search_code`, `run_command`) confined to one workspace root
(`KAI_WORKSPACE` env or `<project>/agent_workspace/`). Paths are
`resolve()`d and containment-checked. `run_command` is an allowlist
(python/node/npm test|run/git status|diff|log), `shlex`-split,
`shell=False`, 30 s timeout, truncated output. See SECURITY_AUDIT
S2 for why the *executed code* is not confined even though the
*file tools* are.

## Frontend (918 lines total)

React 19.3 + Vite 8.3, plain hooks (no store, no router):
`App.jsx` (chat/memory views, model picker, AGENT/CODE toggles),
components `Sidebar`, `MessageList`, `ChatInput`, `MemoryPanel`;
all HTTP in `api.js`. Dev: Vite proxy → Django :8000.

## Deployment

- **Production: Render** free web service (`render.yaml` blueprint,
  blueprint id exs-dbpersmtlv9c73fcr18g), service `kai-ai`
  → https://kai-ai-02i0.onrender.com. Build: pip install (both
  requirements files) → npm ci + build → collectstatic → migrate.
  Start: gunicorn `--timeout 120`. DB: Neon Postgres (project "Kai").
  Deploys are Manual (blueprint shows "Failed sync"; service itself
  deploys fine). Free tier sleeps when idle (~50 s cold start).
- Docker path (`Dockerfile`, multi-stage) still exists from the
  retired Antideploy deployment (2026-11-01 → 2026-11-10).
- Secrets: env only (`.env` local, Render dashboard in prod).
  `.env` is gitignored and **verified absent from the repo**.

## Known drift

- Local `requirements.txt` pins Django **5.2.19**; the repo (and
  therefore production) still runs **5.2.18** — local-only change
  from 2026-11-04, never shipped.
