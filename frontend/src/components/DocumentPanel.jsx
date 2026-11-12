import { useCallback, useEffect, useRef, useState } from 'react'
import { listDocuments, uploadDocument, deleteDocument, cancelUpload } from '../api.js'
import Icon from './Icon.jsx'

const EXCLUDED_KEY = 'edith-excluded-docs'

// We remember which files are switched OFF, so a newly uploaded file starts switched on.
function loadExcluded() {
  try {
    const v = JSON.parse(localStorage.getItem(EXCLUDED_KEY))
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

const newId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())

/**
 * Lists the uploaded PDFs (newest first). Each has a checkbox: only ticked files
 * are used for answers. Reports {total, selected: [filenames]} through onDocsChange.
 */
export default function DocumentPanel({ onToast, onDocsChange, disabled }) {
  const [docs, setDocs] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [excluded, setExcluded] = useState(loadExcluded)
  const [busy, setBusy] = useState(null) // 'upload' | filename being deleted | null
  const fileRef = useRef(null)
  const uploadRef = useRef(null) // {id, controller, cancelled} of the running upload

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments())
      setLoaded(true)
    } catch {
      /* backend may still be starting; the list stays as it was */
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Tell the app which files answers should use, and remember the choice.
  useEffect(() => {
    localStorage.setItem(EXCLUDED_KEY, JSON.stringify(excluded))
    // Until the list has loaded we report nothing, so the app searches all files
    // instead of wrongly sending "no files selected".
    if (!loaded) return
    const names = docs.map((d) => d.filename)
    onDocsChange?.({ total: names.length, selected: names.filter((n) => !excluded.includes(n)) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs, excluded, loaded])

  function toggle(filename) {
    setExcluded((prev) =>
      prev.includes(filename) ? prev.filter((n) => n !== filename) : [...prev, filename],
    )
  }

  async function handleFiles(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = '' // allow picking the same file again
    setBusy('upload')
    for (const file of files) {
      const job = { id: newId(), controller: new AbortController(), cancelled: false }
      uploadRef.current = job
      try {
        const r = await uploadDocument(file, { uploadId: job.id, signal: job.controller.signal })
        onToast(`Added ${r.filename} (${r.chunks} sections)`)
      } catch (err) {
        if (job.cancelled) {
          onToast('Upload cancelled')
          break // also skip any remaining files
        }
        onToast(`Upload failed: ${err.message}`)
      }
    }
    uploadRef.current = null
    setBusy(null)
    refresh()
  }

  async function handleCancelUpload() {
    const job = uploadRef.current
    if (!job) return
    job.cancelled = true
    await cancelUpload(job.id) // the server drops what it had read so far
    job.controller.abort()
  }

  async function handleDelete(filename) {
    if (!window.confirm(`Remove "${filename}" from your documents?`)) return
    setBusy(filename)
    try {
      await deleteDocument(filename)
      setExcluded((prev) => prev.filter((n) => n !== filename))
    } catch (err) {
      onToast(`Could not remove it: ${err.message}`)
    }
    setBusy(null)
    refresh()
  }

  const locked = busy !== null || disabled
  const uploading = busy === 'upload'

  return (
    <div className="doc-panel">
      <div className="sidebar-label">Documents</div>

      <div className="doc-list">
        {docs.length === 0 && <div className="session-empty">No documents yet</div>}
        {docs.map((d) => {
          const on = !excluded.includes(d.filename)
          const label = d.filename.replace(/\.pdf$/i, '')
          return (
            <div
              className={`doc-item ${on ? '' : 'off'}`}
              key={d.filename}
              title={`${d.filename} — ${d.pages} pages${on ? '' : ' (not used for answers)'}`}
            >
              <label className="doc-check">
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggle(d.filename)}
                  aria-label={`Use ${label} for answers`}
                />
                <span className="doc-text">
                  <span className="doc-name">{label}</span>
                  <span className="doc-pages">{d.pages} {d.pages === 1 ? 'page' : 'pages'}</span>
                </span>
              </label>
              <button
                className="icon-btn"
                onClick={() => handleDelete(d.filename)}
                disabled={locked}
                aria-label={`Remove ${d.filename}`}
                title="Remove"
              >
                <Icon name="trash" size={14} />
              </button>
            </div>
          )
        })}
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        onChange={handleFiles}
      />
      {uploading ? (
        <button className="btn-upload uploading" onClick={handleCancelUpload} title="Stop reading this PDF">
          <Icon name="stop" size={12} /> Reading PDF… Cancel
        </button>
      ) : (
        <button className="btn-upload" onClick={() => fileRef.current?.click()} disabled={locked}>
          <Icon name="upload" size={14} /> Upload PDF
        </button>
      )}
    </div>
  )
}
