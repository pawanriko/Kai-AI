// @vitest-environment jsdom
//
// Phase 7 (Stage A): the voice helpers wrap the browser's Web
// Speech API. The browser APIs are stubbed here — these tests
// lock the wiring (configuration, event routing, degradation),
// not the browser's own recognition quality.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createRecognizer,
  speak,
  speechRecognitionSupported,
  speechSynthesisSupported,
  stopSpeaking,
  voiceErrorMessage,
} from './voice'

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

describe('voice helpers', () => {
  beforeEach(() => {
    FakeRecognition.instances = []
  })

  afterEach(() => {
    delete window.SpeechRecognition
    delete window.webkitSpeechRecognition
    delete window.speechSynthesis
    delete window.SpeechSynthesisUtterance
    vi.restoreAllMocks()
  })

  it('reports unsupported when the browser has no APIs', () => {
    expect(speechRecognitionSupported()).toBe(false)
    expect(speechSynthesisSupported()).toBe(false)
    expect(createRecognizer({})).toBeNull()
    expect(speak('hello')).toBe(false)
  })

  it('configures the recognizer for one utterance in the chosen language', () => {
    window.SpeechRecognition = FakeRecognition
    const session = createRecognizer({ lang: 'hi-IN' })
    expect(session).not.toBeNull()
    const recognition = FakeRecognition.instances[0]
    expect(recognition.lang).toBe('hi-IN')
    expect(recognition.continuous).toBe(false)
    expect(recognition.interimResults).toBe(true)
    session.start()
    expect(recognition.start).toHaveBeenCalledTimes(1)
    session.stop()
    expect(recognition.stop).toHaveBeenCalledTimes(1)
  })

  it('prefers webkitSpeechRecognition when that is all there is', () => {
    window.webkitSpeechRecognition = FakeRecognition
    expect(speechRecognitionSupported()).toBe(true)
    expect(createRecognizer({})).not.toBeNull()
  })

  it('routes final results, interim previews, errors, and end', () => {
    window.SpeechRecognition = FakeRecognition
    const onFinal = vi.fn()
    const onInterim = vi.fn()
    const onError = vi.fn()
    const onEnd = vi.fn()
    createRecognizer({ lang: 'en-IN', onFinal, onInterim, onError, onEnd })
    const recognition = FakeRecognition.instances[0]
    recognition.fireResult('hearing this', false)
    expect(onInterim).toHaveBeenCalledWith('hearing this')
    expect(onFinal).not.toHaveBeenCalled()
    recognition.fireResult('hello kai', true)
    expect(onFinal).toHaveBeenCalledWith('hello kai')
    recognition.fireError('no-speech')
    expect(onError).toHaveBeenCalledWith('no-speech')
    recognition.fireEnd()
    expect(onEnd).toHaveBeenCalledTimes(1)
  })

  it('maps error codes to friendly messages', () => {
    expect(voiceErrorMessage('not-allowed')).toContain('Microphone blocked')
    expect(voiceErrorMessage('no-speech')).toContain("Didn't catch")
    expect(voiceErrorMessage('weird-code')).toContain('failed')
  })

  it('speaks with the chosen language and interrupts previous speech', () => {
    const utterances = []
    window.speechSynthesis = { speak: vi.fn(), cancel: vi.fn() }
    window.SpeechSynthesisUtterance = class {
      constructor(text) {
        this.text = text
        utterances.push(this)
      }
    }
    const onDone = vi.fn()
    expect(speak('Hello Kai', { lang: 'hi-IN', onDone })).toBe(true)
    expect(window.speechSynthesis.cancel).toHaveBeenCalledTimes(1)
    expect(utterances[0].text).toBe('Hello Kai')
    expect(utterances[0].lang).toBe('hi-IN')
    expect(window.speechSynthesis.speak).toHaveBeenCalledWith(utterances[0])
    utterances[0].onend()
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('refuses empty text and stops speech on demand', () => {
    window.speechSynthesis = { speak: vi.fn(), cancel: vi.fn() }
    window.SpeechSynthesisUtterance = class {
      constructor(text) {
        this.text = text
      }
    }
    expect(speak('   ')).toBe(false)
    expect(window.speechSynthesis.speak).not.toHaveBeenCalled()
    stopSpeaking()
    expect(window.speechSynthesis.cancel).toHaveBeenCalledTimes(1)
  })
})
