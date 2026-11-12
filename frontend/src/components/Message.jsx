import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import SourceList from './SourceList.jsx'
import Icon from './Icon.jsx'

// The model writes LaTeX as \( … \) and \[ … \]; remark-math reads $$ … $$.
// (Single-$ math is switched off below so prices like "$500" stay plain text.)
function normalizeMath(text) {
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, m) => `\n\n$$\n${m.trim()}\n$$\n\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, m) => `$$${m.trim()}$$`)
}

const bubbleVariants = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
}

export default function Message({ role, content, sources }) {
  const isUser = role === 'user'

  return (
    <motion.div
      className={`msg ${isUser ? 'user' : 'ai'}`}
      variants={bubbleVariants}
      initial="hidden"
      animate="visible"
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
    >
      {isUser ? (
        <div className="bubble">{content}</div>
      ) : (
        <>
          <span className="avatar"><Icon name="sparkle" size={15} /></span>
          <div className="msg-body">
            <div className="msg-name">E.D.I.T.H</div>
            <div className="bubble">
              <ReactMarkdown
                remarkPlugins={[[remarkMath, { singleDollarTextMath: false }]]}
                rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}
              >
                {normalizeMath(content)}
              </ReactMarkdown>
            </div>
            {sources && <SourceList sources={sources} />}
          </div>
        </>
      )}
    </motion.div>
  )
}
