import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api, apiUpload, errorText } from '../api'
import { useAuth } from '../auth'
import ProofreadText from '../ProofreadText'
import Directory from './Directory'
import PersonProfile from './PersonProfile'
import TaskDetailPanel from './TaskDetail'
import { ChangeRequests, CompleteModal, DeletedTasks, ProgressModal, RequestChangeModal, WorkloadPanel } from './TaskExtras'
import { useDepartments } from '../useDepartments'
import FilePick from '../FilePick'

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
/* A deadline in the past is nearly always an AM/PM slip (5 PM typed as
   5 AM). The browser's own picker blocks it before anyone submits. */
export const nowForInput = () => {
  const d = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
  return d.toISOString().slice(0, 16)
}

const PRIORITIES = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High'], ['urgent', 'Urgent']]
const FREQUENCIES = [['one_time', 'One time'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly']]
const RANGES = [
  ['today', 'Today'], ['yesterday', 'Yesterday'], ['this_week', 'This Week'],
  ['last_week', 'Last Week'], ['this_month', 'This Month'], ['last_month', 'Last Month'],
  ['this_year', 'This Year'], ['all', 'All Time'],
]

export default function Tasks() {
  const { can } = useAuth()
  // Opened from a notification email: /tasks/<id> lands straight on that task
  const { taskId: deepLinked } = useParams()
  const [openTask, setOpenTask] = useState(null)
  useEffect(() => { if (deepLinked) setOpenTask(Number(deepLinked)) }, [deepLinked])
  const isAdmin = can('tasks.view_all')
  const isManager = isAdmin || can('tasks.view_department')
  // The tab is in the address, so refreshing, pressing Back, or opening a
  // link from WhatsApp all land on the tab you were actually looking at.
  const [params, setParams] = useSearchParams()
  const area = params.get('tab') || 'dashboard'
  const setArea = useCallback(v => setParams(
    v === 'dashboard' ? {} : { tab: v }, { replace: false }), [setParams])
  const [prefill, setPrefill] = useState(null)   // template -> open list with modal
  const [listPreset, setListPreset] = useState(null)  // D3: tile click-through filters
  const [inboxCount, setInboxCount] = useState(0)
  // Everyone whose tasks I may see. More than just me => I have a team, so
  // the All Tasks tab is worth showing (covers admins, department managers
  // AND anyone with direct reports).
  const [people, setPeople] = useState([])
  useEffect(() => { api('/api/tasks/people/').then(setPeople).catch(() => {}) }, [])
  const hasTeam = isManager || people.length > 1

  const refreshInbox = useCallback(() => {
    api('/api/task-change-requests/?scope=inbox&page_size=1')
      .then(d => setInboxCount(d.count ?? (d.results || d).length))
      .catch(() => {})
  }, [])
  useEffect(() => { refreshInbox() }, [refreshInbox])

  const useTemplate = (tpl) => { setPrefill(tpl); setArea('my') }

  const tabs = [
    ['dashboard', 'Dashboard'], ['my', 'My Tasks'],
    // All Tasks: everyone the viewer may see — admin the company, a manager
    // their department plus direct reports. Filter by person or department.
    ...(hasTeam ? [['all', 'All Tasks']] : []),
    ['delegated', 'Delegated'],
    ['subscribed', 'Subscribed'],
    ['requests', inboxCount > 0 ? `Requests (${inboxCount})` : 'Requests'],
    ['templates', 'Templates'], ['directory', 'Template Directory'],
    ['activities', 'Activities'],
    ...(isManager ? [['employees', 'Reports'], ['time', 'Time Report'],
                     ['disputes', 'Disputes']] : [['time', 'Time Report']]),
    ...(isAdmin ? [['deleted', 'Deleted']] : []),
  ]

  return (
    <div>
      <div className="page-head"><h1>Tasks</h1></div>
      <TabBar tabs={tabs} area={area} setArea={setArea} />
      {area === 'dashboard' && (
        <TaskDashboard onTileClick={(preset) => { setListPreset(preset); setArea(preset.area) }} />
      )}
      {['my', 'all', 'delegated', 'subscribed'].includes(area) && (
        <TaskList scope={area} key={area} prefill={prefill} people={people}
          clearPrefill={() => setPrefill(null)} preset={listPreset}
          clearPreset={() => setListPreset(null)}
          onRequestsChanged={refreshInbox} />
      )}
      {area === 'requests' && <ChangeRequests isAdmin={isAdmin} onChanged={refreshInbox} />}
      {area === 'templates' && <Templates onUse={useTemplate} />}
      {area === 'directory' && <Directory />}
      {area === 'activities' && <Activities people={people} />}
      {area === 'time' && <TimeReport />}
      {area === 'employees' && <EmployeesReport />}
      {area === 'disputes' && <DisputesReport />}
      {area === 'deleted' && <DeletedTasks />}
      {openTask && (
        <TaskDeepLink taskId={openTask} onClose={() => setOpenTask(null)} />
      )}
    </div>
  )
}

/* The task a notification email pointed at. Opens the normal detail panel,
   so replying to a query is one tap from the mail. */
function TaskDeepLink({ taskId, onClose }) {
  const { user } = useAuth()
  const [settings, setSettings] = useState({})
  useEffect(() => { api('/api/task-settings/').then(setSettings).catch(() => {}) }, [])
  return (
    <TaskDetailPanel taskId={taskId} user={user} team={[]} settings={settings}
      focusComment onClose={onClose} onChanged={() => {}} />
  )
}

/* ================= Dashboard ================= */

const TILES = [
  // last item is the denominator the share is taken against
  ['overdue', 'Overdue', 'alert', 'total'], ['pending', 'Pending', '', 'total'],
  ['in_progress', 'In Progress', '', 'total'], ['completed', 'Completed', 'good', 'total'],
  ['in_time', 'Finished on time', 'good', 'completed'],
  ['delayed', 'Finished late', 'alert', 'completed'],
]

/* Twelve tabs in a row scrolled off a phone and pushed every number below
   the fold. The four people actually use stay put; the rest live behind
   "More", which still shows which tab is active when one is chosen. */
function TabBar({ tabs, area, setArea }) {
  const [open, setOpen] = useState(false)
  const PRIMARY = 4
  const front = tabs.slice(0, PRIMARY)
  const rest = tabs.slice(PRIMARY)
  const restActive = rest.find(([v]) => v === area)
  useEffect(() => { setOpen(false) }, [area])
  if (!rest.length) {
    return (
      <div className="area-tabs">
        {front.map(([v, l]) => (
          <button key={v} className={'tab' + (area === v ? ' on' : '')}
            onClick={() => setArea(v)}>{l}</button>
        ))}
      </div>
    )
  }
  return (
    <div className="area-tabs">
      {front.map(([v, l]) => (
        <button key={v} className={'tab' + (area === v ? ' on' : '')}
          onClick={() => setArea(v)}>{l}</button>
      ))}
      <div className="tab-more">
        <button className={'tab' + (restActive ? ' on' : '')} aria-expanded={open}
          onClick={() => setOpen(o => !o)}>
          {restActive ? restActive[1] : 'More'} ▾
        </button>
        {open && (
          <>
            <div className="tab-more-veil" onClick={() => setOpen(false)} />
            <div className="tab-menu" role="menu">
              {rest.map(([v, l]) => (
                <button key={v} role="menuitem" className={area === v ? 'on' : ''}
                  onClick={() => setArea(v)}>{l}</button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* D3: preset chips + a custom from–to picker, shared by dashboard & reports */
function RangePicker({ range, setRange, custom, setCustom }) {
  return (
    <div className="filters">
      {/* Nine pills wrapped over three rows on a phone. One dropdown says the
          same thing in one line and reads the same on both screens. */}
      <select className="range-select" value={range} onChange={e => setRange(e.target.value)}
        aria-label="Date range">
        {RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        <option value="custom">Custom range…</option>
      </select>
      {range === 'custom' && (
        <>
          <input type="date" value={custom.start} onChange={e => setCustom(c => ({ ...c, start: e.target.value }))} />
          <span className="muted">to</span>
          <input type="date" value={custom.end} onChange={e => setCustom(c => ({ ...c, end: e.target.value }))} />
        </>
      )}
    </div>
  )
}

const rangeParams = (range, custom) => {
  const p = new URLSearchParams({ range })
  if (range === 'custom') { p.set('start', custom.start); p.set('end', custom.end) }
  return p
}

/* D3: which list-filters a tile click jumps to */
const TILE_PRESETS = {
  overdue: { tab: 'open,in_progress', overdue: true },
  pending: { tab: 'open,in_progress' },
  in_progress: { tab: 'open,in_progress' },
  completed: { tab: 'done' },
  in_time: { tab: 'done' },
  delayed: { tab: 'done' },
}

/* One score, drawn the same way everywhere: a ring you can read at a glance
   instead of hunting for a number in a column. */
function ScoreRing({ value, size = 34 }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  const colour = value == null ? 'var(--line)'
    : pct >= 75 ? 'var(--accent)' : pct >= 45 ? '#b45309' : 'var(--red)'
  return (
    <span className="score-ring" style={{
      width: size, height: size,
      background: `conic-gradient(${colour} ${pct * 3.6}deg, var(--line) 0)`,
    }} title={value == null ? 'Nothing scored yet' : `${pct}% on time`}>
      <span className="score-ring-in">{value == null ? '—' : Math.round(pct)}</span>
    </span>
  )
}

/* Every report tab renders THIS table — same columns, same order, so moving
   between Employees / Monthly / Groups needs no re-reading. */
function ReportTable({ rows, firstColumn, firstCell, extraHead, extraCell, empty }) {
  const pct = (n, d) => (d ? `${Math.round((100 * n) / d)}%` : '—')
  if (!rows?.length) return <p className="muted">{empty || 'Nothing in this range.'}</p>
  return (
    <div className="tablewrap">
      <table className="table report-table">
        <thead>
          <tr>
            <th>{firstColumn}</th><th>Total</th><th>Score</th>
            <th>Overdue</th><th>Pending</th><th>In-Progress</th>
            <th>In Time</th><th>Delayed</th>
            {extraHead}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.user ?? r.month ?? r.group ?? r.category ?? i}>
              <td>{firstCell(r)}</td>
              <td>{r.total}</td>
              <td><ScoreRing value={r.score} /></td>
              <td className={r.overdue ? 'late' : ''}>
                {r.overdue} <span className="muted small">({pct(r.overdue, r.total)})</span>
              </td>
              <td>{r.pending} <span className="muted small">({pct(r.pending, r.total)})</span></td>
              <td>{r.in_progress} <span className="muted small">({pct(r.in_progress, r.total)})</span></td>
              <td className="ok">{r.in_time} <span className="muted small">({pct(r.in_time, r.completed)})</span></td>
              <td className={r.delayed ? 'late' : ''}>
                {r.delayed} <span className="muted small">({pct(r.delayed, r.completed)})</span>
              </td>
              {extraCell?.(r)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TaskDashboard({ onTileClick }) {
  const { can } = useAuth()
  const hasGroup = can('tasks.view_all') || can('tasks.view_department')
  const [range, setRange] = useState('this_week')
  const [custom, setCustom] = useState({ start: '', end: '' })
  const [scope, setScope] = useState('my')
  const [category, setCategory] = useState('')
  const [search, setSearch] = useState('')
  const [view, setView] = useState('table')
  const [cats, setCats] = useState([])
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => { api('/api/tasks/categories/').then(setCats).catch(() => {}) }, [])
  useEffect(() => {
    if (range === 'custom' && (!custom.start || !custom.end)) return
    const p = rangeParams(range, custom)
    p.set('scope', scope)
    if (category) p.set('category', category)
    if (search.trim()) p.set('search', search.trim())
    api(`/api/tasks/dashboard/?${p}`).then(d => { setData(d); setErr('') }).catch(e => setErr(e.message))
  }, [range, custom, scope, category, search])

  return (
    <div>
      <RangePicker range={range} setRange={setRange} custom={custom} setCustom={setCustom} />
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
            {TILES.map(([k, l, tone, base]) => {
              const of = data.tiles[base] || 0
              const share = of ? `${data.tiles[k]} of ${of} ${base === 'completed' ? 'completed' : 'tasks'}` : '—'
              return (
                <div key={k}
                  className={'stat' + (tone === 'alert' && data.tiles[k] > 0 ? ' alert' : '')}
                  style={{ cursor: scope !== 'group' ? 'pointer' : 'default' }}
                  title={scope !== 'group' ? 'Open the matching task list' : undefined}
                  onClick={() => scope !== 'group' && onTileClick?.({
                    area: scope === 'delegated' ? 'delegated' : 'my', ...TILE_PRESETS[k],
                  })}>
                  <div className="label">{l}</div>
                  <div className="value">{data.tiles[k]}</div>
                  <div className="small muted">{share}</div>
                </div>
              )
            })}
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

function TaskList({ scope, prefill, people = [], clearPrefill, preset, clearPreset, onRequestsChanged }) {
  const { user } = useAuth()
  const [rows, setRows] = useState([])
  const [team, setTeam] = useState([])        // hierarchy-filtered: who I may assign to
  const [groups, setGroups] = useState([])
  const [settings, setSettings] = useState({})
  const [err, setErr] = useState('')
  const [tab, setTab] = useState(preset?.tab ?? 'open,in_progress')
  const [onlyOverdue, setOnlyOverdue] = useState(!!preset?.overdue)
  // D3 tile click-through: apply the tile's filters once, then forget them
  useEffect(() => {
    if (preset) {
      setTab(preset.tab ?? 'open,in_progress')
      setOnlyOverdue(!!preset.overdue)
      clearPreset?.()
    }
  }, [preset])  // eslint-disable-line react-hooks/exhaustive-deps
  const [onlyRecurring, setOnlyRecurring] = useState(false)
  // "All Tasks" only: who / which department / free-text search
  const [fPerson, setFPerson] = useState('')
  const [fDept, setFDept] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [profileFor, setProfileFor] = useState(null)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(id)
  }, [search])
  const [showAdd, setShowAdd] = useState(!!prefill)
  const [completing, setCompleting] = useState(null)   // task in the evidence modal
  const [progressFor, setProgressFor] = useState(null) // task in the status-update modal (P1)
  const [requestFor, setRequestFor] = useState(null)   // task in the request-change modal
  const [detailFor, setDetailFor] = useState(null)     // task in the detail slide-over (E1)

  const load = useCallback(() => {
    const p = new URLSearchParams({ page_size: '200', scope })
    if (tab) p.set('status', tab)
    if (onlyOverdue) p.set('overdue', 'true')
    if (onlyRecurring) p.set('recurring', 'true')
    if (scope === 'all') {
      if (fPerson) p.set('assigned_to', fPerson)
      if (fDept) p.set('department', fDept)
      if (debounced) p.set('search', debounced)
    }
    api(`/api/tasks/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [scope, tab, onlyOverdue, onlyRecurring, fPerson, fDept, debounced])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    api('/api/tasks/assignees/').then(setTeam).catch(() => {})
    api('/api/groups/?active=true').then(setGroups).catch(() => {})
    api('/api/task-settings/').then(setSettings).catch(() => {})
  }, [])
  // department dropdown lists only departments that actually have people
  const deptOptions = useMemo(() => {
    const seen = new Map()
    people.forEach(p => { if (p.department) seen.set(p.department, p.department_display) })
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [people])
  const shownPeople = useMemo(
    () => (fDept ? people.filter(p => p.department === fDept) : people), [people, fDept])

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
    all: 'No tasks match these filters.',
    delegated: 'No tasks you delegated to others here.',
    subscribed: 'You are not following any tasks. Use the 🔔 on a task to follow it.',
  }[scope]

  // headline counts for the filtered set — "kitne pending, kitne overdue"
  const counts = useMemo(() => ({
    total: rows.length,
    overdue: rows.filter(t => t.is_overdue && t.status !== 'done').length,
    pending: rows.filter(t => t.status === 'open').length,
    in_progress: rows.filter(t => t.status === 'in_progress').length,
    done: rows.filter(t => t.status === 'done').length,
  }), [rows])

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
        {/* All Tasks is a read-across view — create tasks from My Tasks */}
        {scope !== 'all' && (
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add Task</button>
        )}
      </div>

      {scope === 'all' && (
        <div className="filters">
          <select value={fDept} onChange={e => {
            setFDept(e.target.value)
            setFPerson('')          // person list narrows to the new department
          }}>
            <option value="">All departments</option>
            {deptOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select value={fPerson} onChange={e => setFPerson(e.target.value)}>
            <option value="">
              {fDept ? 'Everyone in this department' : 'All people'}
            </option>
            {shownPeople.map(p => (
              <option key={p.id} value={p.id}>{p.name} — {p.role_display}</option>
            ))}
          </select>
          <input type="search" placeholder="Search task, code or person…"
            value={search} onChange={e => setSearch(e.target.value)} />
          {(fPerson || fDept || search) && (
            <button className="btn btn-sm" onClick={() => {
              setFPerson(''); setFDept(''); setSearch('')
            }}>Clear</button>
          )}
          {fPerson && (
            <button className="btn btn-sm" title="Open this person's full profile"
              onClick={() => setProfileFor({
                id: Number(fPerson),
                name: people.find(p => String(p.id) === String(fPerson))?.name || '',
              })}>👤 Profile</button>
          )}
        </div>
      )}

      {scope === 'all' && rows.length > 0 && (
        <p className="muted small">
          <strong>{counts.total}</strong> tasks · {counts.pending} pending ·{' '}
          {counts.in_progress} in progress · {counts.done} completed ·{' '}
          <span className={counts.overdue ? 'late' : ''}>{counts.overdue} overdue</span>
        </p>
      )}

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
            <div className="task-main" style={{ cursor: 'pointer' }}
              title="Open task details" onClick={() => setDetailFor(t)}>
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
              {t.description && <div className="small muted prose">{t.description}</div>}
              {t.completion_note && <div className="small muted">📝 {t.completion_note}</div>}
              <div className="when">
                {scope === 'all' && t.assigned_to_detail ? (
                  <button className="link-name" title="Open this person's full profile"
                    onClick={e => {
                      e.stopPropagation()
                      setProfileFor({ id: t.assigned_to, name: t.assigned_to_detail.name })
                    }}>{t.assigned_to_detail.name}</button>
                ) : t.assigned_to_detail?.name}
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
              <button className="btn btn-sm icon-act"
                data-tip={user.capabilities?.includes('tasks.view_all')
                  ? 'Edit this task' : 'Ask to change this task'}
                title={user.capabilities?.includes('tasks.view_all')
                  ? 'Edit this task (admin — applies immediately)'
                  : 'Propose a change (deadline, effort, recurrence…) for approval'}
                onClick={() => setRequestFor(t)}>
                <span aria-hidden="true">✎</span>
                <span className="icon-act-word">
                  {user.capabilities?.includes('tasks.view_all') ? 'Edit' : 'Change'}
                </span>
              </button>
            )}
            <button
              className={'bell btn btn-sm icon-act' + (t.subscribed ? ' on' : '')}
              data-tip={t.subscribed ? 'Unfollow' : 'Follow this task'}
              title={t.subscribed ? 'Unfollow' : 'Follow this task'}
              onClick={() => toggleSub(t)}>
              <span aria-hidden="true">🔔</span>
              <span className="icon-act-word">{t.subscribed ? 'Following' : 'Follow'}</span>
            </button>
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
      {detailFor && (
        <TaskDetailPanel taskId={detailFor.id} user={user} team={team} settings={settings}
          onClose={() => setDetailFor(null)} onChanged={load} />
      )}
      {profileFor && (
        <PersonProfile userId={profileFor.id} name={profileFor.name}
          onClose={() => setProfileFor(null)} />
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

/* Dropdown with checkboxes + name search — used for Assign to and Loop */
function MultiSelect({ options, selected, onChange, placeholder }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const picked = options.filter(o => selected.includes(o.id))
  const label = picked.length === 0 ? (placeholder || '— select —')
    : picked.length <= 2 ? picked.map(o => o.name).join(', ')
    : `${picked.length} selected`
  const shown = q.trim()
    ? options.filter(o => o.name.toLowerCase().includes(q.trim().toLowerCase()))
    : options
  const close = () => { setOpen(false); setQ('') }
  return (
    <div style={{ position: 'relative' }}>
      <button type="button" onClick={() => open ? close() : setOpen(true)}
        style={{
          width: '100%', textAlign: 'left', border: '1px solid var(--line)',
          borderRadius: 9, padding: '9px 11px', background: 'var(--surface)',
          cursor: 'pointer', color: picked.length ? 'inherit' : 'var(--muted)',
        }}>
        {label}<span style={{ float: 'right', color: 'var(--muted)' }}>▾</span>
      </button>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 9 }} onClick={close} />
          <div style={{
            position: 'absolute', zIndex: 10, top: '104%', left: 0, right: 0,
            background: 'var(--surface)', border: '1px solid var(--line)',
            borderRadius: 9, boxShadow: '0 8px 24px rgba(20,32,28,.18)', padding: 6,
          }}>
            <input type="search" placeholder="🔍 Search name…" value={q} autoFocus
              onChange={e => setQ(e.target.value)}
              style={{
                width: '100%', border: '1px solid var(--line)', borderRadius: 7,
                padding: '6px 9px', marginBottom: 6, fontSize: 13,
              }} />
            <div style={{ maxHeight: 180, overflowY: 'auto' }}>
              {shown.length === 0 && (
                <div className="muted small" style={{ padding: '6px 8px' }}>No one matches “{q}”.</div>
              )}
              {shown.map(o => (
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
          </div>
        </>
      )}
    </div>
  )
}

function TaskModal({ user, team, groups = [], template, onClose, onSaved }) {
  const DEPARTMENTS = useDepartments()
  const { can } = useAuth()
  const canAddCategory = can('tasks.assign')
  const [catBox, setCatBox] = useState(null)     // null = closed, '' = typing
  const [catNote, setCatNote] = useState('')

  const submitCategory = async () => {
    const name = (catBox || '').trim()
    if (!name) return
    setErr(''); setCatNote('')
    try {
      const cat = await api('/api/task-categories/', {
        method: 'POST', body: { name, department: f.department },
      })
      setCatBox(null)
      if (cat.pending) {
        setCatNote(`Sent — "${cat.name}" is waiting for your manager's approval.`)
      } else {
        setCategories(prev => [...prev.filter(c => c.id !== cat.id), cat])
        setF(prev => ({ ...prev, category: cat.name }))
      }
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }
  const [f, setF] = useState({
    title: template?.title || '', description: template?.description || '',
    category: template?.category || '', frequency: template?.frequency || 'one_time',
    department: user.department === 'management' ? '' : (user.department || ''),
    group: '',
    priority: template?.priority || 'normal', due_at: '', repeat_until: '',
    effort: '', effort_unit: 'minutes',
  })
  const [assignees, setAssignees] = useState([])   // nobody pre-picked — see the note in submit()
  const [categories, setCategories] = useState([])
  const [inLoop, setInLoop] = useState([])          // Loop: colleagues who follow the task
  const [workloads, setWorkloads] = useState([])    // C1: pipeline per picked assignee
  const [aiPrompt, setAiPrompt] = useState(null)    // E3: null = closed
  // The assigner breaks the task into steps here; the assignee ticks them
  // off one by one and cannot complete the task until all are done.
  const [steps, setSteps] = useState([])
  const [stepDraft, setStepDraft] = useState('')
  // Optional reference files the assignee needs to DO the work — an invoice,
  // a photo, a spec. Not the completion proof, which is collected at the end.
  const [attachments, setAttachments] = useState([])
  const addStep = () => {
    const t = stepDraft.trim()
    if (!t) return
    setSteps(prev => [...prev, t].slice(0, 30))
    setStepDraft('')
  }
  const moveStep = (i, by) => setSteps(prev => {
    const next = [...prev]
    const j = i + by
    if (j < 0 || j >= next.length) return prev
    ;[next[i], next[j]] = [next[j], next[i]]
    return next
  })
  const [aiBusy, setAiBusy] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))

  const aiDraft = async () => {
    if (!aiPrompt?.trim()) return
    setAiBusy(true); setErr('')
    try {
      const d = await api('/api/tasks/ai_draft/', { method: 'POST', body: { prompt: aiPrompt } })
      setF(prev => ({ ...prev, title: d.title, description: d.description }))
      setSteps(prev => [...prev, ...(d.checklist || [])].slice(0, 30))
      setAiPrompt(null)
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
    finally { setAiBusy(false) }
  }

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
    if (!assignees.length) {
      setErr('Pick who this task is for — nobody is selected by default.')
      setBusy(false)
      return
    }
    // one INDIVIDUAL task per picked assignee — each completes their own
    let created = 0
    try {
      for (const id of assignees) {
        const made = await api('/api/tasks/', {
          method: 'POST',
          body: {
            ...base, assigned_to: id, checklist: steps,
            in_loop: inLoop.filter(x => x !== id),
          },
        })
        if (attachments.length) {
          const fd = new FormData()
          attachments.forEach(f => fd.append('file', f))
          await apiUpload(`/api/tasks/${made.id}/upload/`, fd)
        }
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
      <form className="modal-card task-form" onSubmit={submit}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {template ? `New task from "${template.name}"` : 'Add Task'}
          <span style={{ flex: 1 }} />
          <button type="button" className="btn btn-sm"
            title="Describe the task in your words — AI drafts title, description & checklist"
            onClick={() => setAiPrompt(p => p === null ? '' : null)}>✨ AI draft</button>
        </h2>
        {aiPrompt !== null && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            <input value={aiPrompt} autoFocus style={{ flex: 1 }}
              placeholder="e.g. Ravi ko brake pads ke baare mein call karo, phir quotation bhejo"
              onChange={e => setAiPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); aiDraft() } }} />
            <button type="button" className="btn btn-sm btn-primary" disabled={aiBusy}
              onClick={aiDraft}>{aiBusy ? '…' : 'Generate'}</button>
          </div>
        )}
        <div className="form-grid">
          <div className="wide">
            <label>Title *</label>
            <input value={f.title} onChange={set('title')} autoFocus placeholder="e.g. Call Ravi with revised quote" />
          </div>
          <div className="wide">
            <ProofreadText label="Description *" value={f.description} rows={4} required
              onChange={v => setF(prev => ({ ...prev, description: v }))}
              placeholder="What exactly has to be done?&#10;Press Enter for a new line — write as many points as you need." />
          </div>
          <div>
            <label>Assign to *</label>
            <div className="hint">Your level and below. Each person gets their own copy.</div>
            <MultiSelect options={team} selected={assignees} onChange={setAssignees}
              placeholder="— pick people —" />
            {assignees.length === 0 && (
              <button type="button" className="btn btn-sm" style={{ marginTop: 4 }}
                onClick={() => setAssignees([user.id])}>Assign to myself</button>
            )}
          </div>
          <div>
            <label>Due * {f.frequency !== 'one_time' && '(first occurrence)'}</label>
            <input type="datetime-local" value={f.due_at} onChange={set('due_at')}
              min={nowForInput()} required />
            {f.due_at && new Date(f.due_at) <= new Date() && (
              <div className="err" style={{ margin: '4px 0 0' }}>
                That time has already passed — check AM/PM.
              </div>
            )}
          </div>
          <div>
            <label>Effort *</label>
            <div className="hint">How long should this take?</div>
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
            <label>Category *</label>
            {catBox === null ? (
              <div style={{ display: 'flex', gap: 6 }}>
                <select value={f.category} onChange={set('category')} style={{ flex: 1 }}>
                  <option value="">— pick a category —</option>
                  {categories.map(c => (
                    <option key={c.id} value={c.name}>
                      {c.name}{c.department ? '' : ' (general)'}
                    </option>
                  ))}
                </select>
                {/* managers/admin add outright; everyone else asks for it */}
                <button type="button" className="btn btn-sm"
                  title={canAddCategory ? 'Add a new category'
                    : 'Ask your manager to add a new category'}
                  onClick={() => setCatBox('')}>
                  {canAddCategory ? '+' : '+ request'}
                </button>
              </div>
            ) : (
              <div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input value={catBox} onChange={e => setCatBox(e.target.value)} autoFocus
                    placeholder={canAddCategory ? 'New category name' : 'Category you need…'}
                    style={{ flex: 1 }}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submitCategory() } }} />
                  <button type="button" className="btn btn-sm btn-primary"
                    onClick={submitCategory}>{canAddCategory ? 'Add' : 'Send request'}</button>
                  <button type="button" className="btn btn-sm" onClick={() => setCatBox(null)}>✕</button>
                </div>
                <div className="muted small">
                  {canAddCategory
                    ? 'It goes straight into the list for everyone.'
                    : 'Your manager gets this and approves it — pick an existing category for now.'}
                </div>
                {catNote && <div className="muted small"><strong>{catNote}</strong></div>}
              </div>
            )}
          </div>
          {workloads.length > 0 && (
            <div className="wide">
              {workloads.map(w => <WorkloadPanel key={w.user} w={w} />)}
            </div>
          )}
          <div>
            <label>Department</label>
            <select value={f.department} onChange={set('department')}>
              <option value="">General (no department)</option>
              {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Frequency</label>
            <select value={f.frequency} onChange={set('frequency')}>
              {FREQUENCIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          {f.frequency !== 'one_time' && (
            <div>
              <label>Repeat until</label>
              <div className="hint">Optional — leave blank to repeat forever.</div>
              <input type="date" value={f.repeat_until} onChange={set('repeat_until')} />
            </div>
          )}
          <div>
            <label>Priority</label>
            <select value={f.priority} onChange={set('priority')}>
              {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
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
            <label>Loop</label>
            <div className="hint">Colleagues who follow this task, but are not doing it.</div>
            <MultiSelect options={team.filter(a => a.id !== user.id)}
              selected={inLoop} onChange={setInLoop} placeholder="— optional —" />
          </div>
        </div>
        {/* Optional, so they sit below the required fields and stay
            shut until wanted -- they used to fill the first phone screen. */}
        <details className="opt-box">
          <summary>Steps to finish this task
            <span className="muted small">
              {steps.length ? `${steps.length} step${steps.length === 1 ? '' : 's'} added`
                : 'optional — a big task is easier one step at a time'}
            </span>
          </summary>
            {steps.length > 0 && (
              <ol className="steps-list">
                {steps.map((s, i) => (
                  <li key={i}>
                    <span className="steps-text">{s}</span>
                    <span className="steps-actions">
                      <button type="button" className="btn btn-sm" title="Move up"
                        onClick={() => moveStep(i, -1)} disabled={i === 0}>↑</button>
                      <button type="button" className="btn btn-sm" title="Move down"
                        onClick={() => moveStep(i, 1)}
                        disabled={i === steps.length - 1}>↓</button>
                      <button type="button" className="btn btn-sm" title="Remove"
                        onClick={() => setSteps(prev => prev.filter((_, k) => k !== i))}>✕</button>
                    </span>
                  </li>
                ))}
              </ol>
            )}
            <div className="steps-add">
              <input value={stepDraft} onChange={e => setStepDraft(e.target.value)}
                placeholder="e.g. Collect the invoice copy from accounts"
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addStep() } }} />
              <button type="button" className="btn btn-sm btn-primary"
                disabled={!stepDraft.trim()} onClick={addStep}>+ Add step</button>
            </div>
            {steps.length > 0 && (
              <p className="muted small" style={{ margin: '6px 0 0' }}>
                The assignee ticks each step with a note on what they did, and can only
                mark the task complete once every step is done.
              </p>
            )}
        </details>
        <details className="opt-box">
          <summary>Attachments
            <span className="muted small">
              {attachments.length ? `${attachments.length} file${attachments.length === 1 ? '' : 's'} attached`
                : 'optional — invoice, photo, anything they need'}
            </span>
          </summary>
            <FilePick onPick={picked =>
              setAttachments(prev => [...prev, ...picked]
                .filter((f, i, all) => all.findIndex(x => x.name === f.name && x.size === f.size) === i)
                .slice(0, 5))} />
            {attachments.length > 0 && (
              <ul className="steps-list">
                {attachments.map((f, i) => (
                  <li key={i}>
                    <span className="steps-text">📎 {f.name}
                      <span className="muted small"> · {Math.round(f.size / 1024)} KB</span>
                    </span>
                    <span className="steps-actions">
                      <button type="button" className="btn btn-sm" title="Remove"
                        onClick={() => setAttachments(p => p.filter((_, k) => k !== i))}>✕</button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="muted small" style={{ margin: '6px 0 0' }}>
              Up to 5 files, 10 MB each. Everyone on the task can open them.
            </p>
        </details>
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
          <div className="wide">
            <ProofreadText label="Description" value={f.description} rows={3}
              onChange={v => setF(prev => ({ ...prev, description: v }))} /></div>
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

function Activities({ people = [] }) {
  const { user } = useAuth()
  const [rows, setRows] = useState([])
  const [days, setDays] = useState('7')
  const [who, setWho] = useState('')         // whose TASK the activity is on
  const [actor, setActor] = useState('')     // who performed it
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [detailFor, setDetailFor] = useState(null)   // click a row -> open the task
  const [err, setErr] = useState('')

  useEffect(() => {
    const id = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(id)
  }, [search])
  const [counts, setCounts] = useState([])

  const load = useCallback(() => {
    const p = new URLSearchParams({ page_size: '100' })
    if (days) p.set('days', days)
    if (who) p.set('assigned_to', who)
    if (debounced) p.set('search', debounced)
    const withActor = new URLSearchParams(p)
    if (actor) withActor.set('actor', actor)
    api(`/api/task-activities/?${withActor}`)
      .then(d => setRows(d.results || d)).catch(e => setErr(e.message))
    // the chips deliberately ignore the actor filter — they ARE the actor picker
    api(`/api/task-activities/counts/?${p}`).then(setCounts).catch(() => {})
  }, [days, who, actor, debounced])
  useEffect(() => { load() }, [load])

  return (
    <div>
      <div className="filters">
        <div className="seg">
          {[['1', 'Today'], ['7', '7 days'], ['30', '30 days'], ['', 'All']].map(([v, l]) => (
            <button key={l} className={'seg-btn' + (days === v ? ' on' : '')} onClick={() => setDays(v)}>{l}</button>
          ))}
        </div>
        {people.length > 1 && (
          <>
            <select value={who} onChange={e => setWho(e.target.value)}>
              <option value="">Whose task — anyone</option>
              {people.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select value={actor} onChange={e => setActor(e.target.value)}>
              <option value="">Done by — anyone</option>
              {people.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </>
        )}
        <input type="search" placeholder="Search activity or task…"
          value={search} onChange={e => setSearch(e.target.value)} />
        {(who || actor || search) && (
          <button className="btn btn-sm"
            onClick={() => { setWho(''); setActor(''); setSearch('') }}>Clear</button>
        )}
      </div>
      {counts.length > 0 && (
        <div className="who-chips">
          {counts.map(c => {
            const initials = c.name.split(' ').filter(Boolean).slice(0, 2)
              .map(w => w[0]).join('').toUpperCase()
            const on = String(actor) === String(c.user)
            return (
              <button key={c.user} className={'who-chip' + (on ? ' on' : '')}
                title={on ? `Showing only ${c.name} — click to clear` : `Show only ${c.name}`}
                onClick={() => setActor(on ? '' : String(c.user))}>
                <span className="av">{initials}</span>
                {c.name}<span className="n">{c.count}</span>
              </button>
            )
          })}
        </div>
      )}
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No task activity in this window.</p>}
      <div className="dash-card" style={{ maxWidth: 720 }}>
        {rows.map(a => (
          <div className="feed-row" key={a.id} style={{ cursor: a.task ? 'pointer' : 'default' }}
            title={a.task ? 'Open this task' : ''}
            onClick={() => a.task && setDetailFor(a.task)}>
            <span className="dot" style={{ marginTop: 6 }} />
            <div>
              {a.task_code && <span className="t-code">{a.task_code}</span>}{' '}
              <strong>{a.task_title}</strong> <span className="small muted">{a.text}</span>
              <div className="when">
                {a.actor?.name || 'System'} · {fmtDT(a.created_at)}
                {a.task_assignee && <> · task of {a.task_assignee}</>}
              </div>
            </div>
          </div>
        ))}
      </div>
      {detailFor && (
        <TaskDetailPanel taskId={detailFor} user={user} team={[]} settings={{}}
          onClose={() => setDetailFor(null)} onChanged={load} />
      )}
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

/* ================= Employees report (D2/D3/D4) ================= */

const downloadCSV = (filename, header, rows) => {
  const esc = v => `"${String(v ?? '').replace(/"/g, '""')}"`
  const csv = [header, ...rows].map(r => r.map(esc).join(',')).join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

const REPORT_TABS = [
  ['person', 'Employees'], ['category', 'Categories'], ['mine', 'My Report'],
  ['delegated', 'Delegated'], ['daily', 'Daily'], ['monthly', 'Monthly'],
  ['overdue', 'OverDue'], ['group', 'Groups'],
]

/* Every report in one place, all reading the same table. Previously these
   lived across three separate tabs with three different column sets. */
function EmployeesReport() {
  const { user, can } = useAuth()
  const [tab, setTab] = useState('person')
  const [range, setRange] = useState('this_month')
  const [custom, setCustom] = useState({ start: '', end: '' })
  const [data, setData] = useState(null)
  const [person, setPerson] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (range === 'custom' && (!custom.start || !custom.end)) return
    setData(null)
    const p = rangeParams(range, custom)
    // Employees / My Report / Delegated all use the per-person grain; the
    // rest ask the server for their own grouping.
    if (!['person', 'mine', 'delegated', 'category'].includes(tab)) p.set('grain', tab)
    if (tab === 'mine') p.set('user', String(user.id))
    const url = tab === 'category' || tab === 'delegated'
      ? `/api/tasks/dashboard/?${p}${tab === 'delegated' ? '&scope=delegated' : ''}`
      : `/api/tasks/employees_report/?${p}`
    api(url).then(d => { setData(d); setErr('') })
      .catch(e => setErr(errorText(e.data) || e.message))
  }, [tab, range, custom, user.id])

  const rows = data?.rows || data?.categories || []

  const exportCSV = () => {
    const head = ['Name', 'Total', 'Score', 'Overdue', 'Pending', 'In progress',
                  'Completed', 'In time', 'Delayed']
    downloadCSV(`report-${tab}-${range}.csv`, head, rows.map(r => [
      r.name || r.label || r.group || r.category, r.total, r.score ?? '',
      r.overdue, r.pending, r.in_progress, r.completed, r.in_time, r.delayed]))
  }

  const firstCell = (r) => {
    if (tab === 'monthly') return <strong>{r.label}</strong>
    if (tab === 'group') return <strong>{r.group}</strong>
    if (tab === 'category') return <strong>{r.category}</strong>
    return (
      <>
        <button className="link-name" title="Open this person's full profile"
          onClick={() => setPerson({ user: r.user, name: r.name })}>{r.name}</button>
        {r.self_assigned > 0 && (
          <span className="ai-chip" title="Created for themselves — not scored">
            {r.self_assigned} self-assigned
          </span>
        )}
        {r.review && <div className="muted small">💡 {r.review}</div>}
      </>
    )
  }

  return (
    <div>
      <div className="report-tabs">
        {REPORT_TABS.map(([v, l]) => (
          <button key={v} className={'seg-btn' + (tab === v ? ' on' : '')}
            onClick={() => setTab(v)}>{l}</button>
        ))}
      </div>
      <RangePicker range={range} setRange={setRange} custom={custom} setCustom={setCustom} />
      <div className="filters">
        <span style={{ flex: 1 }} />
        {rows.length > 0 && (
          <button className="btn btn-sm" onClick={exportCSV}>⬇ Export CSV</button>
        )}
      </div>
      {err && <div className="err">{err}</div>}
      {!data && !err && <p className="muted">Loading…</p>}

      {data && tab === 'daily' && (
        <ReportTable rows={rows.map(r => ({ ...r, total: r.completed }))}
          firstColumn="Date" empty="Nothing completed in this range."
          firstCell={r => <strong>{new Date(r.date + 'T00:00:00')
            .toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</strong>} />
      )}
      {data && tab === 'overdue' && (
        <ReportTable rows={rows} firstColumn="Employee"
          empty="Nobody is overdue right now. 🎉"
          firstCell={firstCell}
          extraHead={<th>Overdue Since</th>}
          extraCell={r => (
            <td className="late">
              {r.days_overdue === 0 ? 'today'
                : r.days_overdue < 30 ? `${r.days_overdue} days ago`
                : `${Math.round(r.days_overdue / 30)} month(s) ago`}
            </td>
          )} />
      )}
      {data && !['daily', 'overdue'].includes(tab) && (
        <ReportTable rows={rows} firstCell={firstCell}
          firstColumn={{ monthly: 'Month', group: 'Group', category: 'Category' }[tab] || 'Employee'}
          empty={tab === 'mine' ? 'You have no tasks in this range.' : undefined} />
      )}

      {data?.formula && ['person', 'mine'].includes(tab) && (
        <p className="muted small" style={{ marginTop: 10 }}>
          Formula (open, not a black box): <strong>{data.formula}</strong>.
        </p>
      )}
      {person && (
        <PersonProfile userId={person.user} name={person.name}
          onClose={() => setPerson(null)} />
      )}
    </div>
  )
}


/* ================= Effort disputes (D5) ================= */

function DisputesReport() {
  const [range, setRange] = useState('this_month')
  const [custom, setCustom] = useState({ start: '', end: '' })
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (range === 'custom' && (!custom.start || !custom.end)) return
    api(`/api/tasks/effort_disputes/?${rangeParams(range, custom)}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(errorText(e.data) || e.message))
  }, [range, custom])
  if (err) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading…</div>
  return (
    <div style={{ maxWidth: 860 }}>
      <RangePicker range={range} setRange={setRange} custom={custom} setCustom={setCustom} />
      <p className="muted small">
        Where the assigner and the assignee disagreed on how long a task takes —
        &ldquo;Amit said 1 hour, Bhavna said 4&rdquo;. Sorted by the size of the
        disagreement; the Actual column settles the argument.
      </p>
      {data.rows.length === 0 && <p className="muted">No disputes in this range — everyone agrees. 🎉</p>}
      {data.rows.length > 0 && (
        <table className="table">
          <thead><tr><th>Task</th><th>Assignee</th><th>Assigner said</th><th>Assignee said</th><th>Actually took</th><th>Status</th></tr></thead>
          <tbody>
            {data.rows.map(r => (
              <tr key={r.id}>
                <td><span className="t-code">{r.code}</span> <strong>{r.title}</strong>
                  <div className="muted small">assigned by {r.assigner}</div></td>
                <td>{r.assignee}</td>
                <td>{fmtEffort(r.effort_minutes)}</td>
                <td className={r.estimate_minutes > r.effort_minutes ? 'late' : 'ok'}>
                  {fmtEffort(r.estimate_minutes)}</td>
                <td><strong>{r.actual_minutes ? fmtEffort(r.actual_minutes) : '—'}</strong></td>
                <td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* Holidays moved to the Attendance page (HR.jsx) — reviewer feedback. */
