// @vitest-environment jsdom
//
// Phase 2.3: scroll and Thinking-bubble behaviour, tested in the
// DOM (renderToString cannot observe effects or scrolling).
//
// F1: the transcript scrolls instantly and only while the user is
// already near the bottom — no smooth-scroll animation restarting
// on every chunk, and no yanking a reader who scrolled up.
// F3: the Thinking bubble shows only while sending AND no assistant
// bubble exists yet. That rule lives in App.jsx, which gates the
// `sending` prop it passes here (sending && last message is not an
// assistant bubble) — the first chunk creates the assistant bubble,
// which hides it. MessageList itself renders Thinking whenever its
// `sending` prop is true; the end-to-end rule is covered by
// App.test.jsx, which asserts Thinking shows before the first flush
// and is gone after it. What this level locks in: Thinking appears
// while sending with no assistant bubble yet.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MessageList from './components/MessageList'

const roots = []
let origScrollIntoView

afterEach(() => {
  act(() => {
    roots.splice(0).forEach((root) => root.unmount())
  })
  document.body.innerHTML = ''
  if (origScrollIntoView !== undefined) {
    Element.prototype.scrollIntoView = origScrollIntoView
    origScrollIntoView = undefined
  }
  vi.restoreAllMocks()
})

function renderList(messages, sending) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  const render = (msgs, snd) => {
    act(() => {
      root.render(<MessageList messages={msgs} sending={snd} />)
    })
  }
  render(messages, sending)
  return { container, render }
}

// jsdom has no layout: scrollHeight/clientHeight read 0. Define
// them on the element so the near-bottom math has real numbers.
function setMetrics(el, { scrollHeight, clientHeight, scrollTop }) {
  Object.defineProperty(el, 'scrollHeight', {
    value: scrollHeight,
    configurable: true,
  })
  Object.defineProperty(el, 'clientHeight', {
    value: clientHeight,
    configurable: true,
  })
  el.scrollTop = scrollTop
}

describe('MessageList scroll (Phase 2.3 F1)', () => {
  it('scrolls instantly to the bottom when near it', () => {
    const { container, render } = renderList(
      [{ id: 1, role: 'user', content: 'hi' }],
      false
    )
    const el = container.querySelector('.messages')
    setMetrics(el, { scrollHeight: 1000, clientHeight: 500, scrollTop: 500 })
    // New chunk arrives: content grows, still near the bottom.
    // The assignment lands on the maximum scroll position
    // (scrollHeight - clientHeight), not on scrollHeight itself.
    setMetrics(el, { scrollHeight: 1200, clientHeight: 500, scrollTop: 500 })
    render(
      [
        { id: 1, role: 'user', content: 'hi' },
        { id: 2, role: 'assistant', content: 'hello' },
      ],
      false
    )
    expect(el.scrollTop).toBe(700)
  })

  it('does not scroll when the content fits the container', () => {
    const { container, render } = renderList(
      [{ id: 1, role: 'user', content: 'hi' }],
      false
    )
    const el = container.querySelector('.messages')
    // Short content: scrollHeight < clientHeight, so the maximum
    // scroll position is 0 — never a negative assignment.
    setMetrics(el, { scrollHeight: 300, clientHeight: 500, scrollTop: 0 })
    render(
      [
        { id: 1, role: 'user', content: 'hi' },
        { id: 2, role: 'assistant', content: 'hello' },
      ],
      false
    )
    expect(el.scrollTop).toBe(0)
  })

  it('never moves the viewport once the user scrolled up', () => {
    const { container, render } = renderList(
      [{ id: 1, role: 'user', content: 'hi' }],
      false
    )
    const el = container.querySelector('.messages')
    setMetrics(el, { scrollHeight: 1000, clientHeight: 500, scrollTop: 100 })
    act(() => {
      el.dispatchEvent(new Event('scroll'))
    })
    setMetrics(el, { scrollHeight: 1200, clientHeight: 500, scrollTop: 100 })
    render(
      [
        { id: 1, role: 'user', content: 'hi' },
        { id: 2, role: 'assistant', content: 'hello' },
      ],
      false
    )
    expect(el.scrollTop).toBe(100)
  })

  it('resumes auto-scroll once the user returns to the bottom', () => {
    const { container, render } = renderList(
      [{ id: 1, role: 'user', content: 'hi' }],
      false
    )
    const el = container.querySelector('.messages')
    const two = [
      { id: 1, role: 'user', content: 'hi' },
      { id: 2, role: 'assistant', content: 'hello' },
    ]
    const three = [
      ...two,
      { id: 3, role: 'assistant', content: 'hello again' },
    ]
    // User scrolls up: the next chunk must not move the viewport.
    setMetrics(el, { scrollHeight: 1000, clientHeight: 500, scrollTop: 100 })
    act(() => {
      el.dispatchEvent(new Event('scroll'))
    })
    setMetrics(el, { scrollHeight: 1200, clientHeight: 500, scrollTop: 100 })
    render(two, false)
    expect(el.scrollTop).toBe(100)
    // User scrolls back to the bottom: the next chunk resumes
    // auto-scroll instantly, to the maximum scroll position.
    setMetrics(el, { scrollHeight: 1200, clientHeight: 500, scrollTop: 700 })
    act(() => {
      el.dispatchEvent(new Event('scroll'))
    })
    setMetrics(el, { scrollHeight: 1400, clientHeight: 500, scrollTop: 700 })
    render(three, false)
    expect(el.scrollTop).toBe(900)
  })

  it('never calls scrollIntoView (no smooth animation to restart)', () => {
    origScrollIntoView = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = vi.fn()
    const { render } = renderList(
      [{ id: 1, role: 'user', content: 'hi' }],
      true
    )
    render(
      [
        { id: 1, role: 'user', content: 'hi' },
        { id: 2, role: 'assistant', content: 'hello' },
      ],
      true
    )
    render(
      [
        { id: 1, role: 'user', content: 'hi' },
        { id: 2, role: 'assistant', content: 'hello world' },
      ],
      true
    )
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })
})

describe('MessageList Thinking bubble (Phase 2.3 F3)', () => {
  it('shows Thinking while sending with no assistant bubble yet', () => {
    const { container } = renderList(
      [{ id: 1, role: 'user', content: 'hi' }],
      true
    )
    expect(container.textContent).toContain('Thinking')
  })
})

describe('MessageList interrupted label', () => {
  it('labels a saved incomplete reply as interrupted', () => {
    const html = renderToString(
      <MessageList
        messages={[
          { id: 1, role: 'user', content: 'hi' },
          {
            id: 2,
            role: 'assistant',
            content: 'half an ans',
            status: 'incomplete',
          },
        ]}
        sending={false}
      />
    )
    expect(html).toContain('half an ans')
    expect(html).toContain('Response interrupted')
  })

  it('labels a live interrupted bubble (incomplete flag)', () => {
    const html = renderToString(
      <MessageList
        messages={[
          { role: 'assistant', content: 'partial', incomplete: true },
        ]}
        sending={false}
      />
    )
    expect(html).toContain('Response interrupted')
  })

  it('does not label a normal completed reply', () => {
    const html = renderToString(
      <MessageList
        messages={[
          {
            id: 3,
            role: 'assistant',
            content: 'full answer',
            status: 'complete',
          },
        ]}
        sending={false}
      />
    )
    expect(html).not.toContain('Response interrupted')
  })
})

describe('MessageList read-aloud (Phase 7 Stage A)', () => {
  let utterances

  beforeEach(() => {
    utterances = []
    window.speechSynthesis = { speak: vi.fn(), cancel: vi.fn() }
    window.SpeechSynthesisUtterance = class {
      constructor(text) {
        this.text = text
        utterances.push(this)
      }
    }
  })

  afterEach(() => {
    delete window.speechSynthesis
    delete window.SpeechSynthesisUtterance
  })

  function renderSpeakingList(messages, voiceLang) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    roots.push(root)
    act(() => {
      root.render(
        <MessageList
          messages={messages}
          sending={false}
          voiceLang={voiceLang}
        />
      )
    })
    return container
  }

  it('reads an assistant reply aloud in the chosen language', () => {
    const container = renderSpeakingList(
      [{ id: 1, role: 'assistant', content: 'Hello there' }],
      'hi-IN'
    )
    const button = container.querySelector('.speak-btn')
    expect(button).toBeTruthy()
    act(() => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(utterances[0].text).toBe('Hello there')
    expect(utterances[0].lang).toBe('hi-IN')
    expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(1)
    expect(button.textContent).toContain('Stop')
  })

  it('stops on a second click and clears state when speech ends', () => {
    const container = renderSpeakingList([
      { id: 1, role: 'assistant', content: 'Hello there' },
    ])
    const button = container.querySelector('.speak-btn')
    act(() => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    act(() => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(window.speechSynthesis.cancel).toHaveBeenCalled()
    expect(button.textContent).toContain('Read aloud')
  })

  it('offers no read-aloud on user messages', () => {
    const container = renderSpeakingList([
      { id: 1, role: 'user', content: 'Hi' },
      { id: 2, role: 'assistant', content: 'Hello' },
    ])
    expect(container.querySelectorAll('.speak-btn').length).toBe(1)
  })

  it('shows no speak buttons when synthesis is missing', () => {
    delete window.speechSynthesis
    delete window.SpeechSynthesisUtterance
    const container = renderSpeakingList([
      { id: 1, role: 'assistant', content: 'Hello' },
    ])
    expect(container.querySelector('.speak-btn')).toBeNull()
  })
})
