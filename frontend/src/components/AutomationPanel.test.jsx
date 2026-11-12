// @vitest-environment jsdom
//
// Phase 8: the Automation panel proposes actions, approves/denies/
// executes them one step at a time, and shows the audit trail.
// Proposing must never execute: the panel only ever calls the
// propose endpoint from the form, and execute only from an
// approved action's own button.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  approveAction,
  denyAction,
  executeAction,
  listActions,
  listAudit,
  proposeAction,
} from '../api'
import AutomationPanel from './AutomationPanel'

vi.mock('../api', () => ({
  approveAction: vi.fn(),
  denyAction: vi.fn(),
  executeAction: vi.fn(),
  listActions: vi.fn(),
  listAudit: vi.fn(),
  proposeAction: vi.fn(),
}))

let container
let root

const ACTIONS = {
  actions: [
    {
      id: 1,
      target: 'browser',
      action: 'navigate',
      payload: { url: 'https://example.com' },
      description: 'Open example.com',
      status: 'pending',
      result: '',
      created_at: '2026-11-12T00:00:00Z',
      decided_at: null,
      executed_at: null,
    },
    {
      id: 2,
      target: 'workflow',
      action: 'trigger',
      payload: { webhook_url: 'https://n8n.example/webhook/abc' },
      description: 'Trigger nightly sync',
      status: 'approved',
      result: '',
      created_at: '2026-11-12T00:00:00Z',
      decided_at: '2026-11-12T00:01:00Z',
      executed_at: null,
    },
  ],
}

const AUDIT = {
  entries: [
    {
      id: 1,
      action_pk: 1,
      target: 'browser',
      action_name: 'navigate',
      description: 'Open example.com',
      event: 'proposed',
      detail: '',
      created_at: '2026-11-12T00:00:00Z',
    },
  ],
}

beforeEach(() => {
  listActions.mockResolvedValue(ACTIONS)
  listAudit.mockResolvedValue(AUDIT)
})

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
    root.render(<AutomationPanel />)
  })
}

function typeInto(input, value) {
  const proto =
    input.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
  act(() => {
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function buttonByText(text) {
  return [...container.querySelectorAll('button')].find(
    (b) => b.textContent === text
  )
}

describe('AutomationPanel', () => {
  it('renders pending actions, decided actions, and the audit trail', async () => {
    await renderPanel()
    expect(container.textContent).toContain('Open example.com')
    expect(container.textContent).toContain('Trigger nightly sync')
    expect(container.textContent).toContain('Awaiting approval (1)')
    expect(container.textContent).toContain('proposed')
    expect(buttonByText('Approve')).toBeTruthy()
    expect(buttonByText('Deny')).toBeTruthy()
    expect(buttonByText('Execute')).toBeTruthy()
  })

  it('proposes with the parsed payload and reloads', async () => {
    proposeAction.mockResolvedValue({})
    await renderPanel()
    typeInto(
      container.querySelector('input[aria-label="Action description"]'),
      'Open the docs'
    )
    typeInto(
      container.querySelector('textarea[aria-label="Action payload JSON"]'),
      '{"url": "https://docs.example.com"}'
    )
    await act(async () => {
      container
        .querySelector('form')
        .dispatchEvent(
          new Event('submit', { bubbles: true, cancelable: true })
        )
    })
    expect(proposeAction).toHaveBeenCalledWith(
      'browser',
      'navigate',
      { url: 'https://docs.example.com' },
      'Open the docs'
    )
    expect(executeAction).not.toHaveBeenCalled()
  })

  it('refuses invalid JSON without calling propose', async () => {
    await renderPanel()
    typeInto(
      container.querySelector('textarea[aria-label="Action payload JSON"]'),
      '{not json'
    )
    await act(async () => {
      container
        .querySelector('form')
        .dispatchEvent(
          new Event('submit', { bubbles: true, cancelable: true })
        )
    })
    expect(proposeAction).not.toHaveBeenCalled()
    expect(container.textContent).toContain('valid JSON')
  })

  it('approves, denies, and executes through the action buttons', async () => {
    approveAction.mockResolvedValue({})
    denyAction.mockResolvedValue({})
    executeAction.mockResolvedValue({})
    await renderPanel()
    await act(async () => {
      buttonByText('Approve').dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    expect(approveAction).toHaveBeenCalledWith(1)
    await act(async () => {
      buttonByText('Deny').dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    expect(denyAction).toHaveBeenCalledWith(1)
    await act(async () => {
      buttonByText('Execute').dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    expect(executeAction).toHaveBeenCalledWith(2)
  })

  it('switches the action list and payload hint per target', async () => {
    await renderPanel()
    const targetSelect = container.querySelector(
      'select[aria-label="Automation target"]'
    )
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        'value'
      ).set
      setter.call(targetSelect, 'computer')
      targetSelect.dispatchEvent(new Event('change', { bubbles: true }))
    })
    const actionOptions = [
      ...container
        .querySelector('select[aria-label="Automation action"]')
        .querySelectorAll('option'),
    ].map((o) => o.value)
    expect(actionOptions).toEqual(['run'])
    expect(
      container.querySelector('textarea[aria-label="Action payload JSON"]')
        .value
    ).toContain('command')
  })
})
