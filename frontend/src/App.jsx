import { useCallback, useEffect, useState } from 'react'

import {
  deleteConversation,
  getConversation,
  listConversations,
  listModels,
  sendChat,
} from './api'
import ChatInput from './components/ChatInput'
import MemoryPanel from './components/MemoryPanel'
import MessageList from './components/MessageList'
import Sidebar from './components/Sidebar'

// App is the conductor: it owns the shared state (which conversation
// is open, its messages, the chosen model) and passes data + callbacks
// down to the presentational components. Components never fetch on
// their own — except MemoryPanel, which owns its little world.
export default function App() {
  const [view, setView] = useState('chat')
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [providers, setProviders] = useState([])
  const [model, setModel] = useState('groq::llama-3.3-70b-versatile')
  const [agent, setAgent] = useState(false)
  const [coding, setCoding] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations()
      setConversations(data.conversations)
    } catch {
      setError('Could not reach the server — is Django running on :8000?')
    }
  }, [])

  useEffect(() => {
    refreshConversations()
  }, [refreshConversations])

  useEffect(() => {
    // Load the provider/model catalogue; default to the first model
    // of the first provider that actually has a key configured.
    listModels()
      .then((data) => {
        setProviders(data.providers)
        const ready = data.providers.find((p) => p.configured)
        if (ready) setModel(`${ready.provider}::${ready.models[0].id}`)
      })
      .catch(() => {})
  }, [])

  async function openConversation(id) {
    setView('chat')
    setActiveId(id)
    setError('')
    try {
      const data = await getConversation(id)
      setMessages(data.messages)
    } catch {
      setError('Could not load that conversation.')
    }
  }

  function newChat() {
    setView('chat')
    setActiveId(null)
    setMessages([])
    setError('')
  }

  async function removeConversation(id) {
    await deleteConversation(id)
    if (id === activeId) newChat()
    refreshConversations()
  }

  async function handleSend(text) {
    setError('')
    setSending(true)
    // Optimistic: show the user's message before the server answers.
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    try {
      const data = await sendChat(text, activeId, model, agent, coding)
      setActiveId(data.conversation_id)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.reply, trace: data.trace || [] },
      ])
      refreshConversations()
    } catch (err) {
      setError(
        err.message === 'AI unavailable'
          ? '⚠️ AI unavailable — check the server keys (.env) and try again.'
          : `⚠️ ${err.message}`,
      )
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="layout">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        view={view}
        onSelect={openConversation}
        onNew={newChat}
        onDelete={removeConversation}
        onView={setView}
      />
      <main className="main">
        {view === 'memory' ? (
          <MemoryPanel />
        ) : (
          <>
            {error && <div className="error-box">{error}</div>}
            <MessageList messages={messages} sending={sending} />
            <ChatInput
              providers={providers}
              model={model}
              onModel={setModel}
              agent={agent}
              onAgent={setAgent}
              coding={coding}
              onCoding={setCoding}
              onSend={handleSend}
              sending={sending}
            />
          </>
        )}
      </main>
    </div>
  )
}
