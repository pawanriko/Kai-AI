// @vitest-environment jsdom
//
// Phase 3: the Usage view renders ledger totals and recent calls.
// Unknowns stay unknown on screen: streamed calls show a dash for
// tokens, and models with no verified price show "unknown" cost —
// never a silent zero.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { listUsage } from '../api'
import UsagePanel from './UsagePanel'

vi.mock('../api', () => ({
  listUsage: vi.fn(),
}))

let container
let root

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.resetAllMocks()
})

async function renderPanel() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root.render(<UsagePanel />)
  })
}

const USAGE = {
  totals: {
    calls: 2,
    prompt_tokens: 17,
    completion_tokens: 8,
    estimated_cost_usd: 0,
    unknown_cost_calls: 1,
    unknown_token_calls: 1,
  },
  recent: [
    {
      id: 2,
      provider: 'gemini',
      model: 'gemini-3.8-flash',
      task: 'chat',
      kind: 'chat',
      prompt_tokens: 7,
      completion_tokens: 3,
      estimated_cost_usd: null,
      created_at: '2026-11-12T10:00:00Z',
    },
    {
      id: 1,
      provider: 'openrouter',
      model: 'google/gemma-4-31b-it:free',
      task: 'chat',
      kind: 'stream',
      prompt_tokens: null,
      completion_tokens: null,
      estimated_cost_usd: 0,
      created_at: '2026-11-12T09:00:00Z',
    },
  ],
}

describe('UsagePanel', () => {
  it('renders totals and recent calls, unknowns shown as unknown', async () => {
    listUsage.mockResolvedValue(USAGE)
    await renderPanel()
    expect(container.textContent).toContain('2 calls')
    expect(container.textContent).toContain('17 prompt tokens')
    expect(container.textContent).toContain('1 calls with unknown cost')
    expect(container.textContent).toContain('gemini::gemini-3.8-flash')
    expect(container.textContent).toContain('unknown')
    expect(container.textContent).toContain(
      'openrouter::google/gemma-4-31b-it:free'
    )
    expect(container.textContent).toContain('—')
    expect(container.textContent).toContain('$0.0000')
  })

  it('shows an error when the ledger cannot load', async () => {
    listUsage.mockRejectedValue(new Error('down'))
    await renderPanel()
    expect(container.textContent).toContain('Could not load usage')
  })

  it('explains the empty state', async () => {
    listUsage.mockResolvedValue({
      totals: {
        calls: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        estimated_cost_usd: null,
        unknown_cost_calls: 0,
        unknown_token_calls: 0,
      },
      recent: [],
    })
    await renderPanel()
    expect(container.textContent).toContain('Nothing yet')
  })
})
