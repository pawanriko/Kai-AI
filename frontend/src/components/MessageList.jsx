import { memo, useCallback, useEffect, useRef, useState } from 'react'

import { speakCloud } from '../api'
import {
  DEFAULT_VOICE_LANG,
  playAudioBlob,
  speak,
  speechSynthesisSupported,
  stopSpeaking,
} from '../voice'
import { SpeakerIcon, StopIcon } from './icons'

// The scrolling transcript. Messages are plain text for now (line
// breaks preserved via CSS white-space); rich markdown rendering is a
// later polish step.
//
// Phase 2.3 (F1): the transcript div itself is the scroll container
// (.messages, overflow-y: auto). The old effect called
// scrollIntoView({ behavior: 'smooth' }) on every messages change —
// and every stream chunk changes messages — so each chunk restarted
// a smooth-scroll animation, which juddered while text grew and
// yanked readers who had scrolled up. Now the scroll is instant
// (plain scrollTop assignment — no animation to restart) and only
// while the user is already near the bottom: if they scrolled up to
// read, new chunks never move the viewport.
//
// Phase 2.3 (F2): each bubble row is memoized. The transcript
// re-renders on every flushed chunk, but only the growing assistant
// bubble gets a new object identity, so only it re-renders — the
// rest of the list is skipped by React.memo.

const NEAR_BOTTOM_PX = 120

function MessageBubble({ message: m, bubbleKey, speaking, onSpeak, ttsConfigured }) {
  return (
    <div className="bubble">
      <div className="bubble-role">{m.role === 'user' ? 'YOU' : 'KAI'}</div>
      <div className="bubble-text">{m.content}</div>
      {(m.incomplete || m.status === 'incomplete') && (
        <div className="bubble-note">⚠️ Response interrupted — incomplete</div>
      )}
      {/* Read-aloud for assistant replies: the cloud voice when
          the server has a key, else the browser voice. The button
          appears when EITHER path exists — a browser without
          speechSynthesis can still hear the cloud voice. Speaking
          state lives in MessageList so only one bubble can talk
          at a time. onSpeak is a stable callback taking the bubble
          key, so React.memo keeps working. */}
      {m.role === 'assistant' && (speechSynthesisSupported() || ttsConfigured) && (
        <button
          className="speak-btn icon-btn"
          onClick={() => onSpeak(bubbleKey, m.content)}
          aria-label={speaking ? 'Stop reading aloud' : 'Read aloud'}
          title={speaking ? 'Stop reading aloud' : 'Read aloud'}
        >
          {speaking ? <StopIcon /> : <SpeakerIcon />}
        </button>
      )}
      {m.trace && m.trace.length > 0 && (
        <details className="trace">
          <summary>Agent steps ({m.trace.length})</summary>
          {m.trace.map((step, j) => (
            <div key={j} className="trace-step">
              <span className="trace-tool">{step.tool}</span>
              <span className="trace-args">{JSON.stringify(step.args)}</span>
              <div className="trace-result">{step.result}</div>
            </div>
          ))}
        </details>
      )}
    </div>
  )
}

const MemoBubble = memo(MessageBubble)

export default function MessageList({
  messages,
  sending,
  voiceLang = DEFAULT_VOICE_LANG,
  ttsConfigured = false,
}) {
  const listRef = useRef(null)
  const stickRef = useRef(true)
  const [speakingKey, setSpeakingKey] = useState(null)
  // Guards the async cloud fetch: every speak/stop click bumps
  // the token, so a fetch resolving after the user stopped (or
  // picked another bubble) never starts stale audio.
  const speakRequestRef = useRef(0)

  // Stop any speech when the transcript unmounts (view switch).
  useEffect(
    () => () => {
      speakRequestRef.current += 1
      stopSpeaking()
    },
    []
  )

  const handleSpeak = useCallback(
    async (key, content) => {
      const requestId = ++speakRequestRef.current
      if (speakingKey === key) {
        stopSpeaking()
        setSpeakingKey(null)
        return
      }
      stopSpeaking()
      // Cloud voice first when the server has a key; ANY failure
      // (unconfigured, rate-limited, provider down, playback
      // refused) falls through to the browser voice, so read-aloud
      // never hard-fails on a cloud problem.
      if (ttsConfigured) {
        try {
          const blob = await speakCloud(content)
          if (requestId !== speakRequestRef.current) return
          const started = playAudioBlob(blob, {
            onDone: () => setSpeakingKey(null),
          })
          if (started) {
            setSpeakingKey(key)
            return
          }
        } catch {
          if (requestId !== speakRequestRef.current) return
        }
      }
      const started = speak(content, {
        lang: voiceLang,
        onDone: () => setSpeakingKey(null),
      })
      if (started) setSpeakingKey(key)
    },
    [speakingKey, voiceLang, ttsConfigured]
  )

  function handleScroll() {
    const el = listRef.current
    if (!el) return
    stickRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
  }

  useEffect(() => {
    const el = listRef.current
    if (!el || !stickRef.current) return
    // The actual maximum scroll position: scrollHeight alone
    // overshoots by one viewport (browsers clamp it, but the
    // assignment should say what it means), and when the content
    // is shorter than the container the maximum is 0, never
    // negative.
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight)
  }, [messages, sending])

  if (messages.length === 0 && !sending) {
    return (
      <div className="messages empty-state">
        <h2>Ask KAI anything</h2>
        <p>
          Your chats are stored on the server now — and KAI quietly learns
          facts about you as you talk. Check the Memory tab to see them.
        </p>
      </div>
    )
  }

  return (
    <div className="messages" ref={listRef} onScroll={handleScroll}>
      {messages.map((m, i) => (
        <div key={m.id ?? `local-${i}`} className={`bubble-row ${m.role}`}>
          <MemoBubble
            message={m}
            bubbleKey={m.id ?? `local-${i}`}
            speaking={speakingKey === (m.id ?? `local-${i}`)}
            onSpeak={handleSpeak}
            ttsConfigured={ttsConfigured}
          />
        </div>
      ))}
      {sending && (
        <div className="bubble-row assistant">
          <div className="bubble thinking">
            <div className="bubble-role">KAI</div>
            <div className="bubble-text">Thinking…</div>
          </div>
        </div>
      )}
    </div>
  )
}
