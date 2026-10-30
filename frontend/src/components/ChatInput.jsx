import { useState } from 'react'

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
  onSend,
  sending,
}) {
  const [text, setText] = useState('')

  function submit() {
    const value = text.trim()
    if (!value || sending) return
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
      <button
        className={agent ? 'agent-toggle active' : 'agent-toggle'}
        onClick={() => onAgent(!agent)}
        title="Agent mode: KAI can use tools (calculator, weather, date/time)"
      >
        Agent {agent ? 'ON' : 'OFF'}
      </button>
      <textarea
        className="composer-input"
        rows={1}
        placeholder={
          agent
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
    </div>
  )
}
