import { useCallback, useEffect, useState } from 'react'

import {
  deleteConversation,
  getConversation,
  getMe,
  listConversations,
  logout,
  MODELS,
  sendChat,
} from './api'
import AuthScreen from './components/AuthScreen'
import ChatInput from './components/ChatInput'
import MemoryPanel from './components/MemoryPanel'
import MessageList from './components/MessageList'
import Sidebar from './components/Sidebar'

export default function App() {
  const [user, setUser] = useState(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [view, setView] = useState('chat')
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [model, setModel] = useState(MODELS[0].id)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations()
      setConversations(data.conversations)
    } catch (err) {
      setError(err.message === 'authentication required'
        ? 'Your session has expired. Sign in again.'
        : 'Could not reach the server. Is Django running on :8000?')
    }
  }, [])

  useEffect(() => {
    getMe()
      .then((data) => {
        setUser(data.user)
        return listConversations()
      })
      .then((data) => setConversations(data.conversations))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true))
  }, [])

  function handleAuthenticated(authenticatedUser) {
    setUser(authenticatedUser)
    setError('')
    refreshConversations()
  }

  async function handleLogout() {
    try {
      await logout()
    } finally {
      setUser(null)
      setConversations([])
      setActiveId(null)
      setMessages([])
      setError('')
    }
  }

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
    try {
      await deleteConversation(id)
      if (id === activeId) newChat()
      await refreshConversations()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleSend(text) {
    setError('')
    setSending(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    try {
      const data = await sendChat(text, activeId, model)
      setActiveId(data.conversation_id)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }])
      refreshConversations()
    } catch (err) {
      setError(err.message === 'AI unavailable'
        ? 'AI unavailable. Check the server keys in .env and try again.'
        : err.message)
    } finally {
      setSending(false)
    }
  }

  if (!authChecked) {
    return <main className="auth-screen"><p className="muted">Loading KAI…</p></main>
  }
  if (!user) return <AuthScreen onAuthenticated={handleAuthenticated} />

  return (
    <div className="layout">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        view={view}
        username={user.username}
        onSelect={openConversation}
        onNew={newChat}
        onDelete={removeConversation}
        onView={setView}
        onLogout={handleLogout}
      />
      <main className="main">
        {error && <div className="error-box">{error}</div>}
        {view === 'memory'
          ? <MemoryPanel />
          : <><MessageList messages={messages} sending={sending} /><ChatInput model={model} onModel={setModel} onSend={handleSend} sending={sending} /></>}
      </main>
    </div>
  )
}
