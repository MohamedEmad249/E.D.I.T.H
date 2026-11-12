const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

async function errorFrom(res) {
  let detail = `HTTP ${res.status}`
  try {
    const err = await res.json()
    if (typeof err.detail === 'string') detail = err.detail
  } catch {
    /* no-op: body wasn't JSON */
  }
  return new Error(detail)
}

export async function fetchSessions() {
  const res = await fetch(`${API_BASE}/sessions`)
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()).sessions // [{session_id, title, turns}], newest first
}

export async function listDocuments() {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()).documents // [{filename, chunks, pages}]
}

export async function uploadDocument(file, { uploadId, signal } = {}) {
  const form = new FormData()
  form.append('file', file)
  const query = uploadId ? `?upload_id=${encodeURIComponent(uploadId)}` : ''
  const res = await fetch(`${API_BASE}/documents${query}`, { method: 'POST', body: form, signal })
  if (!res.ok) throw await errorFrom(res)
  return res.json()
}

/** Ask the server to stop reading an upload. Never throws. */
export async function cancelUpload(uploadId) {
  try {
    await fetch(`${API_BASE}/documents/uploads/${encodeURIComponent(uploadId)}`, { method: 'DELETE' })
  } catch {
    /* best-effort */
  }
}

export async function deleteDocument(filename) {
  const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(filename)}`, { method: 'DELETE' })
  if (!res.ok) throw await errorFrom(res)
  return res.json()
}

export async function sendChatMessage(question, sessionId) {
  const body = { question }
  if (sessionId) body.session_id = sessionId

  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const err = await res.json()
      detail = err.detail || detail
    } catch {
      /* no-op: body wasn't JSON */
    }
    throw new Error(detail)
  }

  return res.json()
}

/**
 * Streaming chat. The server sends newline-delimited JSON events:
 *   {type:'meta', session_id, sources} → {type:'token', text}… → {type:'done'}
 * or {type:'error', detail}. Callbacks: onMeta(meta), onToken(text).
 */
export async function streamChatMessage(
  question,
  sessionId,
  { onMeta, onToken, sources, requestId, signal } = {},
) {
  const body = { question }
  if (sessionId) body.session_id = sessionId
  if (sources) body.sources = sources // file names to answer from; omitted = all documents
  if (requestId) body.request_id = requestId // lets stopChat() stop this answer

  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const err = await res.json()
      detail = err.detail || detail
    } catch {
      /* no-op: body wasn't JSON */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  function handle(line) {
    if (!line.trim()) return
    const ev = JSON.parse(line)
    if (ev.type === 'meta') onMeta?.(ev)
    else if (ev.type === 'token') onToken?.(ev.text)
    else if (ev.type === 'error') throw new Error(ev.detail)
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() // keep the incomplete trailing line for the next chunk
    lines.forEach(handle)
  }
  handle(buffer)
}

/** Ask the server to stop a running answer. Never throws: stopping is best-effort. */
export async function stopChat(requestId) {
  try {
    await fetch(`${API_BASE}/chat/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
    })
  } catch {
    /* the fetch abort that follows stops the client side anyway */
  }
}

export async function renameSession(sessionId, title) {
  const res = await fetch(`${API_BASE}/session/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw await errorFrom(res)
  return res.json() // {session_id, title}
}

export async function fetchSessionHistory(sessionId) {
  const res = await fetch(`${API_BASE}/session/${sessionId}/history`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function clearSession(sessionId) {
  const res = await fetch(`${API_BASE}/session`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
