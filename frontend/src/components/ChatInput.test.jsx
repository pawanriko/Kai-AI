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
import { polishPrompt } from '../api'

vi.mock('../api', () => ({ polishPrompt: vi.fn() }))

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
      agentOn.querySelector('[aria-label="Plan first"]')
    ).toBeTruthy()

    const agentOff = renderAgentInput({ agent: false })
    expect(agentOff.querySelector('.bundle-picker')).toBeNull()
    expect(
      agentOff.querySelector('[aria-label="Plan first"]')
    ).toBeNull()
  })

  it('toggles plan-first and picks a bundle', () => {
    const onPlanFirst = vi.fn()
    const onBundle = vi.fn()
    const container = renderAgentInput({ onPlanFirst, onBundle })
    const planButton = container.querySelector('[aria-label="Plan first"]')
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

  it('shows the mic button and language toggle when supported', () => {
    const container = renderVoiceInput()
    expect(micButton(container)).toBeTruthy()
    expect(micButton(container).getAttribute('aria-label')).toBe('Speak')
    expect(container.querySelector('.lang-btn')).toBeTruthy()
    expect(container.querySelector('.lang-btn').textContent).toBe('A')
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
    expect(micButton(container).getAttribute('aria-label')).toBe(
      'Stop listening'
    )
    expect(micButton(container).classList.contains('listening')).toBe(true)
    act(() => {
      recognition.fireResult('hello kai', true)
    })
    expect(container.querySelector('.composer-input').value).toBe('hello kai')
    act(() => {
      recognition.fireEnd()
    })
    expect(micButton(container).getAttribute('aria-label')).toBe('Speak')
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

  it('cycles the voice language through the icon toggle', () => {
    const onVoiceLang = vi.fn()
    const container = renderVoiceInput({ onVoiceLang })
    act(() => {
      container
        .querySelector('.lang-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onVoiceLang).toHaveBeenCalledWith('hi-IN')

    const hindi = renderVoiceInput({ voiceLang: 'hi-IN', onVoiceLang })
    expect(hindi.querySelector('.lang-btn').textContent).toBe('अ')
    act(() => {
      hindi
        .querySelector('.lang-btn')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onVoiceLang).toHaveBeenCalledWith('en-IN')
  })

  it('hides voice controls when the browser has no speech APIs', () => {
    delete window.SpeechRecognition
    const container = renderVoiceInput()
    expect(micButton(container)).toBeNull()
    expect(container.querySelector('.lang-btn')).toBeNull()
  })
})

describe('ChatInput prompt polish', () => {
  beforeEach(() => {
    polishPrompt.mockReset()
  })

  function polishButton(container) {
    return container.querySelector('[aria-label="Polish prompt"]')
  }

  function previewAction(container, label) {
    return [...container.querySelectorAll('.polish-actions button')].find(
      (b) => b.textContent === label
    )
  }

  function click(element) {
    act(() => {
      element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
  }

  async function flush() {
    await act(async () => {})
    await act(async () => {})
  }

  async function openPreview(container, draft = 'rough draft') {
    polishPrompt.mockResolvedValue({ polished: 'Clearer draft.' })
    typeText(container.querySelector('.composer-input'), draft)
    click(polishButton(container))
    await flush()
  }

  it('disables the polish button when the box is empty', () => {
    const { container } = renderInput({ onSend: () => {} })
    expect(polishButton(container).disabled).toBe(true)
    typeText(container.querySelector('.composer-input'), 'rough draft')
    expect(polishButton(container).disabled).toBe(false)
  })

  it('shows the rewrite as a preview without sending', async () => {
    const onSend = vi.fn()
    const { container } = renderInput({ onSend })
    await openPreview(container)
    expect(polishPrompt).toHaveBeenCalledWith('rough draft')
    expect(container.querySelector('.polish-text').textContent).toBe(
      'Clearer draft.'
    )
    expect(onSend).not.toHaveBeenCalled()
  })

  it('Use replaces the draft and closes the preview', async () => {
    const { container } = renderInput({ onSend: () => {} })
    await openPreview(container)
    const textarea = container.querySelector('.composer-input')
    click(previewAction(container, 'Use this'))
    expect(textarea.value).toBe('Clearer draft.')
    expect(container.querySelector('.polish-preview')).toBeNull()
  })

  it('Keep original leaves the draft and closes the preview', async () => {
    const { container } = renderInput({ onSend: () => {} })
    await openPreview(container)
    const textarea = container.querySelector('.composer-input')
    click(previewAction(container, 'Keep original'))
    expect(textarea.value).toBe('rough draft')
    expect(container.querySelector('.polish-preview')).toBeNull()
  })

  it('a failed polish shows an error and keeps the draft', async () => {
    const { container } = renderInput({ onSend: () => {} })
    polishPrompt.mockRejectedValue(new Error('Polishing failed'))
    const textarea = container.querySelector('.composer-input')
    typeText(textarea, 'rough draft')
    click(polishButton(container))
    await flush()
    expect(container.querySelector('.voice-hint').textContent).toBe(
      'Could not polish — try again.'
    )
    expect(textarea.value).toBe('rough draft')
    expect(container.querySelector('.polish-preview')).toBeNull()
  })

  it('typing clears an open preview', async () => {
    const { container } = renderInput({ onSend: () => {} })
    await openPreview(container)
    const textarea = container.querySelector('.composer-input')
    typeText(textarea, 'rough draft, edited')
    expect(container.querySelector('.polish-preview')).toBeNull()
  })
})
