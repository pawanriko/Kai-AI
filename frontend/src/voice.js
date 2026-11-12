// Voice, Stage A only (Phase 7): the browser's own Web Speech API
// — SpeechRecognition for push-to-talk input (Hindi + English)
// and speechSynthesis for read-aloud. Zero server load, zero new
// dependencies, and no mandatory listening: recognition runs only
// while the user holds the mic open, one utterance at a time.
// (Chrome's recognition sends audio to Google's servers — that is
// inherent to the API, not to KAI.) Stage B (local Whisper/Piper)
// is explicitly out of scope until Stage A disappoints, which only
// Pawan can judge.
//
// Everything here degrades to absence: when an API is missing the
// helpers report unsupported and the UI simply shows no voice
// controls, instead of erroring.

export const VOICE_LANGUAGES = [
  { code: 'en-IN', label: 'English' },
  { code: 'hi-IN', label: 'Hindi' },
]

export const DEFAULT_VOICE_LANG = 'en-IN'

function recognitionConstructor() {
  if (typeof window === 'undefined') return null
  return window.SpeechRecognition || window.webkitSpeechRecognition || null
}

export function speechRecognitionSupported() {
  return recognitionConstructor() !== null
}

export function speechSynthesisSupported() {
  return (
    typeof window !== 'undefined' &&
    !!window.speechSynthesis &&
    typeof window.SpeechSynthesisUtterance !== 'undefined'
  )
}

// Build one recognition session. The callbacks are:
// onFinal(transcript) for each finished phrase, onInterim(text)
// for the live preview, onError(code) for failures, onEnd() when
// the session stops for any reason. Returns { start, stop } or
// null when the API is missing.
export function createRecognizer({ lang, onFinal, onInterim, onError, onEnd }) {
  const Constructor = recognitionConstructor()
  if (!Constructor) return null
  const recognition = new Constructor()
  recognition.continuous = false
  recognition.interimResults = true
  recognition.maxAlternatives = 1
  recognition.lang = lang || DEFAULT_VOICE_LANG

  recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i]
      const transcript = result[0].transcript
      if (result.isFinal) {
        onFinal?.(transcript.trim())
      } else {
        onInterim?.(transcript.trim())
      }
    }
  }
  recognition.onerror = (event) => {
    onError?.(event.error || 'unknown')
  }
  recognition.onend = () => {
    onEnd?.()
  }

  return {
    start() {
      try {
        recognition.start()
      } catch {
        onError?.('start-failed')
      }
    },
    stop() {
      try {
        recognition.stop()
      } catch {
        // Already stopped — onend has fired or will fire.
      }
    },
  }
}

// Friendly one-liners for recognition error codes.
export function voiceErrorMessage(code) {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone blocked — allow microphone access and try again.'
    case 'no-speech':
      return "Didn't catch that — try again."
    case 'audio-capture':
      return 'No microphone found on this device.'
    case 'network':
      return 'Speech service unreachable — check the connection.'
    default:
      return 'Speech recognition failed — try again.'
  }
}

// Speak text aloud, interrupting anything currently playing.
// onDone fires when the utterance ends or errors. Returns false
// when speaking is impossible (unsupported or empty text).
export function speak(text, { lang, onDone } = {}) {
  if (!speechSynthesisSupported()) return false
  const trimmed = (text || '').trim()
  if (!trimmed) return false
  window.speechSynthesis.cancel()
  const utterance = new window.SpeechSynthesisUtterance(trimmed)
  utterance.lang = lang || DEFAULT_VOICE_LANG
  utterance.onend = () => onDone?.()
  utterance.onerror = () => onDone?.()
  window.speechSynthesis.speak(utterance)
  return true
}

export function stopSpeaking() {
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    window.speechSynthesis.cancel()
  }
}
