import { useEffect, useRef, useState } from 'react'

import {
  DEFAULT_VOICE_LANG,
  VOICE_LANGUAGES,
  createRecognizer,
  speechRecognitionSupported,
  speechSynthesisSupported,
  voiceErrorMessage,
} from '../voice'
import {
  AgentIcon,
  CodeIcon,
  MicIcon,
  PlanIcon,
  StopIcon,
} from './icons'

// Bottom bar: provider-grouped model picker, Agent mode toggle,
// message box, Send. Enter sends, Shift+Enter makes a new line.
// Picker options come from the backend catalogue; providers without
// an API key in .env are shown disabled with a "(no key)" suffix.
export default function ChatInput({
  providers,
  model,
  onModel,
  agent,
  onAgent,
  coding,
  onCoding,
  planFirst,
  onPlanFirst,
  bundle,
  onBundle,
  voiceLang = DEFAULT_VOICE_LANG,
  onVoiceLang = () => {},
  onSend,
  sending,
}) {
  const [text, setText] = useState('')
  // Phase 2.2: synchronous in-flight guard. The `sending` prop
  // alone cannot stop a double submit: it only changes on the next
  // render, so two fast clicks (or Enter + click) both read the
  // stale `false` and both fire onSend — the live duplicate prompt
  // on 2026-11-11. A ref flips immediately, inside the same tick,
  // so the second submit in the same tick is blocked. It re-arms
  // when the parent reports the send finished (sending flips
  // false); App.jsx sets sending=true synchronously in handleSend,
  // so the guard cannot get stuck armed.
  const submittingRef = useRef(false)

  useEffect(() => {
    if (!sending) submittingRef.current = false
  }, [sending])

  // Phase 7 (Stage A): push-to-talk via the Web Speech API.
  // Listening runs only while the user asked for it — one
  // utterance, then the session ends on its own. Final phrases
  // append to the message box; interim text is only a preview.
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [voiceError, setVoiceError] = useState('')
  const recognizerRef = useRef(null)
  const sttSupported = speechRecognitionSupported()
  const voiceSupported =
    sttSupported || speechSynthesisSupported()

  useEffect(
    () => () => {
      recognizerRef.current?.stop()
    },
    []
  )

  function toggleListening() {
    if (listening) {
      recognizerRef.current?.stop()
      return
    }
    setVoiceError('')
    setInterim('')
    const recognizer = createRecognizer({
      lang: voiceLang,
      onFinal: (transcript) => {
        if (!transcript) return
        setText((prev) => (prev ? `${prev} ${transcript}` : transcript))
      },
      onInterim: setInterim,
      onError: (code) => setVoiceError(voiceErrorMessage(code)),
      onEnd: () => {
        setListening(false)
        setInterim('')
        recognizerRef.current = null
      },
    })
    if (!recognizer) {
      setVoiceError('Speech recognition is not available in this browser.')
      return
    }
    recognizerRef.current = recognizer
    recognizer.start()
    setListening(true)
  }

  function changeVoiceLang(code) {
    if (listening) recognizerRef.current?.stop()
    onVoiceLang(code)
  }

  // Icon-only language toggle: one tap cycles English ⇄ Hindi.
  // The glyph itself says which language is active — "A" for
  // English, "अ" for Hindi — with the full name in the tooltip.
  function toggleVoiceLang() {
    const current = VOICE_LANGUAGES.findIndex((l) => l.code === voiceLang)
    const next = VOICE_LANGUAGES[(current + 1) % VOICE_LANGUAGES.length]
    changeVoiceLang(next.code)
  }

  function submit() {
    const value = text.trim()
    if (!value || sending || submittingRef.current) return
    submittingRef.current = true
    setText('')
    onSend(value)
  }

  return (
    <div className="composer">
      <select
        className="model-picker"
        value={model}
        onChange={(e) => onModel(e.target.value)}
        title="Provider and model"
      >
        {/* Phase 3: Auto lets the task router pick a free model per
            message (coding/research/reasoning/chat). It never picks
            a paid model — those stay explicit picks only. */}
        <option value="auto">Auto (router — free models)</option>
        {providers.map((p) => (
          <optgroup key={p.provider} label={p.label}>
            {p.models.map((m) => (
              <option
                key={`${p.provider}::${m.id}`}
                value={`${p.provider}::${m.id}`}
                disabled={!p.configured}
              >
                {m.label}
                {p.configured ? '' : ' (no key)'}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {/* Icon-only mode toggles: the icon + active glow is the
          whole control — no ON/OFF text. aria-labels carry the
          meaning for tests and assistive tech. */}
      <button
        className={agent ? 'agent-toggle icon-btn active' : 'agent-toggle icon-btn'}
        onClick={() => onAgent(!agent)}
        aria-label="Agent mode"
        aria-pressed={agent}
        title="Agent mode: KAI can use tools (calculator, weather, date/time)"
      >
        <AgentIcon />
      </button>
      <button
        className={coding ? 'agent-toggle icon-btn active' : 'agent-toggle icon-btn'}
        onClick={() => onCoding(!coding)}
        aria-label="Coding mode"
        aria-pressed={coding}
        title="Coding mode: KAI can read/write code and run tests in the sandbox workspace"
      >
        <CodeIcon />
      </button>
      {/* Phase 6: plan-then-execute + tool bundles only make sense
          with tools on, so they appear with Agent mode. */}
      {agent && (
        <>
          <button
            className={planFirst ? 'agent-toggle icon-btn active' : 'agent-toggle icon-btn'}
            onClick={() => onPlanFirst(!planFirst)}
            aria-label="Plan first"
            aria-pressed={planFirst}
            title="Plan first: KAI shows its plan before running any tools"
          >
            <PlanIcon />
          </button>
          <select
            className="bundle-picker"
            value={bundle}
            onChange={(e) => onBundle(e.target.value)}
            title="Tool bundle: which tools the agent may use"
          >
            <option value="all">All tools</option>
            <option value="research">Research</option>
            <option value="productivity">Productivity</option>
            <option value="coding">Coding</option>
          </select>
        </>
      )}
      <textarea
        className="composer-input"
        rows={1}
        placeholder={
          coding
            ? 'Tell KAI what to build or fix in the workspace…'
            : agent
              ? 'Ask KAI to do something — it can use tools…'
              : 'Type a message…'
        }
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <button className="send-btn" onClick={submit} disabled={sending}>
        Send
      </button>
      {sttSupported && (
        <button
          className={listening ? 'mic-btn icon-btn listening' : 'mic-btn icon-btn'}
          onClick={toggleListening}
          aria-label={listening ? 'Stop listening' : 'Speak'}
          aria-pressed={listening}
          title={
            listening
              ? 'Stop listening'
              : 'Speak: dictate your message (push to talk)'
          }
        >
          {listening ? <StopIcon /> : <MicIcon />}
        </button>
      )}
      {voiceSupported && (
        <button
          className="lang-btn icon-btn"
          onClick={toggleVoiceLang}
          aria-label="Voice language"
          title={`Voice language: ${
            VOICE_LANGUAGES.find((l) => l.code === voiceLang)?.label ||
            voiceLang
          } — click to switch`}
        >
          <span aria-hidden="true">{voiceLang.startsWith('hi') ? 'अ' : 'A'}</span>
        </button>
      )}
      {(interim || voiceError) && (
        <span className="voice-hint">
          {voiceError || `Hearing: ${interim}`}
        </span>
      )}
    </div>
  )
}
