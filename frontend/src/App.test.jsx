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
  sendChat: vi.fn(),
  sendChatStream: vi.fn(),
}))

import {
  exportReport,
  getConversation,
  getMe,
  listConversations,
  listModels,
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
