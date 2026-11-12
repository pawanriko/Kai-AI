import { useEffect, useState } from 'react'

import {
  approveAction,
  denyAction,
  executeAction,
  listActions,
  listAudit,
  proposeAction,
} from '../api'

// The Automation view (Phase 8): propose an action, approve or deny
// it, then execute it — each step separate, each step audited.
// Default-deny: nothing runs without an approval record, and the
// server refuses to execute anything that was never approved, no
// matter what the UI sends. The payload is JSON by design: this is
// a power-user panel, and the schema differs per target.
const TARGET_ACTIONS = {
  browser: ['navigate', 'click', 'type', 'extract'],
  computer: ['run'],
  workflow: ['trigger'],
}

const PAYLOAD_HINTS = {
  browser: '{"url": "https://example.com", "selector": "#go", "text": ""}',
  computer: '{"command": "describe the files in the test folder"}',
  workflow: '{"webhook_url": "https://n8n.example/webhook/abc", "data": {}}',
}

export default function AutomationPanel() {
  const [actions, setActions] = useState([])
  const [entries, setEntries] = useState([])
  const [error, setError] = useState('')
  const [target, setTarget] = useState('browser')
  const [action, setAction] = useState('navigate')
  const [description, setDescription] = useState('')
  const [payloadText, setPayloadText] = useState(PAYLOAD_HINTS.browser)
  const [formError, setFormError] = useState('')

  async function load() {
    try {
      const [actionData, auditData] = await Promise.all([
        listActions(),
        listAudit(),
      ])
      setActions(actionData.actions)
      setEntries(auditData.entries)
    } catch {
      setError('Could not load automation — is Django running?')
    }
  }

  useEffect(() => {
    load()
  }, [])

  function changeTarget(next) {
    setTarget(next)
    setAction(TARGET_ACTIONS[next][0])
    setPayloadText(PAYLOAD_HINTS[next])
  }

  async function propose(event) {
    event.preventDefault()
    setFormError('')
    let payload
    try {
      payload = JSON.parse(payloadText)
    } catch {
      setFormError('Payload must be valid JSON.')
      return
    }
    try {
      await proposeAction(target, action, payload, description)
      setDescription('')
      await load()
    } catch (err) {
      setFormError(err.message)
    }
  }

  async function decide(id, fn) {
    await fn(id)
    await load()
  }

  const pending = actions.filter((a) => a.status === 'pending')
  const decided = actions.filter((a) => a.status !== 'pending')

  function actionRow(a) {
    return (
      <li key={a.id} className="memory-item">
        <span>
          {a.description}{' '}
          <span className="muted">
            ({a.target}/{a.action} · {a.status})
          </span>
          {a.result && (
            <span className="muted"> — {a.result.slice(0, 200)}</span>
          )}
        </span>
        <span>
          {a.status === 'pending' && (
            <>
              <button
                className="forget-btn"
                onClick={() => decide(a.id, approveAction)}
              >
                Approve
              </button>{' '}
              <button
                className="forget-btn"
                onClick={() => decide(a.id, denyAction)}
              >
                Deny
              </button>
            </>
          )}
          {a.status === 'approved' && (
            <button
              className="forget-btn"
              onClick={() => decide(a.id, executeAction)}
            >
              Execute
            </button>
          )}
        </span>
      </li>
    )
  }

  return (
    <div className="memory-panel">
      <h2>Automation</h2>
      <p className="muted">
        Every action needs your approval before it runs — proposing
        alone executes nothing. Browser actions need Playwright on
        the server, computer actions need the Open Interpreter
        bridge on your PC, and workflow actions need an n8n webhook
        URL. Until those are wired up, approved actions fail with a
        clear message instead of running.
      </p>
      {error && <p className="error-box">{error}</p>}

      <form onSubmit={propose}>
        <h3>Propose an action</h3>
        {formError && <p className="error-box">{formError}</p>}
        <select
          aria-label="Automation target"
          value={target}
          onChange={(e) => changeTarget(e.target.value)}
        >
          <option value="browser">Browser</option>
          <option value="computer">Computer (Open Interpreter)</option>
          <option value="workflow">Workflow (n8n)</option>
        </select>{' '}
        <select
          aria-label="Automation action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        >
          {TARGET_ACTIONS[target].map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>{' '}
        <input
          aria-label="Action description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What should this do?"
        />
        <div>
          <textarea
            aria-label="Action payload JSON"
            value={payloadText}
            onChange={(e) => setPayloadText(e.target.value)}
            rows={3}
            cols={60}
          />
        </div>
        <button type="submit">Propose</button>
      </form>

      <h3>Awaiting approval ({pending.length})</h3>
      {pending.length === 0 && (
        <p className="muted">Nothing waiting. Propose an action above.</p>
      )}
      <ul className="memory-list">{pending.map(actionRow)}</ul>

      <h3>Decided</h3>
      <ul className="memory-list">{decided.map(actionRow)}</ul>

      <h3>Audit log</h3>
      <ul className="memory-list">
        {entries.map((entry) => (
          <li key={entry.id} className="memory-item">
            <span>
              {entry.event} — {entry.description}{' '}
              <span className="muted">
                ({entry.target}/{entry.action_name})
              </span>
            </span>
            <span className="muted">
              {new Date(entry.created_at).toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
