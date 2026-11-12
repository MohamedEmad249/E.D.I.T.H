import { motion } from 'framer-motion'

export default function EmptyState() {
  return (
    <motion.div
      className="empty-state"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.35 }}
    >
      <h1 className="empty-title">What are we studying today?</h1>
      <p className="empty-sub">Ask about your PDFs and get answers with the page they came from.</p>
    </motion.div>
  )
}
