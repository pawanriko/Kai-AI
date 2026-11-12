# Automation (Phase 8) — approvals, audit, and the three runners

Every automation action in KAI goes through the same gate:

```
propose → PENDING → approve / deny → execute → EXECUTED / FAILED
```

- **Default-deny.** Nothing executes without an approval record.
  The server refuses to execute anything that is not `approved`,
  and one approval runs exactly once.
- **Audit log.** Every transition (proposed / approved / denied /
  executed / failed) is written to an append-only log that
  survives deletion of the action. There is no endpoint that
  edits or deletes audit entries.
- **Strict ownership.** Automation rows belong to one user, with
  no legacy visibility. Only the owner sees their actions/audit.

## The three runners

### Browser (Playwright) — NOT installed yet

Actions: `navigate`, `click`, `type`, `extract`. Each action is
self-contained: it carries its own `url` (plus `selector` /
`text`), opens a fresh headless Chromium, acts, and closes.

Playwright is deliberately not a dependency of this repo yet: it
needs browser binaries as well as the pip package. Until the host
has both, approved browser actions fail with a clear message
instead of running:

```
pip install playwright
playwright install chromium
```

URLs pass the public-URL guard (no localhost / private ranges /
cloud metadata). No live browser run has happened yet.

### Computer (Open Interpreter) — bridge NOT built yet

Open Interpreter 0.0.58 is already installed on Pawan's PC,
sandboxed to `E:\oi-test`. KAI does not rebuild it and cannot
reach the PC directly. The interface is a small bridge HTTP
endpoint that must run on the PC beside OI:

```
POST {KAI_OI_BRIDGE_URL}/run
{"command": "<instruction>", "cwd": "<folder>"?}
→ {"output": "<transcript>", "exit_code": 0}
```

Set `KAI_OI_BRIDGE_URL` in the server environment to enable it.
Until then, computer actions fail with "not configured". The
bridge itself, and any live OI verification, are deferred —
they need work on his PC, and OI's own approval gates must stay
intact on that side.

### Workflow (n8n) — config/interface only

n8n is self-hosted and free. KAI holds no n8n instance and no
workflow definitions. Triggering is a POST of JSON to a
workflow's Webhook URL, which the user pastes into the action
payload (`webhook_url`, plus optional `data`). No live n8n
verification has happened from here; wiring a real self-hosted
n8n is a setup step for Pawan.

## Status

Shipped: the approval/audit spine, all three runner interfaces,
the Automation panel, and full tests (including default-deny
proofs with mocked runners). Deferred, all needing Pawan's
environment: Playwright install + first live browser run, the OI
bridge on his PC + first live OI run, and a self-hosted n8n
instance + first live webhook trigger.
