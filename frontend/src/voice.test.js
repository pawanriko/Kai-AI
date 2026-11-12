// @vitest-environment jsdom
//
// Phase 7 (Stage A): the voice helpers wrap the browser's Web
// Speech API. The browser APIs are stubbed here — these tests
// lock the wiring (configuration, event routing, degradation),
// not the browser's own recognition quality.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createRecognizer,
  pickVoice,
  resetVoiceCache,
  speak,
  speechRecognitionSupported,
  speechSynthesisSupported,
  splitSentences,
  stopSpeaking,
  voiceErrorMessage,
  warmUpVoices,
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
    resetVoiceCache()
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

  it('picks the most natural exact-language voice, then falls back', () => {
    const flat = { name: 'Default Voice', lang: 'en-IN' }
    const natural = { name: 'Google US English', lang: 'en-IN' }
    const hindi = { name: 'Microsoft Heera - Hindi (India)', lang: 'hi-IN' }
    window.speechSynthesis = {
      getVoices: () => [flat, natural, hindi],
    }
    expect(pickVoice('en-IN')).toBe(natural)
    expect(pickVoice('hi-IN')).toBe(hindi)
    // No exact match: same family, then nothing.
    expect(pickVoice('en-US')).toBe(natural)
    expect(pickVoice('fr-FR')).toBeNull()
    window.speechSynthesis = { getVoices: () => [] }
    expect(pickVoice('en-IN')).toBeNull()
    window.speechSynthesis = {}
    expect(pickVoice('en-IN')).toBeNull()
  })

  it('splits replies into sentences and tunes delivery', () => {
    const utterances = []
    const natural = { name: 'Google हिन्दी', lang: 'hi-IN' }
    window.speechSynthesis = {
      speak: vi.fn(),
      cancel: vi.fn(),
      getVoices: () => [natural],
    }
    window.SpeechSynthesisUtterance = class {
      constructor(text) {
        this.text = text
        utterances.push(this)
      }
    }
    const onDone = vi.fn()
    expect(
      speak('First sentence. Second one! And a third?', {
        lang: 'hi-IN',
        onDone,
      })
    ).toBe(true)
    expect(utterances.map((u) => u.text)).toEqual([
      'First sentence.',
      'Second one!',
      'And a third?',
    ])
    for (const u of utterances) {
      expect(u.lang).toBe('hi-IN')
      expect(u.voice).toBe(natural)
      expect(u.rate).toBe(0.95)
      expect(u.pitch).toBe(1.0)
    }
    expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(3)
    // onDone fires only after the LAST chunk ends.
    utterances[0].onend()
    expect(onDone).not.toHaveBeenCalled()
    utterances[1].onend()
    expect(onDone).not.toHaveBeenCalled()
    utterances[2].onend()
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('keeps unpunctuated text as one chunk', () => {
    expect(splitSentences('Hello Kai')).toEqual(['Hello Kai'])
    expect(splitSentences('One. Two.\nThree!')).toEqual([
      'One.',
      'Two.',
      'Three!',
    ])
    expect(splitSentences('   ')).toEqual([])
  })
})

describe('voice warm-up', () => {
  beforeEach(() => {
    resetVoiceCache()
    window.SpeechSynthesisUtterance = class {
      constructor(text) {
        this.text = text
      }
    }
  })

  afterEach(() => {
    resetVoiceCache()
  })

  it('caches voices arriving via voiceschanged and falls back to the cache', () => {
    let voices = []
    const listeners = {}
    window.speechSynthesis = {
      getVoices: () => voices,
      addEventListener: vi.fn((type, cb) => {
        listeners[type] = cb
      }),
      speak: vi.fn(),
      cancel: vi.fn(),
    }
    warmUpVoices()
    expect(pickVoice('en-IN')).toBeNull()

    const natural = { name: 'Google US English', lang: 'en-IN' }
    voices = [natural]
    listeners.voiceschanged()
    // The live list goes empty again (async timing) — the cache
    // still serves the voice instead of the flat default.
    voices = []
    expect(pickVoice('en-IN')).toBe(natural)
  })

  it('attaches only one voiceschanged listener', () => {
    const addEventListener = vi.fn()
    window.speechSynthesis = {
      getVoices: () => [],
      addEventListener,
      speak: vi.fn(),
      cancel: vi.fn(),
    }
    warmUpVoices()
    warmUpVoices()
    expect(addEventListener).toHaveBeenCalledTimes(1)
    expect(addEventListener).toHaveBeenCalledWith(
      'voiceschanged',
      expect.any(Function)
    )
  })

  it('uses onvoiceschanged when addEventListener is missing', () => {
    const synth = {
      getVoices: () => [],
      speak: vi.fn(),
      cancel: vi.fn(),
    }
    window.speechSynthesis = synth
    warmUpVoices()
    expect(typeof synth.onvoiceschanged).toBe('function')

    const natural = { name: 'Google हिन्दी', lang: 'hi-IN' }
    synth.getVoices = () => [natural]
    synth.onvoiceschanged()
    synth.getVoices = () => []
    expect(pickVoice('hi-IN')).toBe(natural)
  })

  it('skips the listener when voices are already loaded', () => {
    const addEventListener = vi.fn()
    window.speechSynthesis = {
      getVoices: () => [{ name: 'Google US English', lang: 'en-IN' }],
      addEventListener,
      speak: vi.fn(),
      cancel: vi.fn(),
    }
    warmUpVoices()
    expect(addEventListener).not.toHaveBeenCalled()
  })

  it('speaks trigger the warm-up so the first click is covered', () => {
    const addEventListener = vi.fn()
    window.speechSynthesis = {
      getVoices: () => [],
      addEventListener,
      speak: vi.fn(),
      cancel: vi.fn(),
    }
    expect(speak('Hello Kai')).toBe(true)
    expect(addEventListener).toHaveBeenCalledTimes(1)
  })
})
