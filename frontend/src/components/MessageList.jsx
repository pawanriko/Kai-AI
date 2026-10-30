import { useEffect, useRef } from 'react'

// The scrolling transcript. Messages are plain text for now (line
// breaks preserved via CSS white-space); rich markdown rendering is a
// later polish step. Auto-scrolls to the newest message.
export default function MessageList({ messages, sending }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
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
    <div className="messages">
      {messages.map((m, i) => (
        <div key={m.id ?? `local-${i}`} className={`bubble-row ${m.role}`}>
          <div className="bubble">
            <div className="bubble-role">
              {m.role === 'user' ? 'YOU' : 'KAI'}
            </div>
            <div className="bubble-text">{m.content}</div>
            {m.trace && m.trace.length > 0 && (
              <details className="trace">
                <summary>Agent steps ({m.trace.length})</summary>
                {m.trace.map((step, j) => (
                  <div key={j} className="trace-step">
                    <span className="trace-tool">{step.tool}</span>
                    <span className="trace-args">
                      {JSON.stringify(step.args)}
                    </span>
                    <div className="trace-result">{step.result}</div>
                  </div>
                ))}
              </details>
            )}
          </div>
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
      <div ref={bottomRef} />
    </div>
  )
}
