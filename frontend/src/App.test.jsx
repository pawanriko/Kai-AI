// @vitest-environment jsdom
//
// Phase 2.3 (F2): stream chunks arrive per token. App must not apply
// each one as its own setState — chunks accumulate and flush once
// per animation frame, so the bubble grows live but the transcript
// re-renders at most ~60 times a second. The stream mock holds the
// connection open so the test can observe the window between "chunks
// emitted" and "frame fired": three chunks must schedule exactly one
// frame and change nothing on screen until it fires.
//
// Also locks in the F3 rule end to end: the Thinking bubble shows
// while waiting for the first chunk and hides once the assistant
// bubble exists.

// React's act() needs this flag outside a test runner that sets it.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('./api', () => ({
  deleteConversation: vi.fn(),
  exportReport: vi.fn(),
  getConversation: vi.fn(),
  getMe: vi.fn(),
  listConversations: vi.fn(),
  listModels: vi.fn(),
  logout: vi.fn(),
  requestPlan: vi.fn(),
  sendChat: vi.fn(),
  sendChatStream: vi.fn(),
}))

import {
  exportReport,
  getConversation,
  getMe,
  listConversations,
  listModels,
  requestPlan,
  sendChat,
  sendChatStream,
} from './api'

const roots = []
let rafQueue
let origRaf
let origCancelRaf

afterEach(() => {
  act(() => {
    roots.splice(0).forEach((root) => root.unmount())
  })
  document.body.innerHTML = ''
  window.requestAnimationFrame = origRaf
  window.cancelAnimationFrame = origCancelRaf
  window.localStorage.clear()
  vi.clearAllMocks()
})

beforeEach(() => {
  // Hold frames: scheduled callbacks only run when the test fires
  // them, so the batching window is deterministic instead of racing
  // jsdom's ~16ms timer.
  rafQueue = []
  origRaf = window.requestAnimationFrame
  origCancelRaf = window.cancelAnimationFrame
  window.requestAnimationFrame = (cb) => {
    const id = rafQueue.length + 1
    rafQueue.push({ id, cb })
    return id
  }
  window.cancelAnimationFrame = (id) => {
    const i = rafQueue.findIndex((entry) => entry.id === id)
    if (i >= 0) rafQueue.splice(i, 1)
  }

  getMe.mockResolvedValue({
    authenticated: true,
    needs_setup: false,
    username: 'pawanriko',
  })
  listConversations.mockResolvedValue({ conversations: [] })
  listModels.mockResolvedValue({
    providers: [
      {
        provider: 'groq',
        label: 'Groq',
        configured: true,
        models: [{ id: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B' }],
      },
    ],
  })
})

async function renderApp() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => {
    root.render(<App />)
  })
  // Boot is a promise chain (getMe -> auth effect -> listModels /
  // listConversations); flush it before touching the composer.
  await act(async () => {})
  await act(async () => {})
  return container
}

function typeText(textarea, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value'
  ).set
  act(() => {
    setter.call(textarea, value)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('App stream batching (Phase 2.3 F2)', () => {
  it('coalesces rapid chunks into one frame and hides Thinking on first flush', async () => {
    let release
    const streamOpen = new Promise((resolve) => {
      release = resolve
    })
    sendChatStream.mockImplementation(async (_msg, _id, _model, onChunk) => {
      onChunk('Hello ')
      onChunk('world')
      onChunk('!')
      await streamOpen
      return { conversation_id: 7 }
    })

    const container = await renderApp()
    const textarea = container.querySelector('.composer-input')
    expect(textarea).not.toBeNull()
    typeText(textarea, 'hi')
    act(() => {
      container
        .querySelector('.send-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    // Let handleSend run up to the held-open stream.
    await act(async () => {})
    await act(async () => {})

    expect(sendChatStream).toHaveBeenCalledTimes(1)
    // Three chunks emitted, but nothing on screen yet: they are
    // sitting in the ref, waiting for their single frame.
    expect(rafQueue.length).toBe(1)
    expect(container.textContent).not.toContain('Hello')
    // Still waiting for the first chunk: Thinking shows.
    expect(container.textContent).toContain('Thinking')

    // Fire the one scheduled frame: all three chunks land at once.
    act(() => {
      rafQueue.splice(0).forEach(({ cb }) => cb())
    })
    expect(container.textContent).toContain('Hello world!')
    expect(container.textContent).not.toContain('Thinking')

    // Stream completes: the synchronous flush in handleSend must
    // not duplicate or drop anything.
    await act(async () => {
      release()
    })
    await act(async () => {})
    expect(container.textContent).toContain('Hello world!')
    expect(container.querySelector('.send-btn').disabled).toBe(false)
  })

  it('discards queued chunks when the stream fails unsaved — no resurrection', async () => {
    // Phase 2.3 review finding: a frame still pending when a
    // non-interrupted error lands must not flush after the catch
    // drops the bubble, or the transcript would show a reply the
    // server never saved.
    sendChatStream.mockImplementation(async (_msg, _id, _model, onChunk) => {
      onChunk('Hello ')
      onChunk('world')
      throw new Error('boom')
    })

    const container = await renderApp()
    typeText(container.querySelector('.composer-input'), 'hi')
    act(() => {
      container
        .querySelector('.send-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await act(async () => {})
    await act(async () => {})

    // The error path discarded the queued chunks and cancelled
    // the frame before the bubble was dropped.
    expect(rafQueue.length).toBe(0)
    expect(container.textContent).not.toContain('Hello')
    expect(container.textContent).toContain('boom')
    // Even if a frame somehow fired afterwards, nothing is left
    // in the ref to resurrect the bubble.
    act(() => {
      rafQueue.splice(0).forEach(({ cb }) => cb())
    })
    expect(container.textContent).not.toContain('Hello')
    expect(container.querySelector('.send-btn').disabled).toBe(false)
  })
})

describe('App research report button (Phase 5)', () => {
  it('offers a report download once a conversation is open', async () => {
    listConversations.mockResolvedValue({
      conversations: [
        {
          id: 7,
          title: 'Django research',
          created_at: '2026-11-12T00:00:00Z',
          updated_at: '2026-11-12T00:00:00Z',
          message_count: 2,
        },
      ],
    })
    getConversation.mockResolvedValue({
      id: 7,
      title: 'Django research',
      messages: [
        { id: 1, role: 'user', content: 'Is Django 5.2 out?', trace: [] },
        { id: 2, role: 'assistant', content: 'Yes.', trace: [] },
      ],
    })
    exportReport.mockResolvedValue(new Blob(['# report']))
    URL.createObjectURL = vi.fn(() => 'blob:fake')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(
      () => {}
    )

    const container = await renderApp()
    expect(container.textContent).not.toContain('Download research report')

    await act(async () => {
      const item = [...container.querySelectorAll('li')].find((li) =>
        li.textContent.includes('Django research')
      )
      item.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await act(async () => {})

    const button = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Download research report'
    )
    expect(button).toBeTruthy()
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(exportReport).toHaveBeenCalledWith(7)
    vi.restoreAllMocks()
  })
})

describe('App plan-then-execute flow (Phase 6)', () => {
  function clickButton(container, text) {
    const button = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === text
    )
    act(() => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    return button
  }

  // Icon-only toggles carry no text — find them by aria-label.
  function clickIconButton(container, label) {
    const button = container.querySelector(`[aria-label="${label}"]`)
    act(() => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    return button
  }

  async function enablePlanFirst(container) {
    clickIconButton(container, 'Agent mode')
    await act(async () => {})
    clickIconButton(container, 'Plan first')
    await act(async () => {})
  }

  async function sendMessage(container, text) {
    typeText(container.querySelector('.composer-input'), text)
    await act(async () => {
      container
        .querySelector('.send-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await act(async () => {})
    await act(async () => {})
  }

  it('shows the plan before anything runs, then executes on approval', async () => {
    requestPlan.mockResolvedValue({
      plan: { steps: ['Search the web', 'Read the docs'] },
      bundle: null,
      conversation_id: null,
    })
    sendChat.mockResolvedValue({
      reply: 'Done.',
      conversation_id: 9,
      trace: [],
    })
    const container = await renderApp()
    await enablePlanFirst(container)
    await sendMessage(container, 'Research Django 5.2')

    expect(requestPlan).toHaveBeenCalledWith(
      'Research Django 5.2',
      null,
      'groq::llama-3.3-70b-versatile',
      null
    )
    expect(sendChat).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Proposed plan')
    expect(container.textContent).toContain('Search the web')
    // The user's message is not shown until the plan is approved.
    expect(container.querySelector('.message-user')).toBeNull()

    await act(async () => {
      clickButton(container, 'Approve & run')
    })
    await act(async () => {})
    expect(sendChat).toHaveBeenCalledWith(
      'Research Django 5.2',
      null,
      'groq::llama-3.3-70b-versatile',
      true,
      false,
      false,
      { plan: ['Search the web', 'Read the docs'], plan_approved: true }
    )
    expect(container.textContent).not.toContain('Proposed plan')
  })

  it('cancelling a plan sends nothing', async () => {
    requestPlan.mockResolvedValue({
      plan: { steps: ['Search the web'] },
      bundle: null,
      conversation_id: null,
    })
    const container = await renderApp()
    await enablePlanFirst(container)
    await sendMessage(container, 'Research Django 5.2')

    await act(async () => {
      clickButton(container, 'Cancel')
    })
    expect(sendChat).not.toHaveBeenCalled()
    expect(requestPlan).toHaveBeenCalledTimes(1)
    expect(container.textContent).not.toContain('Proposed plan')
  })

  it('sends the bundle with agent runs even without planning', async () => {
    sendChat.mockResolvedValue({
      reply: 'Done.',
      conversation_id: 9,
      trace: [],
    })
    const container = await renderApp()
    clickIconButton(container, 'Agent mode')
    await act(async () => {})
    const picker = container.querySelector('.bundle-picker')
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        'value'
      ).set
      setter.call(picker, 'research')
      picker.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await sendMessage(container, 'Research Django 5.2')
    expect(requestPlan).not.toHaveBeenCalled()
    expect(sendChat).toHaveBeenCalledWith(
      'Research Django 5.2',
      null,
      'groq::llama-3.3-70b-versatile',
      true,
      false,
      false,
      { bundle: 'research' }
    )
  })
})

describe('App paced reveal (smooth output)', () => {
  function lastBubbleText(container) {
    const bubbles = container.querySelectorAll('.bubble-text')
    return bubbles[bubbles.length - 1]?.textContent || ''
  }

  it('reveals a burst gradually across frames instead of dumping it', async () => {
    let release
    const streamOpen = new Promise((resolve) => {
      release = resolve
    })
    const burst = 'word '.repeat(40) // 200 characters, one burst
    sendChatStream.mockImplementation(async (_msg, _id, _model, onChunk) => {
      onChunk(burst)
      await streamOpen
      return { conversation_id: 7 }
    })

    const container = await renderApp()
    typeText(container.querySelector('.composer-input'), 'hi')
    act(() => {
      container
        .querySelector('.send-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await act(async () => {})
    await act(async () => {})

    expect(rafQueue.length).toBe(1)
    // One frame: only the paced slice is visible (cap = 34 for a
    // 200-char backlog), not the whole burst.
    act(() => {
      rafQueue.splice(0).forEach(({ cb }) => cb())
    })
    expect(lastBubbleText(container).length).toBe(34)
    expect(lastBubbleText(container)).not.toBe(burst)

    // Drain the remaining frames: the full burst arrives.
    for (let i = 0; i < 20 && rafQueue.length > 0; i++) {
      act(() => {
        rafQueue.splice(0).forEach(({ cb }) => cb())
      })
    }
    expect(lastBubbleText(container)).toBe(burst)

    await act(async () => {
      release()
    })
    await act(async () => {})
    expect(lastBubbleText(container)).toBe(burst)
    expect(container.querySelector('.send-btn').disabled).toBe(false)
  })

  it('flushes the whole backlog instantly when the stream ends', async () => {
    // The synchronous flush in handleSend bypasses the pace cap:
    // a stream that ends mid-burst must not leave text waiting
    // for frames that may never fire (hidden tab).
    const burst = 'word '.repeat(40)
    sendChatStream.mockImplementation(async (_msg, _id, _model, onChunk) => {
      onChunk(burst)
      return { conversation_id: 7 }
    })

    const container = await renderApp()
    typeText(container.querySelector('.composer-input'), 'hi')
    act(() => {
      container
        .querySelector('.send-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await act(async () => {})
    await act(async () => {})

    // No frames fired, yet the full reply is on screen.
    expect(lastBubbleText(container)).toBe(burst)
    expect(rafQueue.length).toBe(0)
  })
})

describe('App sidebar collapse', () => {
  it('slides the sessions panel away and back, and remembers the choice', async () => {
    const container = await renderApp()
    const layout = () => container.querySelector('.layout')
    expect(layout().classList.contains('sidebar-collapsed')).toBe(false)
    expect(
      container.querySelector('[aria-label="Open sessions panel"]')
    ).toBeNull()

    act(() => {
      container
        .querySelector('[aria-label="Close sessions panel"]')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(layout().classList.contains('sidebar-collapsed')).toBe(true)
    expect(window.localStorage.getItem('kai-sidebar-open')).toBe('false')

    const expand = container.querySelector(
      '[aria-label="Open sessions panel"]'
    )
    expect(expand).toBeTruthy()
    act(() => {
      expand.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(layout().classList.contains('sidebar-collapsed')).toBe(false)
    expect(window.localStorage.getItem('kai-sidebar-open')).toBe('true')
  })

  it('starts collapsed when the stored choice says so', async () => {
    window.localStorage.setItem('kai-sidebar-open', 'false')
    const container = await renderApp()
    expect(
      container
        .querySelector('.layout')
        .classList.contains('sidebar-collapsed')
    ).toBe(true)
  })
})
