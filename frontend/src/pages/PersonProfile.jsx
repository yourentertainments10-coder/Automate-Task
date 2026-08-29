/* One person's whole picture in a slide-over: headline counts (completed /
   pending / overdue) over a chosen range, plus their full task list with the
   same filters as the Tasks page. Opened by clicking a name in My Team, in
   the Employees report, or in All Tasks. */
import { useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import TaskDetailPanel from './TaskDetail'
import { fmtEffort, relDue } from './Tasks'

const RANGES = [
  ['this_month', 'This Month'], ['this_week', 'This Week'],
  ['today', 'Today'], ['this_year', 'This Year'], ['all', 'All Time'],
]
const STATUS_TABS = [['open,in_progress', 'Open'], ['done', 'Done'], ['', 'All']]

export default function PersonProfile({ userId, name, onClose }) {
  const { user: me } = useAuth()
  const [range, setRange] = useState('this_month')
  const [stats, setStats] = useState(null)
  const [tasks, setTasks] = useState(null)
  const [tab, setTab] = useState('open,in_progress')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [detailFor, setDetailFor] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setStats(null)
    api(`/api/tasks/employees_report/?range=${range}&user=${userId}`)
      .then(d => setStats(d.rows?.[0] || null))
      .catch(e => setErr(errorText(e.data) || e.message))
  }, [userId, range])

  const loadTasks = () => {
    const p = new URLSearchParams({ page_size: '200', assigned_to: String(userId) })
    if (tab) p.set('status', tab)
    if (onlyOverdue) p.set('overdue', 'true')
    api(`/api/tasks/?${p}`).then(d => setTasks(d.results || d))
      .catch(e => setErr(errorText(e.data) || e.message))
  }
  useEffect(() => { setTasks(null); loadTasks() }, [userId, tab, onlyOverdue])  // eslint-disable-line react-hooks/exhaustive-deps

  const s = stats
  return (
    <div className="modal side"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-card side-panel">
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
          <h2 style={{ margin: 0, flex: 1 }}>{stats?.name || name}</h2>
          <button className="btn btn-sm" onClick={onClose}>✕</button>
        </div>

        <div className="filters" style={{ marginTop: 10 }}>
          <div className="seg">
            {RANGES.map(([v, l]) => (
              <button key={v} className={'seg-btn' + (range === v ? ' on' : '')}
                onClick={() => setRange(v)}>{l}</button>
            ))}
          </div>
        </div>
        {err && <div className="err">{err}</div>}

        {!s && !err && <p className="muted small">Loading summary…</p>}
        {s && (
          <>
            <div className="stats compact">
              <div className="stat"><div className="label">Total</div><div className="value">{s.total}</div></div>
              <div className="stat"><div className="label">Completed</div><div className="value ok">{s.completed}</div></div>
              <div className="stat"><div className="label">Pending</div><div className="value">{s.pending + s.in_progress}</div></div>
              <div className="stat"><div className="label">Overdue</div><div className={'value' + (s.overdue ? ' late' : '')}>{s.overdue}</div></div>
              <div className="stat"><div className="label">In time</div><div className="value">{s.in_time}</div></div>
              <div className="stat"><div className="label">Delayed</div><div className={'value' + (s.delayed ? ' late' : '')}>{s.delayed}</div></div>
              <div className="stat"><div className="label">Time Earned</div><div className="value">{fmtEffort(s.time_earned_minutes) || '0m'}</div></div>
              <div className="stat">
                <div className="label">Score</div>
                <div className="value" title="Only tasks assigned by someone else are scored">
                  {s.score ?? '—'}
                </div>
              </div>
            </div>
            {s.self_assigned > 0 && (
              <p className="muted small">
                {s.self_assigned} of these {s.self_assigned === 1 ? 'is' : 'are'} self-assigned —
                they show in the counts but earn no points. The score comes from
                the {s.scored_completed} task{s.scored_completed === 1 ? '' : 's'} someone
                else assigned and this person finished.
              </p>
            )}
            {s.review && <p className="muted small">💡 {s.review}</p>}
          </>
        )}

        <h3 style={{ margin: '14px 0 6px' }}>Tasks</h3>
        <div className="filters">
          <div className="seg">
            {STATUS_TABS.map(([v, l]) => (
              <button key={l} className={'seg-btn' + (tab === v ? ' on' : '')}
                onClick={() => setTab(v)}>{l}</button>
            ))}
          </div>
          <button className={'chip' + (onlyOverdue ? ' on' : '')}
            onClick={() => setOnlyOverdue(v => !v)}>⏰ Overdue only</button>
          <span className="muted small">{tasks?.length ?? 0} shown</span>
        </div>

        {!tasks && <p className="muted small">Loading tasks…</p>}
        {tasks?.length === 0 && <p className="muted small">No tasks match this filter.</p>}
        {tasks?.length > 0 && (
          <div className="task-list">
            {tasks.map(t => (
              <div key={t.id} className={'task-row' + (t.is_overdue ? ' overdue' : '') + (t.status === 'done' ? ' done' : '')}>
                <div className="task-main" style={{ cursor: 'pointer' }}
                  title="Open task details" onClick={() => setDetailFor(t)}>
                  <div className="task-title">
                    <span className="t-code">{t.code}</span>{t.title}
                    {t.category && <span className="ai-chip">{t.category}</span>}
                    {t.priority !== 'normal' && <span className={`prio prio-${t.priority}`}>{t.priority_display}</span>}
                    {t.effort_minutes && <span className="ai-chip">⏱ {fmtEffort(t.effort_minutes)}</span>}
                    {t.status === 'in_progress' && t.progress_percent != null && (
                      <span className="ai-chip">▰ {t.progress_percent}%</span>
                    )}
                  </div>
                  <div className="when">
                    {t.status_display}
                    {t.created_by_detail && <> · by {t.created_by_detail.name}</>}
                    {t.due_at && t.status !== 'done' && (
                      <span className={t.is_overdue ? ' late' : ''}> · {relDue(t.due_at)}</span>
                    )}
                    {t.completed_at && <> · done {new Date(t.completed_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="modal-actions">
          <button className="btn btn-primary" onClick={onClose}>Close</button>
        </div>
      </div>
      {detailFor && (
        <TaskDetailPanel taskId={detailFor.id} user={me} team={[]} settings={{}}
          onClose={() => setDetailFor(null)} onChanged={loadTasks} />
      )}
    </div>
  )
}
