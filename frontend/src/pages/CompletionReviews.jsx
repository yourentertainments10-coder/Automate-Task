import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import ProofreadText from '../ProofreadText'

const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '—'

const mins = (m) => (!m ? '—' : m >= 60 ? `${Math.floor(m / 60)}h ${m % 60 || ''}`.trim() + 'm' : `${m}m`)

/* Work submitted as done, waiting for the person who gave it to accept.
 *
 * Accepting is one click. Sending it back needs a reason -- being told "redo
 * it" with no explanation wastes the second attempt as well as the first.
 */
export default function CompletionReviews({ isAdmin, onChanged }) {
  const [scope, setScope] = useState('inbox')
  const [rows, setRows] = useState(null)
  const [rejecting, setRejecting] = useState(null)   // id being sent back
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api(`/api/task-completions/?scope=${scope}&page_size=100`)
      .then(d => setRows(d.results || d))
      .catch(e => setErr(errorText(e.data) || e.message))
  }, [scope])
  useEffect(() => { load() }, [load])

  const decide = async (row, decision, remarks = '') => {
    setErr(''); setBusy(true)
    try {
      await api(`/api/task-completions/${row.id}/review/`,
        { method: 'POST', body: { decision, remarks } })
      setRejecting(null); setWhy('')
      load(); onChanged?.()
    } catch (e) { setErr(errorText(e.data) || e.message) }
    finally { setBusy(false) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>

  return (
    <div style={{ maxWidth: 860 }}>
      <div className="filters">
        <div className="seg">
          <button className={'seg-btn' + (scope === 'inbox' ? ' on' : '')}
            onClick={() => setScope('inbox')}>To accept</button>
          <button className={'seg-btn' + (scope === 'mine' ? ' on' : '')}
            onClick={() => setScope('mine')}>My submissions</button>
          {isAdmin && (
            <button className={'seg-btn' + (scope === 'all' ? ' on' : '')}
              onClick={() => setScope('all')}>All (log)</button>
          )}
        </div>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && (
        <p className="muted">
          {scope === 'inbox'
            ? 'Nothing waiting for you to accept.'
            : 'Nothing here yet.'}
        </p>
      )}

      <div className="task-list">
        {rows.map(r => {
          const late = r.task_due_at && r.created_at
            && new Date(r.created_at) > new Date(r.task_due_at)
          const over = r.task_actual_minutes && r.task_effort_minutes
            && r.task_actual_minutes > r.task_effort_minutes
          return (
            <div className="task-row" key={r.id} style={{ flexWrap: 'wrap' }}>
              <div className="task-main">
                <div className="task-title">
                  <span className="t-code">{r.task_code}</span>{r.task_title}
                  {r.status !== 'pending' && (
                    <span className={'ai-chip' + (r.status === 'rejected' ? ' prio prio-high' : '')}>
                      {r.status_display}
                    </span>
                  )}
                  {late && <span className="prio prio-high">finished late</span>}
                </div>
                <div className="when">
                  {r.submitted_by?.name} · submitted {fmtDT(r.created_at)} ·{' '}
                  took <strong>{mins(r.task_actual_minutes)}</strong> against{' '}
                  {mins(r.task_effort_minutes)}
                  {over && <span className="late"> · over estimate</span>}
                </div>
                {r.note && <div className="small muted prose" style={{ marginTop: 4 }}>{r.note}</div>}
                {r.remarks && (
                  <div className="small muted" style={{ marginTop: 4 }}>
                    <strong>{r.status === 'rejected' ? 'Sent back' : 'Note'}:</strong> {r.remarks}
                  </div>
                )}

                {rejecting === r.id && (
                  <div style={{ marginTop: 8 }}>
                    <ProofreadText label="What is wrong? *" value={why} onChange={setWhy}
                      rows={2}
                      placeholder="e.g. The invoice copy is missing — attach it and complete again." />
                    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                      <button className="btn btn-danger" disabled={busy || why.trim().length < 10}
                        onClick={() => decide(r, 'rejected', why.trim())}>
                        {busy ? 'Sending…' : 'Send it back'}
                      </button>
                      <button className="btn" onClick={() => { setRejecting(null); setWhy('') }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {r.status === 'pending' && rejecting !== r.id && (
                <div className="row-actions">
                  <button className="btn btn-primary" disabled={busy}
                    onClick={() => decide(r, 'approved')}>Accept</button>
                  <button className="btn" disabled={busy}
                    onClick={() => { setRejecting(r.id); setWhy('') }}>Send back</button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
