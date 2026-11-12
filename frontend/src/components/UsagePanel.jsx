import { useEffect, useState } from 'react'

import { listUsage } from '../api'

// The Usage view (Phase 3): the cost ledger, read-only. Totals count
// only what providers actually reported — streamed calls carry no
// token counts, and models with no verified price carry no cost, so
// both are shown as unknown rather than silently zero. Cost is $0.00
// only for rows the server proved free.
function formatCost(cost) {
  if (cost === null || cost === undefined) return 'unknown'
  return `$${cost.toFixed(4)}`
}

function formatTokens(tokens) {
  return tokens === null || tokens === undefined ? '—' : tokens.toLocaleString()
}

export default function UsagePanel() {
  const [usage, setUsage] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    listUsage()
      .then(setUsage)
      .catch(() => setError('Could not load usage — is Django running?'))
  }, [])

  if (error) {
    return (
      <div className="memory-panel">
        <h2>Usage</h2>
        <p className="error-box">{error}</p>
      </div>
    )
  }
  if (!usage) {
    return (
      <div className="memory-panel">
        <h2>Usage</h2>
        <p className="muted">Loading…</p>
      </div>
    )
  }

  const { totals, recent } = usage
  return (
    <div className="memory-panel">
      <h2>Usage</h2>
      <p className="muted">
        {totals.calls} calls · {formatTokens(totals.prompt_tokens)} prompt
        tokens · {formatTokens(totals.completion_tokens)} completion
        tokens · estimated cost{' '}
        {totals.estimated_cost_usd === null
          ? 'unknown'
          : formatCost(totals.estimated_cost_usd)}
        {totals.unknown_cost_calls > 0 &&
          ` (${totals.unknown_cost_calls} calls with unknown cost)`}
        {totals.unknown_token_calls > 0 &&
          ` · ${totals.unknown_token_calls} calls without token counts`}
      </p>

      <h3>Recent calls</h3>
      {recent.length === 0 && (
        <p className="muted">
          Nothing yet. Send a chat and its provider call lands here.
        </p>
      )}
      <ul className="memory-list">
        {recent.map((row) => (
          <li key={row.id} className="memory-item">
            <span>
              {row.provider}::{row.model}
              {row.task ? ` · ${row.task}` : ''} · {row.kind}
            </span>
            <span>
              {formatTokens(row.prompt_tokens)} +{' '}
              {formatTokens(row.completion_tokens)} tokens ·{' '}
              {formatCost(row.estimated_cost_usd)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
