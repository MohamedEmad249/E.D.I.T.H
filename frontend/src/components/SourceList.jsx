import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Icon from './Icon.jsx'

const VISIBLE = 4 // chips shown before "+N more"

// "data\\L5_ Correlation.pdf" → "L5_ Correlation"
function fileLabel(source) {
  const name = String(source || 'unknown').split(/[\\/]/).pop()
  return name.replace(/\.pdf$/i, '')
}

// The backend stores 0-based page numbers; people count from 1.
function pageLabel(page) {
  return typeof page === 'number' ? `p. ${page + 1}` : 'p. ?'
}

function truncate(str, n) {
  if (!str) return ''
  return str.length > n ? str.slice(0, n) + '…' : str
}

export default function SourceList({ sources }) {
  const [openIdx, setOpenIdx] = useState(null) // which chip's preview is shown
  const [showAll, setShowAll] = useState(false)

  if (!sources || sources.length === 0) return null

  const shown = showAll ? sources : sources.slice(0, VISIBLE)
  const hidden = sources.length - shown.length
  const open = openIdx !== null ? sources[openIdx] : null

  return (
    <div className="sources">
      <div className="sources-row">
        <span className="sources-label">Sources</span>
        {shown.map((s, i) => (
          <button
            key={i}
            className={`source-chip ${openIdx === i ? 'open' : ''}`}
            onClick={() => setOpenIdx(openIdx === i ? null : i)}
            aria-expanded={openIdx === i}
            title="Show the excerpt"
          >
            <Icon name="file" size={12} />
            {truncate(fileLabel(s.source), 26)} · {pageLabel(s.page)}
          </button>
        ))}
        {hidden > 0 && (
          <button className="source-chip source-more" onClick={() => setShowAll(true)}>
            +{hidden} more
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key={openIdx}
            className="source-preview"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
          >
            <div className="source-preview-title">
              {fileLabel(open.source)} · {pageLabel(open.page)}
            </div>
            {truncate(open.content, 280)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
