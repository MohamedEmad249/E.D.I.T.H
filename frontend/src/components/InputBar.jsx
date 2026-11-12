import { useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import Icon from './Icon.jsx'

export default function InputBar({ value, onChange, onSend, onStop, disabled }) {
  const textareaRef = useRef(null)

  // Resize on every value change (typing, sending, clicking a suggestion).
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 180) + 'px'
  }, [value])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  return (
    <div className="input-area">
      <div className="input-wrap">
        <textarea
          ref={textareaRef}
          id="question-input"
          rows={1}
          placeholder="Ask about your documents…"
          aria-label="Your question"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        {disabled ? (
          // While an answer is being written the send button becomes a stop button.
          <motion.button
            className="send-btn stop"
            onClick={onStop}
            whileTap={{ scale: 0.92 }}
            title="Stop"
            aria-label="Stop the answer"
          >
            <span className="stop-square" />
          </motion.button>
        ) : (
          <motion.button
            className="send-btn"
            onClick={onSend}
            disabled={!value.trim()}
            whileTap={{ scale: 0.92 }}
            transition={{ type: 'spring', stiffness: 500, damping: 25 }}
            title="Send"
            aria-label="Send"
          >
            <Icon name="send" size={18} strokeWidth={2.4} />
          </motion.button>
        )}
      </div>
      <div className="input-hint">
        Answers come from your PDFs. A small local model can make mistakes.
      </div>
    </div>
  )
}
