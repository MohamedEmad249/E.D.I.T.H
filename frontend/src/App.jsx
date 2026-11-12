import { useState, useRef, useEffect, useCallback } from 'react'
import { AnimatePresence } from 'framer-motion'
import Sidebar from './components/Sidebar.jsx'
import Message from './components/Message.jsx'
import TypingIndicator from './components/TypingIndicator.jsx'
import EmptyState from './components/EmptyState.jsx'
import InputBar from './components/InputBar.jsx'
import Toast from './components/Toast.jsx'
import Icon from './components/Icon.jsx'
import {
  streamChatMessage, fetchSessionHistory, fetchSessions, clearSession, renameSession, stopChat,
} from './api.js'
import './App.css'

function truncate(str, n) {
  if (!str) return ''
  return str.length > n ? str.slice(0, n) + '…' : str
}

const isMobile = () => window.matchMedia('(max-width: 760px)').matches

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [sessions, setSessions] = useState({})       // { id: firstQuestionLabel }
  const [messages, setMessages] = useState([])        // [{role, content, sources}]
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [toast, setToast] = useState(null)
  // On phones the sidebar is a drawer over the chat, so it starts closed.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(isMobile)
  const [docInfo, setDocInfo] = useState(null) // {total, selected: [filenames]} from the sidebar
  const activeRef = useRef(null) // the answer being written: {requestId, controller, stopped}
  const [theme, setTheme] = useState(() => localStorage.getItem('edith-theme') || 'dark')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('edith-theme', theme)
  }, [theme])

  function toggleTheme() {
    setTheme((t) => (t === 'light' ? 'dark' : 'light'))
  }

  const messagesEndRef = useRef(null)

  const scrollToBottom = useCallback(() => {
    // 'auto' while streaming: smooth scrolling lags behind fast token updates
    messagesEndRef.current?.scrollIntoView({ behavior: isLoading ? 'auto' : 'smooth' })
  }, [isLoading])

  useEffect(() => {
    scrollToBottom()
  }, [messages, isLoading, scrollToBottom])

  function showToast(msg) {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  // Saved conversations survive page reloads and server restarts.
  useEffect(() => {
    fetchSessions()
      .then((list) => {
        const loaded = {}
        list.forEach((s) => { loaded[s.session_id] = s.title }) // already newest first
        // Merge, don't replace: a chat started before this list arrived must stay (and stay first).
        setSessions((prev) => ({ ...prev, ...loaded, ...prev }))
      })
      .catch(() => { /* backend not up yet: the list just stays empty */ })
  }, [])

  async function deleteSession(id) {
    if (isLoading) return
    if (!window.confirm('Delete this conversation?')) return
    try {
      await clearSession(id)
    } catch (err) {
      // 404 = already gone on the server; anything else: keep it and tell the user
      if (!String(err.message).includes('404')) {
        showToast(`Could not delete: ${err.message}`)
        return
      }
    }
    setSessions((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    if (id === sessionId) newSession()
  }

  function newSession() {
    // Leaving a chat while its answer is still being written: stop that answer first.
    if (activeRef.current) {
      activeRef.current.discard = true
      handleStop()
    }
    setSessionId(null)
    setMessages([])
    setInput('')
    if (isMobile()) setSidebarCollapsed(true)
  }

  async function switchSession(id) {
    if (id === sessionId || isLoading) return

    setSessionId(id)
    if (isMobile()) setSidebarCollapsed(true)

    try {
      const data = await fetchSessionHistory(id)

      if (!data.history || data.history.length === 0) {
        setMessages([])
        return
      }

      // Rebuild thread from stored turns: [{role, content}, ...]
      setMessages(data.history.map((turn) => ({
        role: turn.role === 'user' ? 'user' : 'assistant',
        content: turn.content,
        sources: turn.sources?.length ? turn.sources : null,
      })))
    } catch (err) {
      showToast(`Could not load that conversation: ${err.message}`)
      setMessages([])
    }
  }

  async function renameChat(id, title) {
    const previous = sessions[id]
    setSessions((prev) => ({ ...prev, [id]: title })) // show it at once, undo on failure
    try {
      const r = await renameSession(id, title)
      setSessions((prev) => ({ ...prev, [id]: r.title }))
    } catch (err) {
      setSessions((prev) => ({ ...prev, [id]: previous }))
      showToast(`Could not rename: ${err.message}`)
    }
  }

  // Stop the answer being written. The server keeps what was written so far.
  function handleStop() {
    const job = activeRef.current
    if (!job) return
    job.stopped = true
    stopChat(job.requestId).finally(() => job.controller.abort())
  }

  async function handleSend(overrideText) {
    const question = (overrideText ?? input).trim()
    if (!question || isLoading) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setIsLoading(true)

    let sources = null
    let started = false // true once the first token has arrived
    const job = {
      requestId: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random(),
      controller: new AbortController(),
      stopped: false,
    }
    activeRef.current = job

    try {
      await streamChatMessage(question, sessionId, {
        requestId: job.requestId,
        signal: job.controller.signal,
        // Only the ticked files are searched. Unknown yet (list not loaded) → all files.
        sources: docInfo && docInfo.total > 0 ? docInfo.selected : undefined,
        onMeta: (meta) => {
          sources = meta.sources
          if (!sessionId) {
            setSessionId(meta.session_id)
            // newest first
            setSessions((prev) => ({ [meta.session_id]: truncate(question, 60), ...prev }))
          }
        },
        onToken: (text) => {
          if (job.stopped) return // a late token after Stop / New chat: ignore it
          if (!started) {
            started = true
            setMessages((prev) => [...prev, { role: 'assistant', content: text, sources }])
          } else {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last?.role !== 'assistant') return prev // thread was cleared meanwhile
              const next = prev.slice()
              next[next.length - 1] = { ...last, content: last.content + text }
              return next
            })
          }
        },
      })
    } catch (err) {
      if (!job.stopped) showToast(`Error: ${err.message}`)
      // Nothing was shown yet → roll back the user bubble. Otherwise keep the partial answer.
      if (!started && !job.discard) {
        setMessages((prev) => prev.slice(0, -1))
        if (job.stopped) setInput(question) // stopped before any answer: give the question back
      }
    } finally {
      activeRef.current = null
      setIsLoading(false)
    }
  }

  return (
    <div className={`app ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        sessions={sessions}
        activeId={sessionId}
        onNew={newSession}
        onSwitch={switchSession}
        onDelete={deleteSession}
        onRename={renameChat}
        onToast={showToast}
        onDocsChange={setDocInfo}
        busy={isLoading}
        collapsed={sidebarCollapsed}
      />
      {!sidebarCollapsed && (
        // Only visible on phones (CSS): tap outside the drawer to close it.
        <button className="backdrop" aria-label="Close menu" onClick={() => setSidebarCollapsed(true)} />
      )}

      <main className={`main ${messages.length > 0 ? 'has-messages' : ''}`}>
        <div className="workspace-bg" aria-hidden="true" />
        <header className="header">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed((c) => !c)}
            aria-label="Toggle sidebar"
            title="Toggle sidebar"
          >
            <Icon name="menu" size={18} />
          </button>

          <span className="header-title">{(sessionId && sessions[sessionId]) || 'New chat'}</span>
          {docInfo && (
            <span
              className={`header-chip ${docInfo.total > 0 && docInfo.selected.length === 0 ? 'warn' : ''}`}
              title="Files used for answers. Tick or untick them in the sidebar."
            >
              {docInfo.selected.length === docInfo.total
                ? `${docInfo.total} ${docInfo.total === 1 ? 'document' : 'documents'}`
                : `${docInfo.selected.length} of ${docInfo.total} documents`}
            </span>
          )}
          <span className="header-spacer" />

          <button
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label="Toggle dark mode"
            title="Toggle dark mode"
          >
            <Icon name={theme === 'light' ? 'moon' : 'sun'} size={16} />
          </button>
        </header>

        <div className="messages">
          <AnimatePresence mode="wait">
            {messages.length === 0 ? (
              <EmptyState key="empty" />
            ) : (
              <div key="thread" className="thread">
                {messages.map((m, i) => (
                  <Message key={i} role={m.role} content={m.content} sources={m.sources} />
                ))}
                {isLoading && messages[messages.length - 1]?.role === 'user' && <TypingIndicator />}
              </div>
            )}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>

        <InputBar
          value={input}
          onChange={setInput}
          onSend={() => handleSend()}
          onStop={handleStop}
          disabled={isLoading}
        />
      </main>

      <Toast message={toast} />
    </div>
  )
}
