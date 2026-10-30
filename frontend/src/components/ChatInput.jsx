import { useState } from 'react'

import { MODELS } from '../api'

// Bottom bar: model picker + message box + Send. Enter sends,
// Shift+Enter makes a new line. The text lives here; sending hands
// it up to App via onSend and clears the box.
export default function ChatInput({ model, onModel, onSend, sending }) {
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
        title="Model"
      >
        {MODELS.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
      <textarea
        className="composer-input"
        rows={1}
        placeholder="Type a message…"
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
