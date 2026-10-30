import { useEffect, useState } from 'react'

import { deleteMemory, listMemories } from '../api'

// The Memory view: every fact KAI has extracted about the user, stored
// server-side in the Memory table. Deleting a row makes KAI forget it —
// the fact also disappears from future system prompts.
export default function MemoryPanel() {
  const [memories, setMemories] = useState([])
  const [error, setError] = useState('')

  async function load() {
    try {
      const data = await listMemories()
      setMemories(data.memories)
    } catch {
      setError('Could not load memory — is Django running?')
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function forget(id) {
    await deleteMemory(id)
    setMemories((prev) => prev.filter((m) => m.id !== id))
  }

  return (
    <div className="memory-panel">
      <h2>What KAI remembers</h2>
      {error && <p className="error-box">{error}</p>}
      {memories.length === 0 && !error && (
        <p className="muted">
          Nothing yet. Tell KAI something durable — your name, your college,
          an exam date — and it will show up here.
        </p>
      )}
      <ul className="memory-list">
        {memories.map((m) => (
          <li key={m.id} className="memory-item">
            <span>{m.fact}</span>
            <button className="forget-btn" onClick={() => forget(m.id)}>
              Forget
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
