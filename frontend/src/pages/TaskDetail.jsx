/* E1: Task detail slide-over — everything about ONE task in one panel:
   header chips, checklist, sub-tasks, comments, updates feed, attachments,
   plus the action row and the per-task AI summary (E3). */
import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { CompleteModal, ProgressModal, RequestChangeModal } from './TaskExtras'
import { fmtEffort, relDue } from './Tasks'

const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : null

export default function TaskDetailPanel({ taskId, user, team, settings, onClose, onChanged }) {
  const [t, setT] = useState(null)
  const [feed, setFeed] = useState([])
  const [files, setFiles] = useState([])
  const [comment, setComment] = useState('')
  const [newCheck, setNewCheck] = useState('')
  const [summary, setSummary] = useState(null)
  const [modal, setModal] = useState(null)       // progress | complete | request
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api(`/api/tasks/${taskId}/`).then(setT).catch(e => setErr(e.message))
    api(`/api/tasks/${taskId}/activity/`).then(setFeed).catch(() => {})
    api(`/api/tasks/${taskId}/files/`).then(setFiles).catch(() => {})
  }, [taskId])
  useEffect(() => { load() }, [load])

  const post = async (path, body, method = 'POST') => {
    setErr('')
    try {
      const res = await api(`/api/tasks/${taskId}/${path}`, { method, body })
      load(); onChanged?.()
      return res
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const isAssignee = t?.assigned_to === user.id
  const canAct = t && t.status !== 'done'
  const doneChecks = t?.checklist?.filter(c => c.done).length ?? 0

  return (
    <div className="modal" style={{ placeItems: 'stretch end', display: 'flex', justifyContent: 'flex-end' }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-card" style={{
        width: 480, maxWidth: '96vw', height: '100vh', maxHeight: '100vh',
        borderRadius: '16px 0 0 16px', overflowY: 'auto',
      }}>
        {!t && <p className="muted">Loading…</p>}
        {t && (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span className="t-code" style={{ fontSize: 13 }}>{t.code}</span>
              <h2 style={{ margin: 0, flex: 1 }}>{t.title}</h2>
              <button className="btn btn-sm" onClick={onClose}>✕</button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
              <span className={`q-pill q-${t.status === 'done' ? 'approved' : 'under_review'}`}>{t.status_display}</span>
              {t.category && <span className="ai-chip">{t.category}</span>}
              {t.priority !== 'normal' && <span className={`prio prio-${t.priority}`}>{t.priority_display}</span>}
              {t.effort_minutes && <span className="ai-chip">⏱ {fmtEffort(t.effort_minutes)}</span>}
              {t.actual_minutes && <span className="ai-chip">⏲ {fmtEffort(t.actual_minutes)} spent</span>}
              {t.progress_percent != null && t.status !== 'done' && <span className="ai-chip">▰ {t.progress_percent}%</span>}
              {t.parent_code && <span className="ai-chip">↑ sub-task of {t.parent_code}</span>}
            </div>
            {t.description && <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{t.description}</p>}
            <p className="small muted">
              Assigned to <strong>{t.assigned_to_detail?.name}</strong>
              {t.created_by_detail && <> by <strong>{t.created_by_detail.name}</strong></>}
              {t.due_at && <> · due {fmtDT(t.due_at)} ({relDue(t.due_at)})</>}
              {t.completed_at && <> · completed {fmtDT(t.completed_at)}</>}
              {t.lead_name && <> · lead: {t.lead_name}</>}
            </p>

            {/* action row */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '8px 0' }}>
              {canAct && isAssignee && (
                <>
                  <button className="btn btn-sm" onClick={() => setModal('progress')}>+ Status update</button>
                  <button className="btn btn-sm btn-primary" onClick={() => setModal('complete')}>Complete</button>
                </>
              )}
              {canAct && <button className="btn btn-sm" onClick={() => setModal('request')}>
                {user.capabilities?.includes('tasks.view_all') ? 'Edit' : 'Request change'}</button>}
              <button className="btn btn-sm" title="AI summary (works without AI too)"
                onClick={async () => {
                  const r = await post('summarize/', {})
                  if (r) setSummary(r)
                }}>✨ Summarize</button>
            </div>
            {summary && (
              <div className="small" style={{ padding: 10, background: 'var(--bg)', borderRadius: 8 }}>
                {summary.summary} <span className="muted">({summary.provider})</span>
              </div>
            )}
            {err && <div className="err">{err}</div>}

            {/* checklist */}
            <h3 style={{ margin: '14px 0 6px' }}>
              Checklist {t.checklist.length > 0 && <span className="muted small">{doneChecks}/{t.checklist.length}</span>}
            </h3>
            {t.checklist.map(c => (
              <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '3px 0' }}>
                <input type="checkbox" checked={c.done} onChange={() => post(`check/${c.id}/`, {})} />
                <span className="small" style={{ flex: 1, textDecoration: c.done ? 'line-through' : 'none' }}>{c.text}</span>
                <button className="btn btn-sm" style={{ padding: '0 6px' }}
                  onClick={() => post(`check/${c.id}/?delete=true`, {})}>✕</button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <input placeholder="Add a step…" value={newCheck} style={{ flex: 1 }}
                onChange={e => setNewCheck(e.target.value)}
                onKeyDown={async e => {
                  if (e.key === 'Enter' && newCheck.trim()) {
                    e.preventDefault()
                    await post('add_check/', { text: newCheck.trim() }); setNewCheck('')
                  }
                }} />
              <button className="btn btn-sm" disabled={!newCheck.trim()}
                onClick={async () => { await post('add_check/', { text: newCheck.trim() }); setNewCheck('') }}>Add</button>
            </div>

            {/* sub-tasks */}
            {t.subtasks.length > 0 && (
              <>
                <h3 style={{ margin: '14px 0 6px' }}>Sub-tasks</h3>
                {t.subtasks.map(s => (
                  <div key={s.id} className="small" style={{ padding: '3px 0' }}>
                    <span className="t-code">{s.code}</span> {s.title}
                    <span className="muted"> — {s.assignee} · {s.status}</span>
                  </div>
                ))}
              </>
            )}

            {/* attachments */}
            {files.length > 0 && (
              <>
                <h3 style={{ margin: '14px 0 6px' }}>Attachments</h3>
                {files.map(f => (
                  <div key={f.id} className="small" style={{ padding: '2px 0' }}>
                    📎 <a href={f.url} target="_blank" rel="noreferrer">{f.filename}</a>
                    <span className="muted"> · {f.uploaded_by?.name}</span>
                  </div>
                ))}
              </>
            )}

            {/* comments + updates feed */}
            <h3 style={{ margin: '14px 0 6px' }}>Comments &amp; updates</h3>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <input placeholder="Write a comment…" value={comment} style={{ flex: 1 }}
                onChange={e => setComment(e.target.value)}
                onKeyDown={async e => {
                  if (e.key === 'Enter' && comment.trim()) {
                    e.preventDefault()
                    await post('comment/', { text: comment.trim() }); setComment('')
                  }
                }} />
              <button className="btn btn-sm btn-primary" disabled={!comment.trim()}
                onClick={async () => { await post('comment/', { text: comment.trim() }); setComment('') }}>Send</button>
            </div>
            {feed.map(a => (
              <div key={a.id} className="small" style={{
                padding: '5px 8px', marginBottom: 4, borderRadius: 6,
                background: a.kind === 'comment' ? 'rgba(13,122,95,.08)' : 'transparent',
                borderLeft: a.kind === 'comment' ? '3px solid var(--accent)' : '3px solid var(--line)',
              }}>
                {a.kind === 'comment' && '💬 '}<strong>{a.actor?.name || 'System'}</strong>
                <span className="muted"> · {fmtDT(a.created_at)}</span>
                <div>{a.text}</div>
              </div>
            ))}
          </>
        )}
      </div>

      {modal === 'progress' && t && (
        <ProgressModal task={t} onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); onChanged?.() }} />
      )}
      {modal === 'complete' && t && (
        <CompleteModal task={t} settings={settings} onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); onChanged?.() }} />
      )}
      {modal === 'request' && t && (
        <RequestChangeModal task={t} team={team} user={user}
          isAdmin={user.capabilities?.includes('tasks.view_all')}
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); onChanged?.() }} />
      )}
    </div>
  )
}
