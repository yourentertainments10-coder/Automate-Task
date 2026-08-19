import { useCallback, useEffect, useState } from 'react'
import { api, apiUpload, errorText } from '../api'
import { fmtEffort } from './Tasks'

const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : null
const PRIORITIES = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High'], ['urgent', 'Urgent']]

/* ================= Complete with evidence (B3) ================= */

export function CompleteModal({ task, settings, onClose, onDone }) {
  const [remarks, setRemarks] = useState('')
  const [file, setFile] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const fd = new FormData()
      fd.append('remarks', remarks)
      if (file) fd.append('file', file)
      await apiUpload(`/api/tasks/${task.id}/complete/`, fd)
      onDone()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>Complete {task.code}</h2>
        <p className="muted small">{task.title}</p>
        <div className="form-grid">
          <div className="wide">
            <label>What was done? {settings.require_completion_remarks ? '*' : '(optional)'}</label>
            <textarea rows={3} value={remarks} onChange={e => setRemarks(e.target.value)}
              style={{ width: '100%', border: '1px solid var(--line)', borderRadius: 9, padding: '9px 11px' }}
              placeholder="e.g. Delivered the quotation and confirmed on call" />
          </div>
          <div className="wide">
            <label>Proof file / photo {settings.require_completion_attachment ? '*' : '(optional)'}</label>
            <input type="file" onChange={e => setFile(e.target.files[0] || null)} />
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy
            || (settings.require_completion_remarks && !remarks.trim())
            || (settings.require_completion_attachment && !file)}>
            {busy ? 'Saving…' : 'Complete task'}
          </button>
        </div>
      </form>
    </div>
  )
}

/* ================= Request a change (B2) ================= */

export function RequestChangeModal({ task, team, user, isAdmin = false, onClose, onDone }) {
  const [f, setF] = useState({
    due_at: '', priority: '', effort: '', title: '',
    stop_recurring: false, cancel: false, assigned_to: '', reason: '',
  })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(p => ({ ...p, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const approver = task.created_by_detail?.id === user.id ? 'an admin' : 'the task creator'

  const submit = async (e) => {
    e.preventDefault()
    const changes = {}
    if (f.cancel) changes.cancel = true
    else {
      if (f.due_at) changes.due_at = new Date(f.due_at).toISOString()
      if (f.priority) changes.priority = f.priority
      if (f.effort) changes.effort_minutes = Number(f.effort)
      if (f.title.trim()) changes.title = f.title.trim()
      if (f.stop_recurring) changes.frequency = 'one_time'
      if (f.assigned_to) changes.assigned_to = Number(f.assigned_to)
    }
    if (!Object.keys(changes).length) { setErr('Pick at least one change.'); return }
    setErr(''); setBusy(true)
    try {
      if (isAdmin) {
        // Admin edits directly -- no approval loop, but it IS logged.
        if (changes.cancel) {
          await api(`/api/tasks/${task.id}/`, { method: 'DELETE' })
        } else {
          const body = { ...changes }
          delete body.cancel
          await api(`/api/tasks/${task.id}/`, { method: 'PATCH', body })
        }
      } else {
        await api(`/api/tasks/${task.id}/request_change/`, {
          method: 'POST', body: { changes, reason: f.reason },
        })
      }
      onDone()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>{isAdmin ? `Edit task — ${task.code}` : `Request a change — ${task.code}`}</h2>
        <p className="muted small">
          {task.title} · {isAdmin
            ? 'admin edit: applies immediately and is logged in the task activity.'
            : <>approved by <strong>{approver}</strong>, logged for admin.</>}
        </p>
        <div className="form-grid">
          <div>
            <label>New due date</label>
            <input type="datetime-local" value={f.due_at} onChange={set('due_at')} disabled={f.cancel} />
          </div>
          <div>
            <label>New priority</label>
            <select value={f.priority} onChange={set('priority')} disabled={f.cancel}>
              <option value="">— keep —</option>
              {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>New effort (minutes)</label>
            <input type="number" min="1" value={f.effort} onChange={set('effort')} disabled={f.cancel} />
          </div>
          <div>
            <label>Reassign to</label>
            <select value={f.assigned_to} onChange={set('assigned_to')} disabled={f.cancel}>
              <option value="">— keep —</option>
              {team.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
          <div className="wide">
            <label>New title</label>
            <input value={f.title} onChange={set('title')} placeholder="— keep —" disabled={f.cancel} />
          </div>
          {task.frequency !== 'one_time' && (
            <div>
              <label className="switch" style={{ marginTop: 20 }}>
                <input type="checkbox" checked={f.stop_recurring} onChange={set('stop_recurring')}
                  disabled={f.cancel} />
                <span>Stop the recurrence</span>
              </label>
            </div>
          )}
          <div>
            <label className="switch" style={{ marginTop: 20 }}>
              <input type="checkbox" checked={f.cancel} onChange={set('cancel')} />
              <span>Cancel this task entirely</span>
            </label>
          </div>
          {!isAdmin && (
            <div className="wide">
              <label>Reason *</label>
              <input value={f.reason} onChange={set('reason')}
                placeholder="e.g. Deadline was set to midnight by mistake" />
            </div>
          )}
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || (!isAdmin && !f.reason.trim())}>
            {busy ? 'Saving…' : isAdmin ? 'Apply changes' : 'Send request'}
          </button>
        </div>
      </form>
    </div>
  )
}

/* ================= Requests inbox (B2) ================= */

const CHANGE_LABELS = {
  due_at: 'due date', effort_minutes: 'effort', priority: 'priority',
  title: 'title', description: 'description', frequency: 'recurrence',
  repeat_until: 'repeat-until', category: 'category', assigned_to: 'assignee',
}

function describeChanges(changes) {
  return Object.entries(changes).map(([k, v]) => {
    if (k === 'cancel') return 'cancel the task'
    if (k === 'due_at' && v) return `due date → ${fmtDT(v)}`
    if (k === 'effort_minutes') return `effort → ${fmtEffort(Number(v))}`
    if (k === 'frequency' && v === 'one_time') return 'stop recurrence'
    return `${CHANGE_LABELS[k] || k} → ${v}`
  }).join(' · ')
}

export function ChangeRequests({ isAdmin, onChanged }) {
  const [scope, setScope] = useState('inbox')
  const [rows, setRows] = useState(null)
  const [remarks, setRemarks] = useState({})
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api(`/api/task-change-requests/?scope=${scope}&page_size=100`)
      .then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [scope])
  useEffect(() => { load() }, [load])

  const review = async (r, decision) => {
    setErr('')
    try {
      await api(`/api/task-change-requests/${r.id}/review/`, {
        method: 'POST', body: { decision, remarks: remarks[r.id] || '' },
      })
      load(); onChanged?.()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading requests…</div>

  return (
    <div style={{ maxWidth: 820 }}>
      <div className="filters">
        <div className="seg">
          <button className={'seg-btn' + (scope === 'inbox' ? ' on' : '')} onClick={() => setScope('inbox')}>To approve</button>
          <button className={'seg-btn' + (scope === 'mine' ? ' on' : '')} onClick={() => setScope('mine')}>My requests</button>
          {isAdmin && <button className={'seg-btn' + (scope === 'all' ? ' on' : '')} onClick={() => setScope('all')}>All (log)</button>}
        </div>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && (
        <p className="muted">
          {scope === 'inbox' ? 'Nothing waiting for your approval.' : 'No requests here.'}
        </p>
      )}
      <div className="task-list">
        {rows.map(r => (
          <div className="task-row" key={r.id} style={{ flexWrap: 'wrap' }}>
            <div className="task-main">
              <div className="task-title">
                <span className="t-code">{r.task_code}</span>{r.task_title}
                <span className={`q-pill q-${r.status === 'pending' ? 'under_review' : r.status}`}>{r.status_display}</span>
                {r.escalated && <span className="ai-chip">↑ escalated to admin</span>}
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                <strong>{describeChanges(r.changes)}</strong>
              </div>
              <div className="small muted">Reason: {r.reason}</div>
              <div className="when">
                {r.requested_by?.name} · {fmtDT(r.created_at)}
                {r.reviewed_by && <> · reviewed by {r.reviewed_by.name}{r.remarks ? ` — "${r.remarks}"` : ''}</>}
              </div>
            </div>
            {scope === 'inbox' && r.status === 'pending' && (
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input placeholder="Remarks…" style={{ width: 140 }}
                  value={remarks[r.id] || ''}
                  onChange={e => setRemarks(p => ({ ...p, [r.id]: e.target.value }))} />
                <button className="btn btn-sm btn-primary" onClick={() => review(r, 'approved')}>Approve</button>
                <button className="btn btn-sm" onClick={() => review(r, 'rejected')}>Reject</button>
                {!isAdmin && (
                  <button className="btn btn-sm" title="Let the admin decide this one"
                    onClick={() => review(r, 'escalated')}>Escalate ↑</button>
                )}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ================= Deleted Tasks bin (A4, admin) ================= */

export function DeletedTasks() {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api('/api/tasks/?scope=deleted&page_size=100')
      .then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const restore = async (t) => {
    setErr('')
    try { await api(`/api/tasks/${t.id}/restore/`, { method: 'POST' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading bin…</div>
  return (
    <div style={{ maxWidth: 760 }}>
      <p className="muted small">Deleted tasks are never destroyed — they rest here, restorable any time.</p>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">The bin is empty.</p>}
      <div className="task-list">
        {rows.map(t => (
          <div className="task-row" key={t.id} style={{ opacity: .75 }}>
            <div className="task-main">
              <div className="task-title"><span className="t-code">{t.code}</span>{t.title}</div>
              <div className="when">
                {t.assigned_to_detail?.name} · deleted {fmtDT(t.deleted_at)}
              </div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={() => restore(t)}>Restore</button>
          </div>
        ))}
      </div>
    </div>
  )
}
