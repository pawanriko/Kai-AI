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
// onDone fires when the LAST chunk ends or errors. Returns false
// when speaking is impossible (unsupported or empty text).
//
// Humanizing, within what the browser allows: speechSynthesis can
// only use the voices installed on the device, so the quality
// ceiling is the OS/browser voice list — KAI cannot conjure a
// human voice from nothing. What it CAN do is pick the best voice
// available (natural/neural voices over the flat default), tune
// the delivery slightly slower than default, and speak sentence
// by sentence so the pauses land like natural phrasing instead of
// one flat run-on. A truly human voice would need a cloud TTS
// service (API key + cost) — deliberately not added here.
export function speak(text, { lang, onDone } = {}) {
  if (!speechSynthesisSupported()) return false
  const trimmed = (text || '').trim()
  if (!trimmed) return false
  const chunks = splitSentences(trimmed)
  const voice = pickVoice(lang || DEFAULT_VOICE_LANG)
  window.speechSynthesis.cancel()
  let pending = chunks.length
  const finishOne = () => {
    pending -= 1
    if (pending <= 0) onDone?.()
  }
  for (const chunk of chunks) {
    const utterance = new window.SpeechSynthesisUtterance(chunk)
    utterance.lang = lang || DEFAULT_VOICE_LANG
    utterance.rate = 0.95
    utterance.pitch = 1.0
    if (voice) utterance.voice = voice
    utterance.onend = finishOne
    utterance.onerror = finishOne
    window.speechSynthesis.speak(utterance)
  }
  return true
}

// Split reply text into speakable sentences. Delimiters stay
// attached (the pause lives in the punctuation), blank runs drop
// out, and text with no sentence punctuation stays one chunk.
export function splitSentences(text) {
  const parts = text.match(/[^.!?\n]+[.!?\n]+|[^.!?\n]+$/g) || []
  return parts.map((p) => p.trim()).filter(Boolean)
}

// Pick the most human-sounding voice for a language from the
// voices the browser reports. Preference order: exact-language
// natural/neural voices first (Google/Microsoft natural voices,
// named human voices), then any exact-language voice, then any
// voice in the same language family. Returns null when no voices
// are reported (Chrome loads them asynchronously — the browser
// default is used instead) or the list has no match.
export function pickVoice(lang) {
  const synth = typeof window !== 'undefined' ? window.speechSynthesis : null
  if (!synth || typeof synth.getVoices !== 'function') return null
  const voices = synth.getVoices() || []
  if (voices.length === 0) return null
  const wanted = (lang || DEFAULT_VOICE_LANG).toLowerCase()
  const family = wanted.split('-')[0]
  const natural = /natural|neural|google|samantha|heera|ravi|aarav|neerja|zira|david|mark/i
  const exact = voices.filter((v) => (v.lang || '').toLowerCase() === wanted)
  const exactNatural = exact.filter((v) => natural.test(v.name || ''))
  if (exactNatural.length > 0) return exactNatural[0]
  if (exact.length > 0) return exact[0]
  const familyVoices = voices.filter(
    (v) => (v.lang || '').toLowerCase().split('-')[0] === family
  )
  const familyNatural = familyVoices.filter((v) => natural.test(v.name || ''))
  if (familyNatural.length > 0) return familyNatural[0]
  if (familyVoices.length > 0) return familyVoices[0]
  return null
}

export function stopSpeaking() {
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    window.speechSynthesis.cancel()
  }
}
