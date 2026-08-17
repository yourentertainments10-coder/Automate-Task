import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import Directory from './Directory'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

const ACCENT = '#0d7a5f'
const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : null
const PRIORITIES = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High'], ['urgent', 'Urgent']]
const FREQUENCIES = [['one_time', 'One time'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly']]
const RANGES = [
  ['today', 'Today'], ['yesterday', 'Yesterday'], ['this_week', 'This Week'],
  ['last_week', 'Last Week'], ['this_month', 'This Month'], ['last_month', 'Last Month'],
  ['this_year', 'This Year'], ['all', 'All Time'],
]

const AREA_TABS = [
  ['dashboard', 'Dashboard'], ['my', 'My Tasks'], ['delegated', 'Delegated'],
  ['subscribed', 'Subscribed'], ['templates', 'Templates'],
  ['directory', 'Template Directory'],
  ['activities', 'Activities'], ['holidays', 'Holidays'],
]

export default function Tasks() {
  const [area, setArea] = useState('dashboard')
  const [prefill, setPrefill] = useState(null)   // template -> open list with modal

  const useTemplate = (tpl) => { setPrefill(tpl); setArea('my') }

  return (
    <div>
      <div className="page-head"><h1>Tasks</h1></div>
      <div className="area-tabs">
        {AREA_TABS.map(([v, l]) => (
          <button key={v} className={'tab' + (area === v ? ' on' : '')} onClick={() => setArea(v)}>{l}</button>
        ))}
      </div>
      {area === 'dashboard' && <TaskDashboard />}
      {['my', 'delegated', 'subscribed'].includes(area) && (
        <TaskList scope={area} key={area} prefill={prefill} clearPrefill={() => setPrefill(null)} />
      )}
      {area === 'templates' && <Templates onUse={useTemplate} />}
      {area === 'directory' && <Directory />}
      {area === 'activities' && <Activities />}
      {area === 'holidays' && <Holidays />}
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

function TaskList({ scope, prefill, clearPrefill }) {
  const { user, can } = useAuth()
  const canAssign = can('tasks.assign')
  const [rows, setRows] = useState([])
  const [team, setTeam] = useState([])
  const [leads, setLeads] = useState([])
  const [groups, setGroups] = useState([])
  const [err, setErr] = useState('')
  const [tab, setTab] = useState('open,in_progress')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [showAdd, setShowAdd] = useState(!!prefill)

  const load = useCallback(() => {
    const p = new URLSearchParams({ page_size: '200', scope })
    if (tab) p.set('status', tab)
    if (onlyOverdue) p.set('overdue', 'true')
    api(`/api/tasks/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [scope, tab, onlyOverdue])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (canAssign) api('/api/leads/assignees/').then(setTeam).catch(() => {})
    api('/api/leads/?page_size=300').then(d => setLeads(d.results || d)).catch(() => {})
    api('/api/groups/?active=true').then(setGroups).catch(() => {})
  }, [canAssign])

  const setStatus = async (t, status) => {
    setErr('')
    try { await api(`/api/tasks/${t.id}/`, { method: 'PATCH', body: { status } }); load() }
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
              onChange={e => setStatus(t, e.target.checked ? 'done' : 'open')}
              title={t.status === 'done' ? 'Reopen' : 'Mark done'}
            />
            <div className="task-main">
              <div className="task-title">
                {t.title}
                {t.category && <span className="ai-chip">{t.category}</span>}
                {t.group_name && <span className="ai-chip">👥 {t.group_name}</span>}
                {t.frequency !== 'one_time' && <span className="ai-chip">↻ {t.frequency_display}</span>}
                {t.priority !== 'normal' && <span className={`prio prio-${t.priority}`}>{t.priority_display}</span>}
              </div>
              {t.description && <div className="small muted">{t.description}</div>}
              <div className="when">
                {t.assigned_to_detail?.name}
                {scope !== 'my' && t.created_by_detail && <> · by {t.created_by_detail.name}</>}
                {t.lead_name && <> · lead: <strong>{t.lead_name}</strong></>}
                {t.due_at && <span className={t.is_overdue ? ' late' : ''}> · due {fmtDT(t.due_at)}</span>}
                {t.completed_at && <> · done {fmtDT(t.completed_at)}</>}
              </div>
            </div>
            <button
              className={'bell' + (t.subscribed ? ' on' : '')}
              title={t.subscribed ? 'Unfollow' : 'Follow this task'}
              onClick={() => toggleSub(t)}
            >🔔</button>
            {t.status !== 'done' && (
              <select value={t.status} onChange={e => setStatus(t, e.target.value)}>
                <option value="open">Open</option>
                <option value="in_progress">In Progress</option>
                <option value="done">Done</option>
              </select>
            )}
          </div>
        ))}
      </div>

      {showAdd && (
        <TaskModal
          user={user} canAssign={canAssign} team={team} leads={leads} groups={groups} template={prefill}
          onClose={() => { setShowAdd(false); clearPrefill?.() }}
          onSaved={() => { setShowAdd(false); clearPrefill?.(); load() }}
        />
      )}
    </div>
  )
}

function TaskModal({ user, canAssign, team, leads, groups = [], template, onClose, onSaved }) {
  const [f, setF] = useState({
    title: template?.title || '', description: template?.description || '',
    category: template?.category || '', frequency: template?.frequency || 'one_time',
    assigned_to: String(user.id), lead: '', group: '',
    priority: template?.priority || 'normal', due_at: '',
  })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    const body = {
      title: f.title, description: f.description, category: f.category,
      frequency: f.frequency, assigned_to: Number(f.assigned_to), priority: f.priority,
      lead: f.lead ? Number(f.lead) : null,
      group: f.group ? Number(f.group) : null,
      due_at: f.due_at ? new Date(f.due_at).toISOString() : null,
    }
    try { await api('/api/tasks/', { method: 'POST', body }); onSaved() }
    catch (ex) { setErr(errorText(ex.data) || ex.message) }
    finally { setBusy(false) }
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
            <label>Description</label>
            <input value={f.description} onChange={set('description')} />
          </div>
          <div>
            <label>Category</label>
            <input value={f.category} onChange={set('category')} placeholder="e.g. Calls, Quotes" />
          </div>
          <div>
            <label>Frequency</label>
            <select value={f.frequency} onChange={set('frequency')}>
              {FREQUENCIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Assign to</label>
            {canAssign ? (
              <select value={f.assigned_to} onChange={set('assigned_to')}>
                {team.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            ) : <input value={user.first_name || user.username} disabled />}
          </div>
          <div>
            <label>Linked lead</label>
            <select value={f.lead} onChange={set('lead')}>
              <option value="">None</option>
              {leads.map(l => <option key={l.id} value={l.id}>{l.customer_name}</option>)}
            </select>
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
            <label>Due {f.frequency !== 'one_time' && '(first occurrence)'}</label>
            <input type="datetime-local" value={f.due_at} onChange={set('due_at')} />
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !f.title.trim()}>
            {busy ? 'Saving…' : 'Create task'}
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

/* ================= Holidays ================= */

function Holidays() {
  const { can } = useAuth()
  const canManage = can('settings.manage')
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [f, setF] = useState({ name: '', date: '' })

  const load = () => api('/api/holidays/').then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const add = async () => {
    setErr('')
    try { await api('/api/holidays/', { method: 'POST', body: f }); setF({ name: '', date: '' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const remove = async (h) => {
    try { await api(`/api/holidays/${h.id}/`, { method: 'DELETE' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <div>
      {canManage && (
        <div className="filters">
          <input placeholder="Holiday name" value={f.name} onChange={e => setF(p => ({ ...p, name: e.target.value }))} />
          <input type="date" value={f.date} onChange={e => setF(p => ({ ...p, date: e.target.value }))} />
          <button className="btn btn-primary" disabled={!f.name.trim() || !f.date} onClick={add}>Add holiday</button>
        </div>
      )}
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No holidays configured.</p>}
      <table className="table" style={{ maxWidth: 480 }}>
        <thead><tr><th>Holiday</th><th>Date</th>{canManage && <th />}</tr></thead>
        <tbody>
          {rows.map(h => (
            <tr key={h.id}>
              <td><strong>{h.name}</strong></td>
              <td>{new Date(h.date + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })}</td>
              {canManage && <td className="row-actions"><button className="btn btn-sm" onClick={() => remove(h)}>Delete</button></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
