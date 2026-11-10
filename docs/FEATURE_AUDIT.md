# KAI — Feature Audit (2026-11-10)

Status key: ✅ implemented & verified · 🟡 partial · ❌ missing ·
⚠️ works but fragile. "Verified" means executed or observed live,
not read in a README.

> **Phase 1 update (2026-11-10):** this audit describes the
> pre-Phase-1 baseline (`fb372253`). Since then, authentication,
> memory confirmation, rate limiting and the coding kill switch
> moved from ❌/⚠️ to implemented (pushed in Units 1–4, up to
> `803661d2`; deployment pending). Rows below are the baseline
> record — for the current status see SECURITY_AUDIT.md's Phase 1
> resolution status and UPGRADE_ROADMAP.md.

## Implemented & verified ✅

| Capability | Evidence |
|---|---|
| Multi-provider chat — Groq, OpenRouter, NVIDIA NIM, DeepSeek (one OpenAI-format path) + Gemini (own adapter) | `chat/ai.py`; live replies on Render 2026-11-10 |
| Cross-provider fallback | Proven live: Gemini 503 → OpenRouter answered ("42", conversation saved to Neon) |
| Within-provider model fallback (pinned mode) | Production logs 2026-11-10 20:29 — 3.8-flash 503, 2 s later 2.5-flash tried |
| Provider failure logging | `[kai] … call failed: HTTPError …` in Render Logs |
| Model picker with per-provider `configured` flags | `GET /api/models/` verified live |
| Persistent conversations + messages (Postgres in prod) | Models + migrations 0001/0002; Neon verified live |
| Long-term memory: extract, dedupe, list, delete, inject into prompt | `views.py`, `MemoryPanel.jsx`; API tests pass |
| Agent mode: tool-calling loop, 6 steps, trace saved + shown | calculator (AST-safe), datetime, weather (Open-Meteo) |
| Coding mode: 14 steps, 6 workspace tools, allowlisted shell | Escape + allowlist tests pass |
| Automated tests | **26/26 executed for this audit** |
| Single-service deploy (Django serves the SPA) | Render live; Docker path retained |

## Partial 🟡

- **Tool calling** — OpenAI-format providers only. Gemini (the
  default engine) has *no* native tool calling in the agent loop;
  agent mode silently depends on a non-Gemini key being configured.
- **Model routing** — manual picker + failure fallback only. No
  task/complexity-based selection, no latency/cost awareness, no
  token or cost tracking. "Never silently switch to a paid model"
  is **not enforced**: today's fallback default happens to be a
  free model, but the picker lists paid models (up to Opus-class)
  with no cost warning in the UI.
- **Memory** — list/delete only. No search, no export, no project
  scoping, no confirmed-vs-inferred split (see SECURITY S5),
  dedupe is exact-match only (near-duplicates accumulate).
- **Error recovery** — provider failure → next provider/model;
  no retry/backoff for transient errors, no user-facing reason
  (uniform "AI unavailable"), agent loop has no replan step —
  it observes tool results but cannot change strategy formally.
- **UI** — chat + memory panel + trace display. No dashboard,
  no usage view, no settings screen, no permissions UI, no
  streaming (replies arrive as one JSON after the full provider
  chain finishes — a 38 s wait with no feedback on a bad day).
- **Audit log** — traces are saved per message but truncated and
  not queryable as a log (see SECURITY S12).

## Missing ❌ (against the OS vision)

- Authentication & per-user data isolation (SECURITY S1).
- Voice: no STT, no TTS, no wake word, no mic UI.
- Web research: **no search tool at all** — the agent cannot open
  or cite web sources; weather is the only live-data tool.
- Browser automation (Playwright), computer control, file
  management outside the coding sandbox.
- Productivity: no tasks, reminders, calendar, or scheduling.
- Workflow automation: no n8n/API integrations, no cron jobs.
- Document/report generation (PDF/Markdown exports).
- Streaming responses (SSE/WebSocket).
- Per-step approval prompts for agent/coding actions (designed
  as a toggle + trace only).
- Token/cost accounting per provider/model.

## Fragile ⚠️

- **Free-model catalogue churn:** two OpenRouter `:free` ids died
  silently and produced 404s until manually replaced (2026-11-10).
  Nothing validates catalogue ids against the provider's live list.
- **Gemini 3.8-flash 503 windows:** Google-side overload can take
  the primary engine out for an evening; fallback now covers it.
- **Groq key returns 403** (account-side, since 2026-10-31) — and
  `DEFAULT_PROVIDER` is still `"groq"`, so a bare model id routes
  to the one dead provider.
- **Blueprint "Failed sync":** the Render blueprint reports a
  failed sync while the service deploys fine manually; root cause
  not yet identified. Deploys are Manual-Deploy-only until fixed.
- **Free-tier sleep:** ~50 s cold start on Render free.

## Technical debt

- Local Django 5.2.19 vs repo/production 5.2.18 (unshipped pin).
- `_system_prompt()` loads **all** memories on every chat request;
  `conversation_list` does a per-row `messages.count()` (N+1).
  Both fine at personal scale, both will hurt later.
- No pagination on conversations/messages/memories.
- `requirements.txt` / `requirements-prod.txt` split is a
  Dockerfile-era artefact; Render installs both — harmless, but
  worth a comment or merge.
- Antideploy leftovers: `.antideploy.json`, `Dockerfile` comments
  reference the retired host (Docker path itself is still valid).
- Test coverage is backend-only; the frontend has no tests, and
  there is no CI.
