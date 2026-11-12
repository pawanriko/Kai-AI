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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

describe('ChatInput plan + bundle controls (Phase 6)', () => {
  function renderAgentInput(props = {}) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    roots.push(root)
    act(() => {
      root.render(
        <ChatInput
          providers={PROVIDERS}
          model="groq::llama-3.3-70b-versatile"
          onModel={() => {}}
          agent={props.agent ?? true}
          onAgent={() => {}}
          coding={false}
          onCoding={() => {}}
          planFirst={props.planFirst ?? false}
          onPlanFirst={props.onPlanFirst ?? (() => {})}
          bundle={props.bundle ?? 'all'}
          onBundle={props.onBundle ?? (() => {})}
          onSend={() => {}}
          sending={false}
        />
      )
    })
    return container
  }

  it('shows plan toggle and bundle picker only in agent mode', () => {
    const agentOn = renderAgentInput({ agent: true })
    expect(agentOn.querySelector('.bundle-picker')).toBeTruthy()
    expect(
      [...agentOn.querySelectorAll('button')].some((b) =>
        b.textContent.startsWith('Plan')
      )
    ).toBe(true)

    const agentOff = renderAgentInput({ agent: false })
    expect(agentOff.querySelector('.bundle-picker')).toBeNull()
    expect(
      [...agentOff.querySelectorAll('button')].some((b) =>
        b.textContent.startsWith('Plan')
      )
    ).toBe(false)
  })

  it('toggles plan-first and picks a bundle', () => {
    const onPlanFirst = vi.fn()
    const onBundle = vi.fn()
    const container = renderAgentInput({ onPlanFirst, onBundle })
    const planButton = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Plan OFF'
    )
    act(() => {
      planButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onPlanFirst).toHaveBeenCalledWith(true)

    const picker = container.querySelector('.bundle-picker')
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        'value'
      ).set
      setter.call(picker, 'research')
      picker.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(onBundle).toHaveBeenCalledWith('research')
  })
})

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

describe('ChatInput Auto option (Phase 3)', () => {
  it('offers an Auto router choice first in the picker', () => {
    const { container } = renderInput({ onSend: vi.fn() })
    const options = [...container.querySelectorAll('.model-picker option')]
    expect(options[0].value).toBe('auto')
    expect(options[0].textContent).toContain('Auto')
    expect(options[0].disabled).toBe(false)
  })
})

describe('ChatInput voice controls (Phase 7 Stage A)', () => {
  class FakeRecognition {
    static instances = []

    constructor() {
      FakeRecognition.instances.push(this)
      this.start = vi.fn()
      this.stop = vi.fn()
    }

    fireResult(transcript, isFinal) {
      this.onresult({
        resultIndex: 0,
        results: [{ 0: { transcript }, isFinal }],
      })
    }

    fireError(code) {
      this.onerror({ error: code })
    }

    fireEnd() {
      this.onend()
    }
  }

  beforeEach(() => {
    FakeRecognition.instances = []
    window.SpeechRecognition = FakeRecognition
  })

  afterEach(() => {
    delete window.SpeechRecognition
  })

  function renderVoiceInput(props = {}) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    roots.push(root)
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
          planFirst={false}
          onPlanFirst={() => {}}
          bundle="all"
          onBundle={() => {}}
          voiceLang={props.voiceLang ?? 'en-IN'}
          onVoiceLang={props.onVoiceLang ?? (() => {})}
          onSend={() => {}}
          sending={false}
        />
      )
    })
    return container
  }

  function micButton(container) {
    return container.querySelector('.mic-btn')
  }

  it('shows the mic button and language picker when supported', () => {
    const container = renderVoiceInput()
    expect(micButton(container)).toBeTruthy()
    expect(micButton(container).textContent).toContain('Speak')
    expect(container.querySelector('.voice-lang-picker')).toBeTruthy()
  })

  it('starts listening on click and appends final transcripts', () => {
    const container = renderVoiceInput()
    act(() => {
      micButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    const recognition = FakeRecognition.instances[0]
    expect(recognition.start).toHaveBeenCalledTimes(1)
    expect(recognition.lang).toBe('en-IN')
    expect(micButton(container).textContent).toContain('Stop')
    act(() => {
      recognition.fireResult('hello kai', true)
    })
    expect(container.querySelector('.composer-input').value).toBe('hello kai')
    act(() => {
      recognition.fireEnd()
    })
    expect(micButton(container).textContent).toContain('Speak')
  })

  it('shows interim previews and friendly errors without touching the box', () => {
    const container = renderVoiceInput()
    act(() => {
      micButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    const recognition = FakeRecognition.instances[0]
    act(() => {
      recognition.fireResult('hearing', false)
    })
    expect(container.textContent).toContain('Hearing: hearing')
    expect(container.querySelector('.composer-input').value).toBe('')
    act(() => {
      recognition.fireError('not-allowed')
    })
    expect(container.textContent).toContain('Microphone blocked')
  })

  it('stops listening on a second click', () => {
    const container = renderVoiceInput()
    act(() => {
      micButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    const recognition = FakeRecognition.instances[0]
    act(() => {
      micButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })
    expect(recognition.stop).toHaveBeenCalledTimes(1)
  })

  it('changes the voice language through the picker', () => {
    const onVoiceLang = vi.fn()
    const container = renderVoiceInput({ onVoiceLang })
    const picker = container.querySelector('.voice-lang-picker')
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        'value'
      ).set
      setter.call(picker, 'hi-IN')
      picker.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(onVoiceLang).toHaveBeenCalledWith('hi-IN')
  })

  it('hides voice controls when the browser has no speech APIs', () => {
    delete window.SpeechRecognition
    const container = renderVoiceInput()
    expect(micButton(container)).toBeNull()
    expect(container.querySelector('.voice-lang-picker')).toBeNull()
  })
})
