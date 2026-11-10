import { useCallback, useEffect, useState } from 'react'

import {
  deleteConversation,
  getConversation,
  getMe,
  listConversations,
  listModels,
  logout as apiLogout,
  sendChat,
} from './api'
import ChatInput from './components/ChatInput'
import Login from './components/Login'
import MemoryPanel from './components/MemoryPanel'
import MessageList from './components/MessageList'
import Sidebar from './components/Sidebar'

// App is the conductor: it owns the shared state (which conversation
// is open, its messages, the chosen model) and passes data + callbacks
// down to the presentational components. Components never fetch on
// their own — except MemoryPanel, which owns its little world.
export default function App() {
  // Auth gate (Phase 1): null = still asking the server who we are.
  const [auth, setAuth] = useState(null)
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

  // A 401 from any data call means the Django session expired (or
  // was logged out elsewhere): drop back to the login screen instead
  // of leaving a dead app on screen.
  const sessionExpired = useCallback((err) => {
    if (err?.status !== 401) return false
    setAuth({ authenticated: false, needs_setup: false })
    setConversations([])
    setMessages([])
    setActiveId(null)
    return true
  }, [])

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations()
      setConversations(data.conversations)
    } catch (err) {
      if (!sessionExpired(err)) {
        setError('Could not reach the server — is Django running on :8000?')
      }
    }
  }, [sessionExpired])

  const refreshAuth = useCallback(async () => {
    try {
      setAuth(await getMe())
    } catch {
      setAuth({ authenticated: false, needs_setup: false })
    }
  }, [])

  useEffect(() => {
    refreshAuth()
  }, [refreshAuth])

  useEffect(() => {
    if (!auth?.authenticated) return
    refreshConversations()
    // Load the provider/model catalogue; default to the first model
    // of the first provider that actually has a key configured.
    listModels()
      .then((data) => {
        setProviders(data.providers)
        const ready = data.providers.find((p) => p.configured)
        if (ready) setModel(`${ready.provider}::${ready.models[0].id}`)
      })
      .catch(() => {})
  }, [auth, refreshConversations])

  async function handleLogout() {
    try {
      await apiLogout()
    } catch {
      // Session is gone either way from the user's point of view.
    }
    setAuth({ authenticated: false, needs_setup: false })
    setConversations([])
    setMessages([])
    setActiveId(null)
  }

  async function openConversation(id) {
    setView('chat')
    setActiveId(id)
    setError('')
    try {
      const data = await getConversation(id)
      setMessages(data.messages)
    } catch (err) {
      if (!sessionExpired(err)) {
        setError('Could not load that conversation.')
      }
    }
  }

  function newChat() {
    setView('chat')
    setActiveId(null)
    setMessages([])
    setError('')
  }

  async function removeConversation(id) {
    try {
      await deleteConversation(id)
    } catch (err) {
      if (sessionExpired(err)) return
      setError('Could not delete that conversation.')
      return
    }
    if (id === activeId) newChat()
    refreshConversations()
  }

  function handleCoding(value) {
    // Enabling CODE mode is the explicit confirmation the server
    // requires (confirm_commands): commands will run inside KAI's
    // workspace without further prompts this session. On the public
    // deployment the server additionally keeps execution disabled
    // entirely, whatever this toggle says.
    if (value) {
      const ok = window.confirm(
        'Coding mode lets KAI run commands on the server inside its ' +
          'workspace folder, without asking again for each command. ' +
          'Only enable this on your own machine. Continue?'
      )
      if (!ok) return
    }
    setCoding(value)
  }

  async function handleSend(text) {
    setError('')
    setSending(true)
    // Optimistic: show the user's message before the server answers.
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    try {
      const data = await sendChat(text, activeId, model, agent, coding, coding)
      setActiveId(data.conversation_id)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.reply, trace: data.trace || [] },
      ])
      refreshConversations()
    } catch (err) {
      if (sessionExpired(err)) return
      setError(
        err.message === 'AI unavailable'
          ? '⚠️ AI unavailable — check the server keys (.env) and try again.'
          : `⚠️ ${err.message}`,
      )
    } finally {
      setSending(false)
    }
  }

  if (auth === null) {
    return (
      <div className="login-wrap">
        <p className="muted">Loading…</p>
      </div>
    )
  }
  if (!auth.authenticated) {
    return (
      <Login
        needsSetup={auth.needs_setup}
        setupEnabled={auth.setup_enabled}
        onDone={refreshAuth}
      />
    )
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
        username={auth.username}
        onLogout={handleLogout}
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
              onCoding={handleCoding}
              onSend={handleSend}
              sending={sending}
            />
          </>
        )}
      </main>
    </div>
  )
}
