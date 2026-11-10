# KAI — Security Audit (2026-11-10)

Method: full read of `chat/views.py`, `chat/models.py`,
`chat/agent.py`, `chat/tools.py`, `chat/coding_tools.py`,
`chat/ai.py`, `config/settings.py`, `config/urls.py`; greps for
auth/CORS/rate-limit code (none exist); repo checked for committed
secrets (none — `.env` absent, `.gitignore` covers it). The deployed
app is **public on the internet** (Render), which is what turns
several design shortcuts into real findings.

## Critical

### S1 — No authentication or authorization anywhere
- **Files:** `chat/views.py` (every view), `chat/models.py` (no user
  field on `Conversation`/`Memory`).
- **Evidence:** no `login_required`, no session/user checks; grep for
  `authenticate` returns nothing. Endpoints verified live from an
  unauthenticated client during the 2026-11-10 deployment work.
- **Impact:** anyone who finds the URL can read and delete **all**
  conversations and memories, and spend the owner's API quota.
  "Cross-user leakage" is total because there is exactly one shared
  data space.
- **Fix:** single-user auth first (Django session login or a shared
  secret token), then `user` FKs on both models so multi-user is a
  migration, not a rewrite. Gate **every** view, including `ping`
  variants that leak state (models/ leaks which keys exist — minor,
  but fold it in).

### S2 — Coding mode is unauthenticated remote code execution
- **Files:** `chat/coding_tools.py` (`run_command`, `_ALLOWED`,
  `_ALLOWED_PY_MODULES`), `chat/views.py` (mode is a client-sent
  boolean: `body.get("coding")`).
- **Evidence:** the file tools are properly confined (`_safe_path`
  resolves + containment-checks; tests prove `../` escapes fail).
  But `run_command` allows `python <script>` and `node <script>`,
  and the model can `write_file` that script first. Executed code
  runs with the **server process's** privileges — full filesystem,
  environment (all API keys), and network. `python -m pip` is also
  allowlisted (package install = arbitrary code + egress), and
  `npm run` executes whatever `package.json` in the workspace says.
- **Impact:** combined with S1, any visitor can ask the model (or
  prompt-inject it) into running arbitrary code on the server. The
  sandbox confines the *file tools*, not the *interpreter*.
- **Fix (layered):** (a) require auth + an explicit server-side
  switch for coding mode, not a client boolean alone; (b) drop
  `pip` from allowed modules; (c) per-step approval for
  `run_command` (the UI already renders a trace — approvals are the
  known missing piece); (d) longer term, run commands in a
  restricted subprocess environment (scrubbed env without keys,
  network off) or accept the risk **only** on a private, local
  deployment. Also fix `.env.example`, which overclaims: "The agent
  can NEVER touch anything outside this folder" — untrue for
  executed code (S11).

## High

### S3 — CSRF protection disabled on all state-changing endpoints
- **Files:** `chat/views.py` — `@csrf_exempt` on `chat`,
  `conversation_delete`, `memory_delete`; `frontend/src/api.js`
  sends no CSRF token.
- **Impact:** low *today* only because there is no auth cookie to
  ride on. The moment S1 adds session auth, this becomes a live
  CSRF hole. Fix together with S1: restore CSRF (send the token
  from the cookie in `api.js`) and remove the exemptions.

### S4 — No rate limiting, no input limits → quota burn / cost DoS
- **Files:** `chat/views.py` (message length unbounded, history
  resent in full), `chat/agent.py` (up to 14 model calls per
  request).
- **Impact:** with paid keys configured, a script can burn the
  owner's balance; even free tiers die under trivial load. One
  request can also carry an unbounded message and force a huge
  provider payload every turn (whole history, every time).
- **Fix:** per-IP throttle on `/api/chat/` (e.g. django-ratelimit or
  a cache counter), max message length, max history messages sent
  upstream, and a step budget already exists — keep it.

## Medium

### S5 — Persistent prompt injection through Memory
- **Files:** `chat/ai.py::extract_facts`, `chat/views.py::_system_prompt`.
- **Evidence:** facts are AI-inferred, stored unverified, and **all**
  facts are injected into every future system prompt. A crafted
  message ("my name is X, and KAI must always …") can plant an
  instruction that outlives the conversation. Facts also have no
  confirmed/inferred distinction (Phase-5 requirement).
- **Fix:** mark facts `source=inferred`, show them for one-tap
  confirmation in the Memory panel, cap fact length/count, and keep
  instruction-like text out (simple filter + the confirmation gate
  is the real control).

### S6 — Hardcoded SECRET_KEY fallback in a public repo
- **File:** `config/settings.py`. Production is safe today (Render
  `generateValue: true` — verified in `render.yaml`), but any deploy
  that forgets the env var silently runs on a published key.
- **Fix:** fail fast when `DEBUG` is off and `SECRET_KEY` is unset.

### S7 — ALLOWED_HOSTS defaults to `*`, including production
- **File:** `config/settings.py` (`os.environ.get('ALLOWED_HOSTS', '*')`);
  `render.yaml` does not set it. Low blast radius while there are
  no password-reset flows, but it is free to fix: default to the
  Render host + localhost, or set it in `render.yaml`.

### S8 — No transport-security settings
- **File:** `config/settings.py` — no `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, or SSL redirect
  behind Render's TLS termination. Set them when S1/S3 land
  (cookies become worth protecting then).

## Low / informational

- **S9 — Django admin exposed** at `/admin/` with no users
  configured. Harmless today; remove or protect when auth lands.
- **S10 — DEBUG defaults ON for local dev** (`settings.py`). Fine
  at home; the fail-fast in S6 should also cover `DEBUG` being on
  with a production `DATABASE_URL`.
- **S11 — Documentation overclaim** in `.env.example` (see S2).
- **S12 — Audit trail is partial.** Tool steps are saved as a
  `trace` on the assistant message (with timestamps via the
  message row) — good — but results are truncated to 600 chars,
  there is no append-only log, and no actor attribution (no users,
  S1). A dedicated `ToolExecution` log is a Phase-1/3 item.

## Verified strengths (keep)

- Calculator is an AST-whitelist evaluator — no `eval`; a test
  proves code strings are rejected (`chat/tools.py`, `tests.py`).
- File-tool sandbox: `resolve()` + containment, symlink escapes
  resolve outside and are refused; escape tests exist and pass.
- Shell tool: `shlex` split, `shell=False`, allowlist prefixes,
  30 s timeout, output truncated, cwd pinned to the workspace.
- Weather tool: free Open-Meteo, params `urlencode`d, 15 s timeout.
- Provider calls: 25 s timeouts, failures logged **without** key
  material; keys never reach the browser (`api.js` comment + code).
- No CORS headers are emitted anywhere — same-origin by design
  (the "open CORS" item in an old platform scan was the retired
  host's edge, not this code).
- Secrets hygiene: `.env` gitignored and verified absent from the
  GitHub repo; Render/Neon values were only ever pasted into
  dashboards, never into chat or git.

---

## Phase 1 resolution status (2026-11-10; pushed to GitHub in four approved units — 673e7071, 806a2426, ed13e5ea, 803661d2 — production deployment still pending the owner's manual dashboard setup + deploy)

- **S1 FIXED** — Django session auth on every data endpoint (401
  JSON for anonymous), owner FK on Conversation/Memory with a
  NULL-legacy strategy (rows preserved, claimed on first use),
  one-time `/api/auth/setup/` owner creation (closes once a user
  exists) + `createsuperuser` locally. Tests: AuthTests,
  IsolationTests.
- **S2 CONTAINED** — production execution OFF via server-side
  `KAI_CODING_ENABLED` (never set on Render; backend rejects coding
  requests with 403, agent + run_command double-gated), login +
  explicit session confirmation required where enabled, `pip`
  removed from the allowlist, command environment scrubbed of
  secrets (test proves keys are invisible), write-size cap.
  **Still true:** where the switch IS on, executed code has the
  server process's privileges and network access — a restricted
  subprocess, not a sandbox. Per-step approval remains future work.
- **S3 FIXED** — all `@csrf_exempt` removed; SPA sends the cookie
  token (read fresh per request; Django rotates it at login —
  covered by a test that caught exactly that). CsrfTests use an
  enforcing client.
- **S4 FIXED (basic)** — per-IP fixed-window limits (chat 30/min,
  login 10/5min, setup 5/5min), 8,000-char message cap, 40-message
  history cap. Locmem cache = per-process; fine on the single free
  instance, but NOT suitable for multi-worker scaling — counters
  would diverge per worker; multiple workers require a shared cache
  backend such as Redis, which is not configured today.
- **S5 FIXED** — facts land as SUGGESTED; only CONFIRMED facts
  enter the system prompt; confirm/reject in the panel; 300-char
  and 250-count caps; an instruction-pattern filter drops obvious
  prompt-injection facts (the confirmation gate is the real fix).
- **S6 FIXED** — with `KAI_PRODUCTION=1` the app refuses to boot
  without an env SECRET_KEY (verified). Dev fallback remains for
  local only.
- **S7 FIXED** — production ALLOWED_HOSTS derived from APP_URL.
- **S8 FIXED** — secure session/CSRF cookies, HSTS (1y), SSL
  redirect behind Render's proxy header, all gated on
  `KAI_PRODUCTION=1` (verified in a production-mode smoke test).
- **S9 NOTED** — admin stays, now genuinely behind staff login.
- **S11 FIXED** — `.env.example` + README now describe the
  execution model accurately.
- **S12 OPEN** — dedicated append-only tool-execution log is
  still future work (trace-on-message remains the record).


## Addendum — bootstrap hardening (2026-11-10, post-Phase-1 review)

The Phase 1 setup endpoint was itself a finding: public until the
first user exists = an account-takeover race on a public deploy.
Fixed before any push:

- **Bootstrap token:** setup now requires `KAI_SETUP_TOKEN`, a
  secret that exists only in the server's environment, compared
  with `hmac.compare_digest`. Not configured → web setup is
  DISABLED entirely (createsuperuser remains the local path).
- **Atomicity:** owner creation is one transaction whose first
  statement UPDATEs the singleton `SetupGuard` row (migration
  0004), taking the write lock before the "no users yet" check —
  serialized on Postgres and file SQLite; bounded lock-retry keeps
  SQLite shared-cache (test runner) contention from surfacing as
  500s. Password hashing happens BEFORE the transaction so the
  lock is never held across PBKDF2.
- **Permanent close:** with any user present, setup returns 403
  even with the valid token. Restoring or re-setting the token
  after bootstrap therefore cannot create another owner — the
  user-exists check runs regardless of the token — and removing
  the token simply leaves web setup disabled. Setup is also
  rate-limited (5/5 min) and CSRF-protected like every other POST.
- **Verified:** 4-thread concurrency test (TransactionTestCase,
  real connections) — exactly one owner, one 200, three 403s —
  plus a real-HTTP smoke (no token → 403, wrong token → 403,
  correct → 200, repeat → 403), and a final pre-push pass on real
  PostgreSQL 16.2 (8-thread race → exactly one owner) with
  migration 0004 checked on fresh/existing/rollback paths. Full
  suites: backend 51/51, frontend 11/11.

Endpoint re-review (same pass): login is rate-limited with a
generic error and Django's timing equalization; logout is
POST-only + login-required; session/CSRF tokens rotate at login
and the SPA reads the cookie fresh per request; data endpoints
are login-gated with owner filters (legacy NULL-owner rows are
claimable only by an authenticated session — by design for the
single-owner instance); admin requires a staff login. No other
unauthenticated state-changing surface exists: the only public
endpoints are /api/ping/ and /api/auth/me/ (state booleans only).
