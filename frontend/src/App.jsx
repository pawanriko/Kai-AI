import { useCallback, useEffect, useRef, useState } from 'react'

import {
  deleteConversation,
  getConversation,
  getMe,
  listConversations,
  listModels,
  logout as apiLogout,
  sendChat,
  sendChatStream,
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

  // Phase 2.3 (F2): stream chunks arrive per token, and applying
  // each one as its own setState re-renders the transcript per
  // token. Collect chunks in a ref and apply them once per animation
  // frame instead — the bubble still grows live, but at most ~60
  // state updates a second. flushChunks is safe to call from the
  // frame callback or synchronously (it cancels any pending frame);
  // the synchronous call matters when the tab is hidden, where
  // requestAnimationFrame never fires, and at the end of a stream,
  // so the final text is never left sitting in the ref.
  const pendingChunkRef = useRef('')
  const chunkRafRef = useRef(0)

  const flushChunks = useCallback(() => {
    if (chunkRafRef.current) {
      cancelAnimationFrame(chunkRafRef.current)
      chunkRafRef.current = 0
    }
    const text = pendingChunkRef.current
    if (!text) return
    pendingChunkRef.current = ''
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.role === 'assistant') {
        const next = [...prev]
        next[next.length - 1] = { ...last, content: last.content + text }
        return next
      }
      return [...prev, { role: 'assistant', content: text, trace: [] }]
    })
  }, [])

  const queueChunk = useCallback(
    (chunk) => {
      pendingChunkRef.current += chunk
      if (!chunkRafRef.current) {
        chunkRafRef.current = requestAnimationFrame(flushChunks)
      }
    },
    [flushChunks]
  )

  // Discard queued chunks without applying them. Used when the
  // stream failed before the server saved anything: a frame still
  // pending when the error lands must not resurrect the partial
  // bubble the error path just dropped — the transcript must never
  // show a reply the server did not save.
  const discardChunks = useCallback(() => {
    if (chunkRafRef.current) {
      cancelAnimationFrame(chunkRafRef.current)
      chunkRafRef.current = 0
    }
    pendingChunkRef.current = ''
  }, [])

  useEffect(
    () => () => cancelAnimationFrame(chunkRafRef.current),
    []
  )

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
      if (!agent && !coding) {
        // Streaming path (Phase 2): the assistant bubble appears with
        // the first chunk and grows as the reply streams in. Agent
        // and coding modes keep the atomic /api/chat/ path below,
        // because their step traces arrive with the finished reply.
        const done = await sendChatStream(text, activeId, model, queueChunk)
        // Phase 2.3: apply any chunk still waiting for its frame
        // before marking the reply complete — a hidden tab never
        // fires requestAnimationFrame, so without this the final
        // words could sit in the ref after the stream ended.
        flushChunks()
        setActiveId(done.conversation_id)
      } else {
        const data = await sendChat(text, activeId, model, agent, coding, coding)
        setActiveId(data.conversation_id)
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: data.reply, trace: data.trace || [] },
        ])
      }
      refreshConversations()
    } catch (err) {
      if (sessionExpired(err)) {
        // The login screen replaces the chat; a pending frame must
        // not re-add a bubble to the cleared transcript.
        discardChunks()
        return
      }
      if (err.interrupted) {
        // Phase 2.1: the provider died mid-reply and the server
        // saved the partial text flagged incomplete. Keep the bubble
        // and label it — dropping it would hide a message the saved
        // transcript actually contains, and keeping it unlabelled
        // would fake a finished answer. Flush first (Phase 2.3) so
        // the bubble shows the full saved partial, not just what
        // happened to reach a frame before the failure.
        flushChunks()
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (!last || last.role !== 'assistant') return prev
          const next = [...prev]
          next[next.length - 1] = { ...last, incomplete: true }
          return next
        })
        if (err.conversationId) setActiveId(err.conversationId)
        refreshConversations()
        setError(
          '⚠️ Response interrupted — the partial reply above is saved ' +
            'and marked incomplete. Ask again to retry.'
        )
        return
      }
      // Any other stream failure (transport drop, missing done
      // event, pre-stream error): the server saved nothing, so drop
      // the partial bubble — the transcript must never show a reply
      // the server did not save. Discard first (Phase 2.3): a frame
      // still pending when the error landed would otherwise flush
      // after the drop and resurrect the bubble.
      discardChunks()
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        return last && last.role === 'assistant' ? prev.slice(0, -1) : prev
      })
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
            <MessageList
              messages={messages}
              sending={
                sending &&
                messages[messages.length - 1]?.role !== 'assistant'
              }
            />
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
