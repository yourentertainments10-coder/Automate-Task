import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import Directory from './Directory'
import { ChangeRequests, CompleteModal, DeletedTasks, ProgressModal, RequestChangeModal, WorkloadPanel } from './TaskExtras'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

const ACCENT = '#0d7a5f'
const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : null

/* "6 hours from now" / "2 days overdue" — the teardown's relative due style */
export const relDue = (iso) => {
  if (!iso) return null
  const diffMin = Math.round((new Date(iso) - Date.now()) / 60000)
  const abs = Math.abs(diffMin)
  const span = abs < 60 ? `${abs} min`
    : abs < 60 * 24 ? `${Math.round(abs / 60)} hour${Math.round(abs / 60) === 1 ? '' : 's'}`
    : `${Math.round(abs / (60 * 24))} day${Math.round(abs / (60 * 24)) === 1 ? '' : 's'}`
  return diffMin >= 0 ? `${span} from now` : `${span} overdue`
}

export const fmtEffort = (min) => {
  if (!min) return null
  if (min < 60) return `${min}m`
  return min % 60 === 0 ? `${min / 60}h` : `${Math.floor(min / 60)}h ${min % 60}m`
}
const PRIORITIES = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High'], ['urgent', 'Urgent']]
const DEPARTMENTS = [
  ['sales', 'Sales'], ['purchase', 'Purchase'], ['accounts', 'Accounts'],
  ['support', 'Customer Support'], ['hr', 'Human Resources'], ['management', 'Management'],
]
const FREQUENCIES = [['one_time', 'One time'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly']]
const RANGES = [
  ['today', 'Today'], ['yesterday', 'Yesterday'], ['this_week', 'This Week'],
  ['last_week', 'Last Week'], ['this_month', 'This Month'], ['last_month', 'Last Month'],
  ['this_year', 'This Year'], ['all', 'All Time'],
]

export default function Tasks() {
  const { can } = useAuth()
  const isAdmin = can('tasks.view_all')
  const [area, setArea] = useState('dashboard')
  const [prefill, setPrefill] = useState(null)   // template -> open list with modal
  const [inboxCount, setInboxCount] = useState(0)

  const refreshInbox = useCallback(() => {
    api('/api/task-change-requests/?scope=inbox&page_size=1')
      .then(d => setInboxCount(d.count ?? (d.results || d).length))
      .catch(() => {})
  }, [])
  useEffect(() => { refreshInbox() }, [refreshInbox])

  const useTemplate = (tpl) => { setPrefill(tpl); setArea('my') }

  const tabs = [
    ['dashboard', 'Dashboard'], ['my', 'My Tasks'], ['delegated', 'Delegated'],
    ['subscribed', 'Subscribed'],
    ['requests', inboxCount > 0 ? `Requests (${inboxCount})` : 'Requests'],
    ['templates', 'Templates'], ['directory', 'Template Directory'],
    ['activities', 'Activities'], ['time', 'Time Report'],
    ...(isAdmin ? [['deleted', 'Deleted']] : []),
  ]

  return (
    <div>
      <div className="page-head"><h1>Tasks</h1></div>
      <div className="area-tabs">
        {tabs.map(([v, l]) => (
          <button key={v} className={'tab' + (area === v ? ' on' : '')} onClick={() => setArea(v)}>{l}</button>
        ))}
      </div>
      {area === 'dashboard' && <TaskDashboard />}
      {['my', 'delegated', 'subscribed'].includes(area) && (
        <TaskList scope={area} key={area} prefill={prefill} clearPrefill={() => setPrefill(null)}
          onRequestsChanged={refreshInbox} />
      )}
      {area === 'requests' && <ChangeRequests isAdmin={isAdmin} onChanged={refreshInbox} />}
      {area === 'templates' && <Templates onUse={useTemplate} />}
      {area === 'directory' && <Directory />}
      {area === 'activities' && <Activities />}
      {area === 'time' && <TimeReport />}
      {area === 'deleted' && <DeletedTasks />}
    </div>
  )
}

/* ================= Dashboard ================= */

const TILES = [
  ['overdue', 'Overdue', 'alert'], ['pending', 'Pending', ''],
  ['in_progress', 'In Progress', ''], ['completed', 'Completed', 'good'],
  ['in_time', 'In Time', 'good'], ['delayed', 'Delayed', 'alert'],
]

function TaskDashboard() {
  const { can } = useAuth()
  const hasGroup = can('tasks.view_all') || can('tasks.view_department')
  const [range, setRange] = useState('this_week')
  const [scope, setScope] = useState('my')
  const [category, setCategory] = useState('')
  const [search, setSearch] = useState('')
  const [view, setView] = useState('table')
  const [cats, setCats] = useState([])
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => { api('/api/tasks/categories/').then(setCats).catch(() => {}) }, [])
  useEffect(() => {
    const p = new URLSearchParams({ range, scope })
    if (category) p.set('category', category)
    if (search.trim()) p.set('search', search.trim())
    api(`/api/tasks/dashboard/?${p}`).then(d => { setData(d); setErr('') }).catch(e => setErr(e.message))
  }, [range, scope, category, search])

  return (
    <div>
      <div className="filters">
        {RANGES.map(([v, l]) => (
          <button key={v} className={'chip' + (range === v ? ' on-accent' : '')} onClick={() => setRange(v)}>{l}</button>
        ))}
      </div>
      <div className="filters">
        <div className="seg">
          <button className={'seg-btn' + (scope === 'my' ? ' on' : '')} onClick={() => setScope('my')}>My Report</button>
          <button className={'seg-btn' + (scope === 'delegated' ? ' on' : '')} onClick={() => setScope('delegated')}>Delegated</button>
          {hasGroup && <button className={'seg-btn' + (scope === 'group' ? ' on' : '')} onClick={() => setScope('group')}>Group</button>}
        </div>
        <select value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {cats.map(c => <option key={c}>{c}</option>)}
        </select>
        <input type="search" placeholder="Search tasks…" value={search} onChange={e => setSearch(e.target.value)} />
        <div className="seg">
          <button className={'seg-btn' + (view === 'table' ? ' on' : '')} onClick={() => setView('table')}>Table</button>
          <button className={'seg-btn' + (view === 'bar' ? ' on' : '')} onClick={() => setView('bar')}>Bar Chart</button>
        </div>
      </div>
      {err && <div className="err">{err}</div>}
      {data && (
        <>
          <div className="stats">
            {TILES.map(([k, l, tone]) => (
              <div key={k} className={'stat' + (tone === 'alert' && data.tiles[k] > 0 ? ' alert' : '')}>
                <div className="label">{l}</div><div className="value">{data.tiles[k]}</div>
              </div>
            ))}
          </div>
          {data.categories.length === 0 && <p className="muted">No tasks in this range.</p>}
          {data.categories.length > 0 && view === 'table' && (
            <table className="table" style={{ maxWidth: 860 }}>
              <thead>
                <tr><th>Category</th><th>Total</th><th>Overdue</th><th>Pending</th><th>In Progress</th><th>Completed</th><th>In Time</th><th>Delayed</th></tr>
              </thead>
              <tbody>
                {data.categories.map(c => (
                  <tr key={c.category}>
                    <td><strong>{c.category}</strong></td>
                    <td>{c.total}</td>
                    <td className={c.overdue ? 'late' : ''}>{c.overdue}</td>
                    <td>{c.pending}</td><td>{c.in_progress}</td>
                    <td className="ok">{c.completed}</td><td>{c.in_time}</td>
                    <td className={c.delayed ? 'late' : ''}>{c.delayed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.categories.length > 0 && view === 'bar' && (
            <div className="dash-card" style={{ maxWidth: 860 }}>
              <div className="chart-box">
                <Bar
                  data={{
                    labels: data.categories.map(c => c.category),
                    datasets: [{
                      data: data.categories.map(c => c.total),
                      backgroundColor: ACCENT,
                      borderRadius: { topLeft: 4, topRight: 4 },
                      maxBarThickness: 36,
                    }],
                  }}
                  options={{
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                      tooltip: {
                        displayColors: false,
                        callbacks: {
                          afterLabel: (ctx) => {
                            const c = data.categories[ctx.dataIndex]
                            return `overdue ${c.overdue} · pending ${c.pending} · in progress ${c.in_progress}\ncompleted ${c.completed} (in time ${c.in_time}, delayed ${c.delayed})`
                          },
                        },
                      },
                    },
                    scales: {
                      x: { grid: { display: false }, ticks: { color: '#66716c', font: { size: 11 } } },
                      y: { beginAtZero: true, ticks: { color: '#66716c', precision: 0, font: { size: 11 } }, grid: { color: '#e9ece9' }, border: { display: false } },
                    },
                  }}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/* ================= Task lists (My / Delegated / Subscribed) ================= */

const STATUS_TABS = [['open,in_progress', 'Open'], ['done', 'Done'], ['', 'All']]

function TaskList({ scope, prefill, clearPrefill, onRequestsChanged }) {
  const { user } = useAuth()
  const [rows, setRows] = useState([])
  const [team, setTeam] = useState([])        // hierarchy-filtered: who I may assign to
  const [groups, setGroups] = useState([])
  const [settings, setSettings] = useState({})
  const [err, setErr] = useState('')
  const [tab, setTab] = useState('open,in_progress')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [onlyRecurring, setOnlyRecurring] = useState(false)
  const [showAdd, setShowAdd] = useState(!!prefill)
  const [completing, setCompleting] = useState(null)   // task in the evidence modal
  const [progressFor, setProgressFor] = useState(null) // task in the status-update modal (P1)
  const [requestFor, setRequestFor] = useState(null)   // task in the request-change modal

  const load = useCallback(() => {
    const p = new URLSearchParams({ page_size: '200', scope })
    if (tab) p.set('status', tab)
    if (onlyOverdue) p.set('overdue', 'true')
    if (onlyRecurring) p.set('recurring', 'true')
    api(`/api/tasks/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [scope, tab, onlyOverdue, onlyRecurring])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    api('/api/tasks/assignees/').then(setTeam).catch(() => {})
    api('/api/groups/?active=true').then(setGroups).catch(() => {})
    api('/api/task-settings/').then(setSettings).catch(() => {})
  }, [])

  const needsEvidence = settings.require_completion_remarks || settings.require_completion_attachment

  const setStatus = async (t, status) => {
    // P2: completing ALWAYS collects description + actual effort spent
    if (status === 'done') { setCompleting(t); return }
    // P1: picking "In Progress" opens the status-update form
    if (status === 'in_progress') { setProgressFor(t); return }
    setErr('')
    try { await api(`/api/tasks/${t.id}/`, { method: 'PATCH', body: { status } }); load() }
    catch (e) {
      const data = e.data || {}
      if (data.needs) { setCompleting(t); return }   // server says evidence required
      setErr(errorText(data) || e.message)
    }
  }

  const giveEstimate = async (t) => {
    const raw = window.prompt(
      `Your estimate for "${t.title}" in MINUTES` +
      (t.effort_minutes ? ` (assigner said ${fmtEffort(t.effort_minutes)})` : '') + ':')
    if (!raw) return
    setErr('')
    try { await api(`/api/tasks/${t.id}/estimate/`, { method: 'POST', body: { minutes: Number(raw) } }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const toggleSub = async (t) => {
    setErr('')
    try {
      await api(`/api/tasks/${t.id}/${t.subscribed ? 'unsubscribe' : 'subscribe'}/`, { method: 'POST' })
      load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const empty = {
    my: 'No tasks assigned to you here.',
    delegated: 'No tasks you delegated to others here.',
    subscribed: 'You are not following any tasks. Use the 🔔 on a task to follow it.',
  }[scope]

  return (
    <div>
      <div className="filters">
        <div className="seg">
          {STATUS_TABS.map(([v, l]) => (
            <button key={l} className={'seg-btn' + (tab === v ? ' on' : '')} onClick={() => setTab(v)}>{l}</button>
          ))}
        </div>
        <button className={'chip' + (onlyOverdue ? ' on' : '')} onClick={() => setOnlyOverdue(v => !v)}>
          ⏰ Overdue only
        </button>
        {scope === 'delegated' && (
          <button className={'chip' + (onlyRecurring ? ' on-accent' : '')}
            title="How many daily/weekly tasks have I assigned?"
            onClick={() => setOnlyRecurring(v => !v)}>
            ↻ Recurring only
          </button>
        )}
        <span style={{ flex: 1 }} />
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add Task</button>
      </div>

      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">{empty}</p>}

      <div className="task-list">
        {rows.map(t => (
          <div key={t.id} className={'task-row' + (t.is_overdue ? ' overdue' : '') + (t.status === 'done' ? ' done' : '')}>
            <input
              type="checkbox" checked={t.status === 'done'}
              disabled={t.assigned_to !== user.id}
              onChange={e => setStatus(t, e.target.checked ? 'done' : 'open')}
              title={t.assigned_to !== user.id ? 'Only the assignee can complete this task'
                : t.status === 'done' ? 'Reopen' : 'Mark done'}
            />
            <div className="task-main">
              <div className="task-title">
                <span className="t-code">{t.code}</span>
                {t.title}
                {t.category && <span className="ai-chip">{t.category}</span>}
                {t.group_name && <span className="ai-chip">👥 {t.group_name}</span>}
                {t.frequency !== 'one_time' && (
                  <span className="ai-chip">↻ {t.frequency_display}{t.repeat_until ? ` till ${fmtDT(t.repeat_until + 'T00:00:00')?.split(',')[0]}` : ''}</span>
                )}
                {t.priority !== 'normal' && <span className={`prio prio-${t.priority}`}>{t.priority_display}</span>}
                {t.effort_minutes && <span className="ai-chip" title="Effort set by the assigner">⏱ {fmtEffort(t.effort_minutes)}</span>}
                {t.status === 'in_progress' && t.progress_percent != null && (
                  <span className="ai-chip" title="Latest status update">▰ {t.progress_percent}%</span>
                )}
                {t.status !== 'done' && t.actual_minutes && (
                  <span className="ai-chip" title="Effort spent so far (self-reported)">⏲ {fmtEffort(t.actual_minutes)} spent</span>
                )}
                {t.status === 'done' && t.actual_minutes && (
                  <span className="ai-chip" title="Actual effort spent vs assigned">⏲ took {fmtEffort(t.actual_minutes)}</span>
                )}
                {t.assignee_estimate_minutes && (
                  <span className="ai-chip est" title="Assignee's own estimate">
                    est. {fmtEffort(t.assignee_estimate_minutes)}
                  </span>
                )}
                {t.pending_change_requests > 0 && (
                  <span className="prio prio-high" title="Pending change request">✎ {t.pending_change_requests}</span>
                )}
              </div>
              {t.description && <div className="small muted">{t.description}</div>}
              {t.completion_note && <div className="small muted">📝 {t.completion_note}</div>}
              <div className="when">
                {t.assigned_to_detail?.name}
                {scope !== 'my' && t.created_by_detail && <> · by {t.created_by_detail.name}</>}
                {t.lead_name && <> · lead: <strong>{t.lead_name}</strong></>}
                {t.due_at && t.status !== 'done' && (
                  <span className={t.is_overdue ? ' late' : ''}> · {relDue(t.due_at)}</span>
                )}
                {t.completed_at && <> · done {fmtDT(t.completed_at)}</>}
              </div>
            </div>
            {t.assigned_to === user.id && t.status !== 'done' && !t.assignee_estimate_minutes && (
              <button className="btn btn-sm" title="Disagree with the effort? Record your own estimate."
                onClick={() => giveEstimate(t)}>est.</button>
            )}
            {(t.assigned_to === user.id || t.created_by_detail?.id === user.id
              || user.capabilities?.includes('tasks.view_all')) && t.status !== 'done' && (
              <button className="btn btn-sm"
                title={user.capabilities?.includes('tasks.view_all')
                  ? 'Edit this task (admin — applies immediately)'
                  : 'Propose a change (deadline, effort, recurrence…) for approval'}
                onClick={() => setRequestFor(t)}>✎</button>
            )}
            <button
              className={'bell' + (t.subscribed ? ' on' : '')}
              title={t.subscribed ? 'Unfollow' : 'Follow this task'}
              onClick={() => toggleSub(t)}
            >🔔</button>
            {t.status === 'in_progress' && t.assigned_to === user.id && (
              <button className="btn btn-sm" title="Add another status update (% done, effort, comment)"
                onClick={() => setProgressFor(t)}>+ update</button>
            )}
            {t.status !== 'done' && t.assigned_to === user.id && (
              <select value={t.status} onChange={e => setStatus(t, e.target.value)}>
                <option value="open">Open</option>
                <option value="in_progress">In Progress — Status Update</option>
                <option value="done">Done</option>
              </select>
            )}
          </div>
        ))}
      </div>

      {completing && (
        <CompleteModal task={completing} settings={settings}
          onClose={() => setCompleting(null)}
          onDone={() => { setCompleting(null); load() }} />
      )}
      {progressFor && (
        <ProgressModal task={progressFor}
          onClose={() => setProgressFor(null)}
          onDone={() => { setProgressFor(null); load() }} />
      )}
      {requestFor && (
        <RequestChangeModal task={requestFor} team={team} user={user}
          isAdmin={user.capabilities?.includes('tasks.view_all')}
          onClose={() => setRequestFor(null)}
          onDone={() => { setRequestFor(null); load(); onRequestsChanged?.() }} />
      )}

      {showAdd && (
        <TaskModal
          user={user} team={team} groups={groups} template={prefill}
          onClose={() => { setShowAdd(false); clearPrefill?.() }}
          onSaved={() => { setShowAdd(false); clearPrefill?.(); load() }}
        />
      )}
    </div>
  )
}

/* Dropdown with checkboxes — used for Assign to and Loop (multi-select) */
function MultiSelect({ options, selected, onChange, placeholder }) {
  const [open, setOpen] = useState(false)
  const picked = options.filter(o => selected.includes(o.id))
  const label = picked.length === 0 ? (placeholder || '— select —')
    : picked.length <= 2 ? picked.map(o => o.name).join(', ')
    : `${picked.length} selected`
  return (
    <div style={{ position: 'relative' }}>
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', textAlign: 'left', border: '1px solid var(--line)',
          borderRadius: 9, padding: '9px 11px', background: 'var(--surface)',
          cursor: 'pointer', color: picked.length ? 'inherit' : 'var(--muted)',
        }}>
        {label}<span style={{ float: 'right', color: 'var(--muted)' }}>▾</span>
      </button>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 9 }} onClick={() => setOpen(false)} />
          <div style={{
            position: 'absolute', zIndex: 10, top: '104%', left: 0, right: 0,
            maxHeight: 180, overflowY: 'auto', background: 'var(--surface)',
            border: '1px solid var(--line)', borderRadius: 9,
            boxShadow: '0 8px 24px rgba(20,32,28,.18)', padding: 6,
          }}>
            {options.map(o => (
              <label key={o.id} style={{
                display: 'flex', gap: 8, alignItems: 'center', padding: '5px 8px',
                fontWeight: 'normal', cursor: 'pointer', borderRadius: 6, margin: 0,
              }}>
                <input type="checkbox" style={{ width: 'auto' }} checked={selected.includes(o.id)}
                  onChange={() => onChange(selected.includes(o.id)
                    ? selected.filter(x => x !== o.id) : [...selected, o.id])} />
                {o.name}
              </label>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function TaskModal({ user, team, groups = [], template, onClose, onSaved }) {
  const { can } = useAuth()
  const canAddCategory = can('tasks.assign')
  const [f, setF] = useState({
    title: template?.title || '', description: template?.description || '',
    category: template?.category || '', frequency: template?.frequency || 'one_time',
    department: user.department === 'management' ? '' : (user.department || ''),
    group: '',
    priority: template?.priority || 'normal', due_at: '', repeat_until: '',
    effort: '', effort_unit: 'minutes',
  })
  const [assignees, setAssignees] = useState([user.id])  // multi-select: one task per person
  const [categories, setCategories] = useState([])
  const [inLoop, setInLoop] = useState([])          // Loop: colleagues who follow the task
  const [newCat, setNewCat] = useState(null)        // null = closed, '' = typing
  const [workloads, setWorkloads] = useState([])    // C1: pipeline per picked assignee
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))

  // C1: whoever is picked, show their current pipeline (informs, never blocks)
  useEffect(() => {
    let alive = true
    Promise.all(assignees.map(id =>
      api(`/api/tasks/workload/?user=${id}`).catch(() => null)))
      .then(ws => { if (alive) setWorkloads(ws.filter(Boolean)) })
    return () => { alive = false }
  }, [assignees])

  // Department first, then its categories (global + department-specific)
  useEffect(() => {
    api(`/api/task-categories/?department=${encodeURIComponent(f.department)}`)
      .then(rows => {
        setCategories(rows)
        setF(prev => rows.some(c => c.name === prev.category) || !prev.category
          ? prev : { ...prev, category: '' })
      })
      .catch(() => setCategories([]))
  }, [f.department])

  const addCategory = async () => {
    const name = (newCat || '').trim()
    if (!name) return
    try {
      const cat = await api('/api/task-categories/', {
        method: 'POST', body: { name, department: f.department },
      })
      setCategories(prev => [...prev.filter(c => c.id !== cat.id), cat])
      setF(prev => ({ ...prev, category: cat.name }))
      setNewCat(null)
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    const effort = f.effort
      ? Math.round(Number(f.effort) * (f.effort_unit === 'hours' ? 60 : 1))
      : null
    const base = {
      title: f.title, description: f.description, category: f.category,
      department: f.department,
      frequency: f.frequency, priority: f.priority,
      group: f.group ? Number(f.group) : null,
      due_at: f.due_at ? new Date(f.due_at).toISOString() : null,
      repeat_until: f.frequency !== 'one_time' && f.repeat_until ? f.repeat_until : null,
      effort_minutes: effort,
    }
    // one INDIVIDUAL task per picked assignee — each completes their own
    let created = 0
    try {
      for (const id of assignees) {
        await api('/api/tasks/', {
          method: 'POST',
          body: { ...base, assigned_to: id, in_loop: inLoop.filter(x => x !== id) },
        })
        created += 1
      }
      onSaved()
    } catch (ex) {
      setErr((created ? `Created ${created}/${assignees.length}, then failed: ` : '')
        + (errorText(ex.data) || ex.message))
    } finally { setBusy(false) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>{template ? `New task from "${template.name}"` : 'Add Task'}</h2>
        <div className="form-grid">
          <div className="wide">
            <label>Title *</label>
            <input value={f.title} onChange={set('title')} autoFocus placeholder="e.g. Call Ravi with revised quote" />
          </div>
          <div className="wide">
            <label>Description *</label>
            <input value={f.description} onChange={set('description')} required
              placeholder="What exactly has to be done?" />
          </div>
          <div>
            <label>Department</label>
            <select value={f.department} onChange={set('department')}>
              <option value="">General (no department)</option>
              {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Category *</label>
            {newCat === null ? (
              <div style={{ display: 'flex', gap: 6 }}>
                <select value={f.category} onChange={set('category')} style={{ flex: 1 }}>
                  <option value="">— pick a category —</option>
                  {categories.map(c => (
                    <option key={c.id} value={c.name}>
                      {c.name}{c.department ? '' : ' (general)'}
                    </option>
                  ))}
                </select>
                {canAddCategory && (
                  <button type="button" className="btn btn-sm" title="Add a new category"
                    onClick={() => setNewCat('')}>+</button>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 6 }}>
                <input value={newCat} onChange={e => setNewCat(e.target.value)} autoFocus
                  placeholder="New category name" style={{ flex: 1 }}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCategory() } }} />
                <button type="button" className="btn btn-sm btn-primary" onClick={addCategory}>Add</button>
                <button type="button" className="btn btn-sm" onClick={() => setNewCat(null)}>✕</button>
              </div>
            )}
          </div>
          <div>
            <label>Frequency</label>
            <select value={f.frequency} onChange={set('frequency')}>
              {FREQUENCIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Assign to * (your level &amp; below — each gets their own task)</label>
            <MultiSelect options={team} selected={assignees} onChange={setAssignees}
              placeholder="— pick people —" />
          </div>
          {workloads.length > 0 && (
            <div className="wide">
              {workloads.map(w => <WorkloadPanel key={w.user} w={w} />)}
            </div>
          )}
          <div>
            <label>Effort — how long should this take? *</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input type="number" min="1" value={f.effort} onChange={set('effort')}
                required placeholder="required" style={{ flex: 1 }} />
              <select value={f.effort_unit} onChange={set('effort_unit')} style={{ width: 90 }}>
                <option value="minutes">min</option>
                <option value="hours">hours</option>
              </select>
            </div>
          </div>
          <div>
            <label>Loop (colleagues who follow this task)</label>
            <MultiSelect options={team.filter(a => a.id !== user.id)}
              selected={inLoop} onChange={setInLoop} placeholder="— optional —" />
          </div>
          <div>
            <label>Group</label>
            <select value={f.group} onChange={set('group')}>
              <option value="">None</option>
              {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </div>
          <div>
            <label>Priority</label>
            <select value={f.priority} onChange={set('priority')}>
              {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Due * {f.frequency !== 'one_time' && '(first occurrence)'}</label>
            <input type="datetime-local" value={f.due_at} onChange={set('due_at')} required />
          </div>
          {f.frequency !== 'one_time' && (
            <div>
              <label>Repeat until (optional)</label>
              <input type="date" value={f.repeat_until} onChange={set('repeat_until')} />
            </div>
          )}
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary"
            disabled={busy || !f.title.trim() || !f.description.trim()
              || !f.category || !f.effort || !f.due_at || assignees.length === 0}>
            {busy ? 'Saving…'
              : assignees.length > 1 ? `Create ${assignees.length} tasks` : 'Create task'}
          </button>
        </div>
      </form>
    </div>
  )
}

/* ================= Templates ================= */

function Templates({ onUse }) {
  const { can } = useAuth()
  const canManage = can('tasks.assign')
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  const load = () => api('/api/task-templates/').then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const remove = async (t) => {
    try { await api(`/api/task-templates/${t.id}/`, { method: 'DELETE' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const grouped = useMemo(() => {
    const g = {}
    rows.forEach(t => { (g[t.category || 'General'] ||= []).push(t) })
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b))
  }, [rows])

  return (
    <div>
      {canManage && (
        <div className="filters">
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ New template</button>
        </div>
      )}
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No templates yet{canManage ? ' — create reusable task blueprints for your team.' : '.'}</p>}
      {grouped.map(([cat, tpls]) => (
        <div key={cat} style={{ marginBottom: 16 }}>
          <h3 className="tpl-cat">{cat}</h3>
          <div className="task-list">
            {tpls.map(t => (
              <div className="task-row" key={t.id}>
                <div className="task-main">
                  <div className="task-title">
                    {t.name}
                    {t.priority !== 'normal' && <span className={`prio prio-${t.priority}`}>{t.priority}</span>}
                    {t.frequency !== 'one_time' && <span className="ai-chip">↻ {t.frequency}</span>}
                  </div>
                  <div className="small muted">{t.title}{t.description ? ` — ${t.description}` : ''}</div>
                </div>
                <button className="btn btn-sm btn-primary" onClick={() => onUse(t)}>Use</button>
                {canManage && <button className="btn btn-sm" onClick={() => remove(t)}>Delete</button>}
              </div>
            ))}
          </div>
        </div>
      ))}
      {showAdd && <TemplateModal onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); load() }} />}
    </div>
  )
}

function TemplateModal({ onClose, onSaved }) {
  const [f, setF] = useState({ name: '', category: '', title: '', description: '', priority: 'normal', frequency: 'one_time' })
  const [err, setErr] = useState('')
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))
  const submit = async (e) => {
    e.preventDefault()
    try { await api('/api/task-templates/', { method: 'POST', body: f }); onSaved() }
    catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }
  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>New task template</h2>
        <div className="form-grid">
          <div><label>Template name *</label><input value={f.name} onChange={set('name')} autoFocus /></div>
          <div><label>Category</label><input value={f.category} onChange={set('category')} placeholder="e.g. Calls" /></div>
          <div className="wide"><label>Task title *</label><input value={f.title} onChange={set('title')} /></div>
          <div className="wide"><label>Description</label><input value={f.description} onChange={set('description')} /></div>
          <div>
            <label>Priority</label>
            <select value={f.priority} onChange={set('priority')}>
              {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Frequency</label>
            <select value={f.frequency} onChange={set('frequency')}>
              {FREQUENCIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={!f.name.trim() || !f.title.trim()}>Save template</button>
        </div>
      </form>
    </div>
  )
}

/* ================= Activities ================= */

function Activities() {
  const [rows, setRows] = useState([])
  const [days, setDays] = useState('7')
  const [err, setErr] = useState('')

  useEffect(() => {
    const p = new URLSearchParams({ page_size: '100' })
    if (days) p.set('days', days)
    api(`/api/task-activities/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [days])

  return (
    <div>
      <div className="filters">
        <div className="seg">
          {[['1', 'Today'], ['7', '7 days'], ['30', '30 days'], ['', 'All']].map(([v, l]) => (
            <button key={l} className={'seg-btn' + (days === v ? ' on' : '')} onClick={() => setDays(v)}>{l}</button>
          ))}
        </div>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No task activity in this window.</p>}
      <div className="dash-card" style={{ maxWidth: 720 }}>
        {rows.map(a => (
          <div className="feed-row" key={a.id}>
            <span className="dot" style={{ marginTop: 6 }} />
            <div>
              <strong>{a.task_title}</strong> <span className="small muted">{a.text}</span>
              <div className="when">{a.actor?.name || 'System'} · {fmtDT(a.created_at)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ================= Time Report (P3) ================= */

const TIME_RANGES = [
  ['today', 'Today'], ['this_week', 'This Week'],
  ['this_month', 'This Month'], ['this_year', 'This Year'], ['all', 'All Time'],
]

function TimeReport() {
  const [range, setRange] = useState('this_month')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api(`/api/tasks/time_report/?range=${range}`)
      .then(setData).catch(e => setErr(errorText(e.data) || e.message))
  }, [range])

  if (err) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading…</div>
  return (
    <div style={{ maxWidth: 760 }}>
      <div className="filters">
        <div className="seg">
          {TIME_RANGES.map(([v, l]) => (
            <button key={v} className={'seg-btn' + (range === v ? ' on' : '')}
              onClick={() => setRange(v)}>{l}</button>
          ))}
        </div>
      </div>
      <p className="muted small">
        <strong>Time Earned</strong> = the assigner&rsquo;s task time, credited when the
        task completes. <strong>Time Spent</strong> = the actual effort the person
        reported. A big gap either way is a conversation, not a verdict.
      </p>
      {data.rows.length === 0 && <p className="muted">No completed tasks in this period.</p>}
      {data.rows.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Person</th><th>Done</th><th>Time Earned</th><th>Time Spent</th><th>Difference</th></tr>
          </thead>
          <tbody>
            {data.rows.map(r => {
              const diff = r.time_spent_minutes - r.time_earned_minutes
              return (
                <tr key={r.user}>
                  <td><strong>{r.name}</strong>
                    {r.no_effort_tasks > 0 && (
                      <div className="muted small">{r.no_effort_tasks} task{r.no_effort_tasks === 1 ? '' : 's'} had no effort value — earned 0</div>
                    )}
                  </td>
                  <td>{r.done}</td>
                  <td>{fmtEffort(r.time_earned_minutes) || '0m'}</td>
                  <td>{fmtEffort(r.time_spent_minutes) || '0m'}</td>
                  <td className={diff > 0 ? 'late' : ''}>
                    {diff === 0 ? '—' : (diff > 0 ? '+' : '−') + fmtEffort(Math.abs(diff))}
                    {diff > 0 ? ' over' : diff < 0 ? ' under' : ''}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* Holidays moved to the Attendance page (HR.jsx) — reviewer feedback. */
