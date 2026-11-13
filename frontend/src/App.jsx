import { useCallback, useEffect, useRef, useState } from 'react'

import {
  deleteConversation,
  exportReport,
  getConversation,
  getMe,
  listConversations,
  listModels,
  logout as apiLogout,
  requestPlan,
  sendChat,
  sendChatStream,
} from './api'
import ChatInput from './components/ChatInput'
import { ChevronRightIcon } from './components/icons'
import Login from './components/Login'
import MemoryPanel from './components/MemoryPanel'
import MessageList from './components/MessageList'
import PlanReview from './components/PlanReview'
import Sidebar from './components/Sidebar'
import UsagePanel from './components/UsagePanel'
import AutomationPanel from './components/AutomationPanel'

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
  // Phase 6: plan-then-execute + tool bundles. `pendingPlan` holds
  // a proposed plan the user has not approved yet — no message has
  // been sent while it is set.
  const [planFirst, setPlanFirst] = useState(false)
  const [bundle, setBundle] = useState('all')
  const [pendingPlan, setPendingPlan] = useState(null)
  // Phase 7 (Stage A): one voice language for speech input and
  // read-aloud, shared by the composer and the transcript.
  const [voiceLang, setVoiceLang] = useState('en-IN')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  // Sessions panel: collapsible — the chevron slides the sidebar
  // away so the chat takes the full width. The choice persists in
  // localStorage; a missing or blocked store just means "open".
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try {
      return window.localStorage.getItem('kai-sidebar-open') !== 'false'
    } catch {
      return true
    }
  })

  function toggleSidebar(open) {
    setSidebarOpen(open)
    try {
      window.localStorage.setItem('kai-sidebar-open', String(open))
    } catch {
      // Private mode etc. — the panel still toggles this session.
    }
  }

  // Phase 2.3 (F2) + paced reveal: stream chunks arrive per token,
  // and applying each one as its own setState re-renders the
  // transcript per token. Collect chunks in a ref and apply them
  // once per animation frame instead. But frames alone do not make
  // output LOOK smooth: free providers send tokens in bursts
  // (nothing for 300ms, then 200 characters at once), so a frame
  // that dumps its whole backlog still jumps. Each frame therefore
  // reveals only a paced slice — at least 30 characters, or a sixth
  // of the backlog when it is large — and re-schedules while text
  // remains. Small backlogs (the common case) still land in one
  // frame with no added latency; bursts drain over ~6 frames
  // (~100ms) as a steady flow instead of a jump. flushChunks
  // bypasses the cap: at stream end (or on interrupt) every
  // remaining character lands immediately, so the final text is
  // never left sitting in the ref — including when the tab is
  // hidden, where requestAnimationFrame never fires.
  const pendingChunkRef = useRef('')
  const chunkRafRef = useRef(0)

  const appendToAssistant = useCallback((text) => {
    if (!text) return
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

  const revealStep = useCallback(() => {
    chunkRafRef.current = 0
    const pending = pendingChunkRef.current
    if (!pending) return
    const cap = Math.max(30, Math.ceil(pending.length / 6))
    pendingChunkRef.current = pending.slice(cap)
    appendToAssistant(pending.slice(0, cap))
    if (pendingChunkRef.current) {
      chunkRafRef.current = requestAnimationFrame(revealStep)
    }
  }, [appendToAssistant])

  const flushChunks = useCallback(() => {
    if (chunkRafRef.current) {
      cancelAnimationFrame(chunkRafRef.current)
      chunkRafRef.current = 0
    }
    const text = pendingChunkRef.current
    pendingChunkRef.current = ''
    appendToAssistant(text)
  }, [appendToAssistant])

  const queueChunk = useCallback(
    (chunk) => {
      pendingChunkRef.current += chunk
      if (!chunkRafRef.current) {
        chunkRafRef.current = requestAnimationFrame(revealStep)
      }
    },
    [revealStep]
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

  // Phase 5: download the open conversation as a Markdown research
  // report — sources come from the stored agent traces, so a report
  // only ever cites pages KAI actually used.
  async function downloadReport() {
    if (!activeId) return
    try {
      const blob = await exportReport(activeId)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `kai-research-${activeId}.md`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      if (!sessionExpired(err)) {
        setError('Could not download the report.')
      }
    }
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

  // Phase 6: approving a plan sends the original message with the
  // plan attached — the server executes only approved plans.
  // Cancelling sends nothing; the message was never shown.
  function approvePlan() {
    const pending = pendingPlan
    if (!pending) return
    setPendingPlan(null)
    handleSend(pending.text, {
      plan: pending.plan.steps,
      plan_approved: true,
    })
  }

  function cancelPlan() {
    setPendingPlan(null)
  }

  async function handleSend(text, extra = null) {
    // Phase 6: plan-first mode asks for a plan BEFORE anything is
    // sent — the user's message is not even shown optimistically
    // until the plan is approved, so cancelling leaves no phantom
    // message behind. `extra` (set by approvePlan) skips planning.
    if (agent && planFirst && !extra) {
      setError('')
      setSending(true)
      try {
        const data = await requestPlan(
          text,
          activeId,
          model,
          bundle === 'all' ? null : bundle
        )
        setPendingPlan({ plan: data.plan, text })
      } catch (err) {
        if (!sessionExpired(err)) {
          setError('Could not make a plan — is Django running?')
        }
      } finally {
        setSending(false)
      }
      return
    }
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
        const data = await sendChat(
          text,
          activeId,
          model,
          agent,
          coding,
          coding,
          {
            ...(bundle !== 'all' ? { bundle } : {}),
            ...(extra || {}),
          }
        )
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
    <div className={sidebarOpen ? 'layout' : 'layout sidebar-collapsed'}>
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
        onCollapse={() => toggleSidebar(false)}
      />
      <main className="main">
        {!sidebarOpen && (
          <button
            className="expand-btn icon-btn"
            onClick={() => toggleSidebar(true)}
            aria-label="Open sessions panel"
            title="Open sessions panel"
          >
            <ChevronRightIcon />
          </button>
        )}
        {view === 'memory' ? (
          <MemoryPanel />
        ) : view === 'usage' ? (
          <UsagePanel />
        ) : view === 'automation' ? (
          <AutomationPanel />
        ) : (
          <>
            {error && <div className="error-box">{error}</div>}
            {pendingPlan && (
              <PlanReview
                plan={pendingPlan.plan}
                message={pendingPlan.text}
                onApprove={approvePlan}
                onCancel={cancelPlan}
              />
            )}
            {activeId && (
              <div className="report-row">
                <button type="button" onClick={downloadReport}>
                  Download research report
                </button>
              </div>
            )}
            <MessageList
              messages={messages}
              sending={
                sending &&
                messages[messages.length - 1]?.role !== 'assistant'
              }
              voiceLang={voiceLang}
              ttsConfigured={auth.tts_configured}
            />
            <ChatInput
              providers={providers}
              model={model}
              onModel={setModel}
              agent={agent}
              onAgent={setAgent}
              coding={coding}
              onCoding={handleCoding}
              planFirst={planFirst}
              onPlanFirst={setPlanFirst}
              bundle={bundle}
              onBundle={setBundle}
              voiceLang={voiceLang}
              onVoiceLang={setVoiceLang}
              onSend={handleSend}
              sending={sending}
            />
          </>
        )}
      </main>
    </div>
  )
}
