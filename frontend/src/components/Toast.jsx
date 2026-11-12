import { AnimatePresence, motion } from 'framer-motion'

export default function Toast({ message }) {
  return (
    <AnimatePresence>
      {message && (
        <motion.div
          className="toast"
          initial={{ opacity: 0, y: 20, x: '-50%' }}
          animate={{ opacity: 1, y: 0, x: '-50%' }}
          exit={{ opacity: 0, y: 20, x: '-50%' }}
          transition={{ duration: 0.25 }}
        >
          {message}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
