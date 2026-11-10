# KAI — Upgrade Roadmap (2026-11-10)

Guiding rules (from the project's own history): one commit at a
time, every change tested, nothing ships without the owner's
approval, free tiers first, and no feature outruns a reliable
chat path. Complexity is sized for one developer + AI pair
working in evening sessions.

## Recommended order (differs from phase numbering — security is
## genuinely first because KAI is already public on the internet)

### Step 1 — Phase 1: Security & stability · Medium
**Status (2026-11-10): DONE and pushed** (Units 1–4: `673e7071`,
`806a2426`, `ed13e5ea`, `803661d2`) — including the bootstrap-token
hardening added on review. Production deployment is the only step
left (owner sets `KAI_PRODUCTION` + `KAI_SETUP_TOKEN` in the Render
dashboard, then Manual Deploy). The list below is the original plan
this was executed against.
The public deployment makes this urgent, and it is mostly small,
well-understood work:
1. Single-user login (Django sessions) + `user` FKs on
   Conversation/Memory with a data migration. *(S1)*
2. Restore CSRF (token from cookie in `api.js`, drop
   `@csrf_exempt`). *(S3 — must land with #1)*
3. Coding-mode hardening: server-side enable flag, remove `pip`
   from allowed modules, scrub provider keys from the command
   environment, approval prompt before `run_command`. *(S2)*
4. Rate limit + input caps on `/api/chat/`. *(S4)*
5. Settings hardening: SECRET_KEY fail-fast, ALLOWED_HOSTS,
   secure cookies/HSTS, admin tucked away. *(S6–S9)*
6. Memory confirmation gate (facts land as "suggested" until
   approved in the panel). *(S5)*
7. Ship the queued Django 5.2.19 pin; fix `DEFAULT_PROVIDER`.

### Step 2 — Streaming responses · Small–Medium
SSE from `/api/chat/`: tokens appear as they generate instead of
one JSON after up to ~40 s. Biggest felt-quality win per hour of
work; also gives the agent loop a natural channel to stream trace
steps live (feeds Phase 8's activity timeline).

### Step 3 — Phase 2: AI brain · Medium
1. Gemini native tool calling in the agent loop (removes the
   silent dependency on a second provider for agent mode).
2. Task-based router: classify (chat / reasoning / coding /
   research) → pick model by a small policy table; **hard rule:
   never fall back *up* into a paid model silently** — free-to-free
   automatic, paid only when the user picked it.
3. Token + estimated-cost ledger (one `Usage` row per call) →
   powers the usage dashboard and free-tier guardrails.
4. Catalogue self-check: a management command (later a cron) that
   validates model ids against each provider's live list — the
   2026-11-10 dead-free-model incident becomes a warning, not an
   outage.

### Step 4 — Phase 5: Memory upgrade · Small–Medium
Search + export (JSON/Markdown), near-duplicate merging,
project-scoped memories, confirmed/inferred states (UI from
Step 1 #6). Mostly building on existing models.

### Step 5 — Phase 6: Web research · Medium
Add `web_search` + `fetch_page` tools (free tiers: Tavily free
quota or DuckDuckGo HTML; Open-Meteo pattern — no key where
possible), source-preserving research flow on top of the existing
agent loop, Markdown report export. Citations or it didn't happen:
the trace already stores tool results; reports render them as
sources.

### Step 6 — Phase 3: Agent system upgrade · Medium–Large
Plan-then-execute mode (the model emits a plan the UI shows
*before* tools run), completion verification step, named tool
bundles (research/coding/productivity) over one orchestrator —
not separate agent codebases. Per-step approvals from Step 1
become the permission spine.

### Step 7 — Phase 4: Voice · Medium (staged)
Stage A (cheap, surprisingly good): browser Web Speech API —
Chrome does Hindi + English STT free, on-device-ish, zero server
load on the Dell i5; TTS via speechSynthesis. Push-to-talk first,
no mandatory listening.
Stage B (only if A disappoints): Faster-Whisper (tiny/base, CPU)
+ Piper locally on the laptop; wake word last, if ever.

### Step 8 — Phase 7: Automation & computer control · Large
Deliberately last and gated: it inherits every permission built
above. Playwright browser agent with per-action approvals;
n8n (self-hosted, free) for scheduled workflows; computer control
connects to the already-installed Open Interpreter setup rather
than rebuilding it. Nothing here ships without the audit log
(S12) and approvals being boring-reliable.

### Phase 8: UI evolution · Medium, continuous
Dashboard shell around the existing chat (don't redesign the
chat itself): usage panel (Step 3 data), agent timeline (Step 2
stream), memory manager (Step 4), permissions/settings (Step 1).
Each lands with its backend step, not as one big rewrite.

## What NOT to do

- No rewrite. The provider registry, agent loop, and sandbox are
  sound bones; every phase above extends them.
- No local frontier models (hardware can't; cloud free tiers can).
- No multi-user/public-product features until Step 1 is done —
  and arguably not even then; this is a *personal* OS.
