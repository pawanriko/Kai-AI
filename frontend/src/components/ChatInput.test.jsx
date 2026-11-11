// @vitest-environment jsdom
//
// Phase 2.2: the double-submit race. The `sending` prop only changes
// on the next render, so two submits in the same tick used to both
// fire onSend (the live duplicate prompt on 2026-11-11). The
// synchronous ref guard must block the second one, and re-arm once
// the parent reports the send finished.
//
// The rapid-fire tests dispatch both events inside ONE act() block:
// React has not re-rendered between them, so the textarea still
// holds its text and the prop still reads `sending: false` —
// exactly the live race window. Only the ref can stop the second
// submit there.

// React's act() needs this flag outside a test runner that sets it.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ChatInput from './ChatInput'

const PROVIDERS = [
  {
    provider: 'groq',
    label: 'Groq',
    configured: true,
    models: [{ id: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B' }],
  },
]

const roots = []

afterEach(() => {
  act(() => {
    roots.splice(0).forEach((root) => root.unmount())
  })
  document.body.innerHTML = ''
})

function renderInput({ onSend, sending = false } = {}) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  const render = (props) => {
    act(() => {
      root.render(
        <ChatInput
          providers={PROVIDERS}
          model="groq::llama-3.3-70b-versatile"
          onModel={() => {}}
          agent={false}
          onAgent={() => {}}
          coding={false}
          onCoding={() => {}}
          onSend={onSend}
          sending={props.sending}
        />
      )
    })
  }
  render({ sending })
  return { container, render }
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

function rapidClicks(container, times = 2) {
  const button = container.querySelector('.send-btn')
  act(() => {
    for (let i = 0; i < times; i++) {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    }
  })
}

function rapidEnters(textarea, times = 2) {
  act(() => {
    for (let i = 0; i < times; i++) {
      textarea.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
      )
    }
  })
}

describe('ChatInput double-submit guard', () => {
  it('sends only once on two rapid Send clicks', () => {
    const onSend = vi.fn()
    const { container } = renderInput({ onSend })
    typeText(container.querySelector('.composer-input'), 'hello')
    rapidClicks(container)
    expect(onSend).toHaveBeenCalledTimes(1)
    expect(onSend).toHaveBeenCalledWith('hello')
  })

  it('sends only once on two rapid Enter presses', () => {
    const onSend = vi.fn()
    const { container } = renderInput({ onSend })
    const textarea = container.querySelector('.composer-input')
    typeText(textarea, 'hello')
    rapidEnters(textarea)
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('sends only once on a rapid click plus Enter', () => {
    const onSend = vi.fn()
    const { container } = renderInput({ onSend })
    const textarea = container.querySelector('.composer-input')
    typeText(textarea, 'hello')
    act(() => {
      container
        .querySelector('.send-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
      textarea.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
      )
    })
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('re-arms after the parent reports the send finished', () => {
    const onSend = vi.fn()
    const { container, render } = renderInput({ onSend })
    typeText(container.querySelector('.composer-input'), 'first')
    rapidClicks(container)
    expect(onSend).toHaveBeenCalledTimes(1)
    render({ sending: true })
    render({ sending: false })
    typeText(container.querySelector('.composer-input'), 'second')
    rapidClicks(container)
    expect(onSend).toHaveBeenCalledTimes(2)
    expect(onSend).toHaveBeenLastCalledWith('second')
  })

  it('never sends empty text', () => {
    const onSend = vi.fn()
    const { container } = renderInput({ onSend })
    typeText(container.querySelector('.composer-input'), '   ')
    rapidClicks(container)
    expect(onSend).not.toHaveBeenCalled()
  })
})
