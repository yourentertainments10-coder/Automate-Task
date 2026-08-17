import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

const fmtDT = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const STATUSES = [
  ['new', 'New'], ['under_review', 'Under Review'], ['approved', 'Approved'],
  ['rejected', 'Rejected'], ['implemented', 'Implemented'],
]

export default function Ideas() {
  const { user, can } = useAuth()
  const canReview = can('tasks.assign')
  const [scope, setScope] = useState('shared')
  const [rows, setRows] = useState(null)
  const [groups, setGroups] = useState([])
  const [fStatus, setFStatus] = useState('')
  const [q, setQ] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const p = new URLSearchParams({ page_size: '100', scope })
    if (fStatus) p.set('status', fStatus)
    if (q.trim()) p.set('search', q.trim())
    api(`/api/ideas/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [scope, fStatus, q])
  useEffect(() => { load() }, [load])
  useEffect(() => { api('/api/groups/').then(setGroups).catch(() => {}) }, [])

  const vote = async (i) => {
    await api(`/api/ideas/${i.id}/vote/`, { method: 'POST' }).catch(() => {})
    load()
  }

  const setStatus = async (i, status) => {
    setErr('')
    try { await api(`/api/ideas/${i.id}/`, { method: 'PATCH', body: { status } }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const remove = async (i) => {
    setErr('')
    try { await api(`/api/ideas/${i.id}/`, { method: 'DELETE' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading ideas…</div>

  return (
    <div style={{ maxWidth: 760 }}>
      <div className="page-head">
        <h1>Idea Board</h1>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ New idea</button>
      </div>
      <div className="filters">
        <div className="seg">
          {[['shared', 'Shared'], ['my', 'My Ideas'], ['group', 'Group Ideas']].map(([v, l]) => (
            <button key={v} className={'seg-btn' + (scope === v ? ' on' : '')} onClick={() => setScope(v)}>{l}</button>
          ))}
        </div>
        <select value={fStatus} onChange={e => setFStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input type="search" placeholder="Search ideas…" value={q} onChange={e => setQ(e.target.value)} />
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No ideas here yet — share the first one.</p>}
      <div className="task-list">
        {rows.map(i => (
          <div className="task-row" key={i.id} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <button className={'vote-btn' + (i.voted ? ' on' : '')} onClick={() => vote(i)} title="Vote">
                ▲<span>{i.vote_count}</span>
              </button>
              <div className="task-main" style={{ cursor: 'pointer' }} onClick={() => setOpenId(openId === i.id ? null : i.id)}>
                <div className="task-title">
                  {i.title}
                  {i.category && <span className="ai-chip">{i.category}</span>}
                  {i.group_name && <span className="ai-chip">👥 {i.group_name}</span>}
                  <span className={`q-pill q-${i.status}`}>{i.status_display}</span>
                </div>
                {i.description && <div className="small muted">{i.description}</div>}
                <div className="when">{i.author_detail?.name} · {fmtDT(i.created_at)} · 💬 {i.comment_count}</div>
              </div>
              <span style={{ display: 'flex', gap: 6 }}>
                {canReview && (
                  <select value={i.status} onChange={e => setStatus(i, e.target.value)}>
                    {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                )}
                {(i.author_detail?.id === user.id || canReview) && (
                  <button className="btn btn-sm" onClick={() => remove(i)}>✕</button>
                )}
              </span>
            </div>
            {openId === i.id && <Comments idea={i} />}
          </div>
        ))}
      </div>
      {showAdd && (
        <IdeaModal groups={groups} onClose={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load() }} />
      )}
    </div>
  )
}

function Comments({ idea }) {
  const [rows, setRows] = useState(null)
  const [body, setBody] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api(`/api/ideas/${idea.id}/comments/`).then(setRows).catch(e => setErr(e.message))
  }, [idea.id])
  useEffect(() => { load() }, [load])

  const add = async () => {
    if (!body.trim()) return
    setErr('')
    try {
      await api(`/api/ideas/${idea.id}/comments/`, { method: 'POST', body: { body: body.trim() } })
      setBody(''); load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (!rows) return <div className="muted small" style={{ padding: '8px 0 0 40px' }}>Loading comments…</div>
  return (
    <div style={{ padding: '10px 0 0 40px' }}>
      {err && <div className="err">{err}</div>}
      {rows.map(c => (
        <div key={c.id} className="note" style={{ marginBottom: 6 }}>
          {c.body}
          <div className="when">{c.author?.name} · {fmtDT(c.created_at)}</div>
        </div>
      ))}
      <div className="note-input">
        <textarea placeholder="Add a comment…" value={body} onChange={e => setBody(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); add() } }} />
        <button className="btn" disabled={!body.trim()} onClick={add}>Post</button>
      </div>
    </div>
  )
}

function IdeaModal({ groups, onClose, onSaved }) {
  const [f, setF] = useState({ title: '', description: '', category: '', group: '', priority: 'normal' })
  const [err, setErr] = useState('')
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    const body = { ...f, group: f.group ? Number(f.group) : null }
    try { await api('/api/ideas/', { method: 'POST', body }); onSaved() }
    catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>New idea</h2>
        <div className="form-grid">
          <div className="wide"><label>Title *</label><input value={f.title} onChange={set('title')} autoFocus /></div>
          <div className="wide"><label>Description</label><input value={f.description} onChange={set('description')} /></div>
          <div><label>Category</label><input value={f.category} onChange={set('category')} placeholder="e.g. Process, Product" /></div>
          <div>
            <label>Board</label>
            <select value={f.group} onChange={set('group')}>
              <option value="">Shared (company-wide)</option>
              {groups.map(g => <option key={g.id} value={g.id}>Group: {g.name}</option>)}
            </select>
          </div>
          <div>
            <label>Priority</label>
            <select value={f.priority} onChange={set('priority')}>
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={!f.title.trim()}>Post idea</button>
        </div>
      </form>
    </div>
  )
}
