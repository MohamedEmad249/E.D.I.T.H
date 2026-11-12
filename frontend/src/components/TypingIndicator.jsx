import { motion } from 'framer-motion'
import Icon from './Icon.jsx'

const dotVariants = {
  animate: (i) => ({
    y: [0, -5, 0],
    opacity: [0.4, 1, 0.4],
    transition: {
      duration: 1.1,
      repeat: Infinity,
      delay: i * 0.18,
      ease: 'easeInOut',
    },
  }),
}

export default function TypingIndicator() {
  return (
    <motion.div
      className="msg ai"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      role="status"
      aria-label="E.D.I.T.H is thinking"
    >
      <span className="avatar"><Icon name="sparkle" size={15} /></span>
      <div className="typing-indicator">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="typing-dot"
            custom={i}
            variants={dotVariants}
            animate="animate"
          />
        ))}
      </div>
    </motion.div>
  )
}
