import { useEffect, useState } from 'react'

import {
  addMemory,
  confirmMemory,
  deleteMemory,
  exportMemories,
  listDuplicates,
  listMemories,
  mergeMemories,
  rejectMemory,
  setMemoryScope,
} from '../api'

// The Memory view (Phase 1 Step 6, extended in Phase 4): facts KAI
// extracted land as SUGGESTIONS first — they only reach future
// system prompts after the user confirms them here. Confirmed
// facts can be forgotten; suggestions can be confirmed or
// rejected. Phase 4 adds: search + project filter, adding a fact
// directly (lands confirmed — the user typed it), per-fact
// project scope, near-duplicate merging, and JSON/Markdown export.
function ScopeInput({ memory, onScoped }) {
  const [project, setProject] = useState(memory.project || '')

  async function save() {
    const updated = await setMemoryScope(memory.id, project)
    onScoped(updated)
  }

  return (
    <span>
      <input
        aria-label={`Project scope for fact ${memory.id}`}
        value={project}
        onChange={(e) => setProject(e.target.value)}
        placeholder="project?"
        size={10}
      />{' '}
      <button className="forget-btn" onClick={save}>
        Set scope
      </button>
    </span>
  )
}

export default function MemoryPanel() {
  const [memories, setMemories] = useState([])
  const [duplicates, setDuplicates] = useState([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [newFact, setNewFact] = useState('')
  const [newProject, setNewProject] = useState('')
  const [formError, setFormError] = useState('')

  async function load(filters = {}) {
    try {
      const data = await listMemories(filters)
      setMemories(data.memories)
    } catch {
      setError('Could not load memory — is Django running?')
    }
  }

  async function loadDuplicates() {
    try {
      const data = await listDuplicates()
      setDuplicates(data.groups)
    } catch {
      // Duplicates are advisory; a failure here must not hide the
      // memories themselves.
    }
  }

  useEffect(() => {
    load()
    loadDuplicates()
  }, [])

  async function search(event) {
    event.preventDefault()
    await load({ q: query, project: projectFilter })
  }

  async function add(event) {
    event.preventDefault()
    setFormError('')
    try {
      await addMemory(newFact, newProject)
      setNewFact('')
      setNewProject('')
      await load({ q: query, project: projectFilter })
    } catch (err) {
      setFormError(err.message)
    }
  }

  async function confirm(id) {
    await confirmMemory(id)
    setMemories((prev) =>
      prev.map((m) => (m.id === id ? { ...m, status: 'confirmed' } : m))
    )
  }

  async function reject(id) {
    await rejectMemory(id)
    setMemories((prev) => prev.filter((m) => m.id !== id))
  }

  async function forget(id) {
    await deleteMemory(id)
    setMemories((prev) => prev.filter((m) => m.id !== id))
  }

  function scoped(updated) {
    setMemories((prev) =>
      prev.map((m) => (m.id === updated.id ? updated : m))
    )
  }

  async function merge(group) {
    const dropIds = group.members
      .map((m) => m.id)
      .filter((id) => id !== group.keeper.id)
    await mergeMemories(group.keeper.id, dropIds)
    await load({ q: query, project: projectFilter })
    await loadDuplicates()
  }

  async function download(format) {
    const blob = await exportMemories(format, projectFilter)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download =
      format === 'md' ? 'kai-memories.md' : 'kai-memories.json'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  const suggested = memories.filter((m) => m.status === 'suggested')
  const confirmed = memories.filter((m) => m.status !== 'suggested')

  function factLabel(m) {
    const bits = [m.origin]
    if (m.project) bits.push(`project: ${m.project}`)
    return bits.join(' · ')
  }

  return (
    <div className="memory-panel">
      <h2>What KAI remembers</h2>
      {error && <p className="error-box">{error}</p>}

      <form onSubmit={search}>
        <input
          aria-label="Search memories"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search facts…"
        />{' '}
        <input
          aria-label="Filter by project"
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
          placeholder="Project…"
        />{' '}
        <button type="submit">Search</button>{' '}
        <button type="button" onClick={() => download('json')}>
          Export JSON
        </button>{' '}
        <button type="button" onClick={() => download('md')}>
          Export Markdown
        </button>
      </form>

      <form onSubmit={add}>
        <h3>Add a fact directly</h3>
        <p className="muted">
          Something you state yourself is confirmed at once — no
          waiting for KAI to infer it.
        </p>
        {formError && <p className="error-box">{formError}</p>}
        <input
          aria-label="New fact"
          value={newFact}
          onChange={(e) => setNewFact(e.target.value)}
          placeholder="A durable fact about you…"
        />{' '}
        <input
          aria-label="New fact project"
          value={newProject}
          onChange={(e) => setNewProject(e.target.value)}
          placeholder="Project (optional)"
        />{' '}
        <button type="submit">Add fact</button>
      </form>

      {duplicates.length > 0 && (
        <>
          <h3>Possible duplicates</h3>
          <p className="muted">
            These facts say nearly the same thing. Merging keeps the
            first one listed and forgets the rest.
          </p>
          <ul className="memory-list">
            {duplicates.map((group) => (
              <li key={group.keeper.id} className="memory-item">
                <span>
                  {group.members.map((m) => m.fact).join(' / ')}
                </span>
                <button
                  className="forget-btn"
                  onClick={() => merge(group)}
                >
                  Merge
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {suggested.length > 0 && (
        <>
          <h3>Suggested — waiting for your OK</h3>
          <p className="muted">
            KAI inferred these from your chats. They are NOT used until
            you confirm them.
          </p>
          <ul className="memory-list">
            {suggested.map((m) => (
              <li key={m.id} className="memory-item">
                <span>
                  {m.fact}{' '}
                  <span className="muted">({factLabel(m)})</span>
                </span>
                <span>
                  <ScopeInput memory={m} onScoped={scoped} />{' '}
                  <button className="forget-btn" onClick={() => confirm(m.id)}>
                    Confirm
                  </button>{' '}
                  <button className="forget-btn" onClick={() => reject(m.id)}>
                    Reject
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Confirmed facts</h3>
      {confirmed.length === 0 && !error && (
        <p className="muted">
          Nothing yet. Tell KAI something durable — your name, your college,
          an exam date — confirm the suggestion here, and KAI will remember
          it in every chat.
        </p>
      )}
      <ul className="memory-list">
        {confirmed.map((m) => (
          <li key={m.id} className="memory-item">
            <span>
              {m.fact} <span className="muted">({factLabel(m)})</span>
            </span>
            <span>
              <ScopeInput memory={m} onScoped={scoped} />{' '}
              <button className="forget-btn" onClick={() => forget(m.id)}>
                Forget
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
