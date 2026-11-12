import { useState } from 'react'
import { motion } from 'framer-motion'
import DocumentPanel from './DocumentPanel.jsx'
import Icon from './Icon.jsx'

export default function Sidebar({
  sessions, activeId, onNew, onSwitch, onDelete, onRename, onToast, onDocsChange, busy, collapsed,
}) {
  const ids = Object.keys(sessions)
  const [editingId, setEditingId] = useState(null)
  const [draft, setDraft] = useState('')

  function startRename(id) {
    setEditingId(id)
    setDraft(sessions[id] || '')
  }

  function finishRename(save) {
    const id = editingId
    const title = draft.trim()
    setEditingId(null)
    if (save && id && title && title !== sessions[id]) onRename(id, title)
  }

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`} aria-hidden={collapsed}>
      <div className="sidebar-logo">
        <span className="logo-mark">E</span>
        <span className="logo-text">E.D.I.T.H</span>
      </div>

      <motion.button
        className="btn-new"
        onClick={onNew}
        whileTap={{ scale: 0.97 }}
        transition={{ type: 'spring', stiffness: 400, damping: 20 }}
      >
        <Icon name="plus" size={14} strokeWidth={2.2} />
        New chat
      </motion.button>

      <div className="sidebar-label">Recent</div>

      <div className="session-list">
        {ids.length === 0 && <div className="session-empty">No chats yet</div>}
        {ids.map((id) => (
          <motion.div
            key={id}
            className={`session-item ${id === activeId ? 'active' : ''} ${id === editingId ? 'editing' : ''}`}
            onClick={() => id !== editingId && onSwitch(id)}
            onDoubleClick={() => startRename(id)}
            title={id === editingId ? undefined : sessions[id]}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.2 }}
          >
            <span className="session-dot" />
            {id === editingId ? (
              <input
                className="session-rename"
                value={draft}
                autoFocus
                maxLength={80}
                aria-label="Chat name"
                onChange={(e) => setDraft(e.target.value)}
                onFocus={(e) => e.target.select()}
                onClick={(e) => e.stopPropagation()}
                onBlur={() => finishRename(true)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') finishRename(true)
                  if (e.key === 'Escape') finishRename(false)
                }}
              />
            ) : (
              <>
                <span className="session-label">{sessions[id]}</span>
                <span className="session-actions">
                  <button
                    className="icon-btn"
                    onClick={(e) => {
                      e.stopPropagation() // don't also open the chat
                      startRename(id)
                    }}
                    aria-label="Rename chat"
                    title="Rename"
                  >
                    <Icon name="pencil" size={13} />
                  </button>
                  <button
                    className="icon-btn"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(id)
                    }}
                    disabled={busy}
                    aria-label="Delete chat"
                    title="Delete"
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </span>
              </>
            )}
          </motion.div>
        ))}
      </div>

      <DocumentPanel onToast={onToast} onDocsChange={onDocsChange} disabled={busy} />

      <div className="sidebar-footer">
        <span className="status-dot" />
        Qwen2.5 1.5B · runs locally
      </div>
    </aside>
  )
}
