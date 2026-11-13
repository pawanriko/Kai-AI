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

// Voice-list warm-up: Chrome loads voices asynchronously —
// getVoices() returns [] until the voiceschanged event fires,
// which can be AFTER the first read-aloud click. Warm up at
// module load (bundle import) so the cache is populated by the
// time anyone speaks, and refresh it when voices arrive. The
// cache is only a fallback: a live non-empty list always wins,
// and a transient empty list never wipes a good cache.
let cachedVoices = []
let warmingUp = false

export function warmUpVoices() {
  if (!speechSynthesisSupported()) return
  if (warmingUp) return
  warmingUp = true
  refreshVoiceCache()
  if (cachedVoices.length > 0) return
  const synth = window.speechSynthesis
  const onVoicesChanged = () => refreshVoiceCache()
  if (typeof synth.addEventListener === 'function') {
    synth.addEventListener('voiceschanged', onVoicesChanged)
  } else {
    synth.onvoiceschanged = onVoicesChanged
  }
}

function refreshVoiceCache() {
  const synth = window.speechSynthesis
  if (!synth || typeof synth.getVoices !== 'function') return
  const voices = synth.getVoices() || []
  if (voices.length > 0) cachedVoices = voices
}

function availableVoices() {
  const synth = typeof window !== 'undefined' ? window.speechSynthesis : null
  if (synth && typeof synth.getVoices === 'function') {
    const live = synth.getVoices() || []
    if (live.length > 0) return live
  }
  return cachedVoices
}

// Test-only: clear the warm-up state between tests so one test's
// voices never leak into the next.
export function resetVoiceCache() {
  cachedVoices = []
  warmingUp = false
}

// Start warming the moment the bundle loads — voices take a
// moment to arrive, and read-aloud may be clicked at any time.
warmUpVoices()

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
  warmUpVoices()
  const chunks = splitSentences(trimmed)
  const voice = pickVoice(lang || DEFAULT_VOICE_LANG)
  stopCloudAudio()
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
// voices the browser reports (live list first, warm-up cache
// when the live list is momentarily empty). Preference order:
// exact-language natural/neural voices first (Google/Microsoft
// natural voices, named human voices), then any exact-language
// voice, then any voice in the same language family. Returns
// null when no voices are known yet — the browser default is
// used instead.
export function pickVoice(lang) {
  const voices = availableVoices()
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

// Cloud audio playback: one Audio element at a time, under the
// same "one speaker" rule as the synth path. stopSpeaking()
// stops both, whichever is playing.
let currentAudio = null
let currentAudioUrl = null

function stopCloudAudio() {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio.onended = null
    currentAudio.onerror = null
    currentAudio = null
  }
  if (
    currentAudioUrl &&
    typeof URL !== 'undefined' &&
    typeof URL.revokeObjectURL === 'function'
  ) {
    URL.revokeObjectURL(currentAudioUrl)
    currentAudioUrl = null
  }
}

// Play audio bytes (a Blob from the cloud TTS endpoint).
// Interrupts anything currently playing. onDone fires when the
// clip ends, errors, or the browser refuses playback (autoplay
// policy after the fetch broke the click's user gesture — a rare
// edge that must still leave a clean stopped state, not a stuck
// "speaking" bubble). Returns false when playback is impossible.
export function playAudioBlob(blob, { onDone } = {}) {
  if (
    typeof window === 'undefined' ||
    typeof window.Audio === 'undefined' ||
    typeof URL === 'undefined' ||
    typeof URL.createObjectURL !== 'function'
  ) {
    return false
  }
  if (!blob || blob.size === 0) return false
  stopSpeaking()
  const url = URL.createObjectURL(blob)
  const audio = new window.Audio(url)
  currentAudio = audio
  currentAudioUrl = url
  const finish = () => {
    if (currentAudio === audio) {
      currentAudio = null
      currentAudioUrl = null
    }
    URL.revokeObjectURL(url)
    onDone?.()
  }
  audio.onended = finish
  audio.onerror = finish
  const playing = audio.play()
  if (playing && typeof playing.catch === 'function') {
    playing.catch(() => finish())
  }
  return true
}

export function stopSpeaking() {
  stopCloudAudio()
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    window.speechSynthesis.cancel()
  }
}
