import { useEffect, useState } from 'react'
import {
  BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api } from '../api'
import { useAuth } from '../auth'
import { fmtINR } from './Leads'
import { relDue } from './Tasks'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

const ACCENT = '#0d7a5f'
const fmtDT = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export default function Home() {
  const { user, can } = useAuth()
  // The pipeline half of this page only means something to people who
  // actually work leads. Warehouse/IT/Accounts have dashboard rights but no
  // pipeline, so showing them "Total Leads 0 / Conversion 0%" was noise.
  const worksLeads = can('leads.view_all') || can('leads.view_department')
    || can('leads.view_own')
  return <Dashboard user={user} showLeads={worksLeads && can('dashboard.view')} />
}

/* Everyone has tasks, whatever their role — this is the part of the
   dashboard that is never empty for anybody. */
function MyWork({ user, can }) {
  const [tiles, setTiles] = useState(null)
  const [next, setNext] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api('/api/tasks/dashboard/?scope=my&range=all')
      .then(d => setTiles(d.tiles)).catch(e => setErr(e.message))
    api('/api/tasks/?scope=my&status=open,in_progress&page_size=6')
      .then(d => setNext(d.results || d)).catch(() => setNext([]))
  }, [])

  const isManager = can('tasks.view_all') || can('tasks.view_department')
  return (
    <>
      <div className="stats">
        <Tile label="My open tasks" value={tiles ? tiles.pending + tiles.in_progress : '—'} />
        <Tile label="Overdue" value={tiles ? tiles.overdue : '—'} alert={tiles?.overdue > 0} />
        <Tile label="In progress" value={tiles ? tiles.in_progress : '—'} />
        <Tile label="Completed" value={tiles ? tiles.completed : '—'} />
        <Tile label="Finished on time" value={tiles ? tiles.in_time : '—'} />
        <Tile label="Delayed" value={tiles ? tiles.delayed : '—'} alert={tiles?.delayed > 0} />
      </div>
      {err && <div className="err">{err}</div>}

      <div className="dash-grid">
        <div className="dash-card">
          <h3>What's next for you</h3>
          {!next && <p className="muted small">Loading…</p>}
          {next?.length === 0 && <p className="muted small">Nothing open — you're clear. 🎉</p>}
          {next?.map(t => (
            <div className="feed-row" key={t.id}>
              <span className="dot" style={{ marginTop: 6 }} />
              <div>
                <span className="t-code">{t.code}</span> <strong>{t.title}</strong>
                <div className="when">
                  {t.status_display}
                  {t.created_by_detail && <> · by {t.created_by_detail.name}</>}
                  {t.due_at && (
                    <span className={t.is_overdue ? ' late' : ''}> · {relDue(t.due_at)}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
          <a className="btn btn-sm" href="/tasks" style={{ marginTop: 10 }}>Open Tasks →</a>
        </div>

        <div className="dash-card">
          <h3>Where to go</h3>
          <p className="muted small">Your role: <strong>{user.role_display}</strong> · {user.department_display}</p>
          <ul className="dir-steps">
            <li><strong>Tasks</strong> — your work, and what you have delegated.</li>
            {isManager && <li><strong>Tasks → All Tasks</strong> — your team's workload, filtered by person.</li>}
            {isManager && <li><strong>Tasks → Requests</strong> — changes waiting for your approval.</li>}
            <li><strong>Attendance</strong> — mark yourself present and apply for leave.</li>
            <li><strong>Mistakes</strong> — log and close accountability items.</li>
            <li><strong>Notifications</strong> — everything that pinged you.</li>
          </ul>
        </div>
      </div>
    </>
  )
}

function Dashboard({ user, showLeads }) {
  const { can } = useAuth()
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!showLeads) return          // no pipeline for this role: skip the call
    api('/api/dashboard/').then(setData).catch(e => setErr(e.message))
  }, [showLeads])

  const head = (
    <div className="page-head">
      <h1>Dashboard</h1>
      <span className="muted small">
        {user.role === 'admin' ? 'All departments' : `${user.department_display} department`}
      </span>
    </div>
  )

  // Task-only roles (warehouse, accounts, IT, developers…) stop here — their
  // dashboard is their work, not a sales pipeline.
  if (!showLeads) {
    return <div>{head}<MyWork user={user} can={can} /></div>
  }

  if (err) return <div>{head}<div className="err">{err}</div><MyWork user={user} can={can} /></div>
  if (!data) return <div className="center-note">Loading dashboard…</div>

  const { tiles, status_dist, per_day, employees, sources, recent_inbound, recent_events } = data
  const maxStatus = Math.max(1, ...status_dist.map(s => s.count))

  return (
    <div>
      {head}

      <div className="stats">
        <Tile label="Total Leads" value={tiles.total} />
        <Tile label="New" value={tiles.new} />
        <Tile label="Active" value={tiles.active} />
        <Tile label="Won" value={tiles.won} />
        <Tile label="Lost" value={tiles.lost} />
      </div>
      <div className="stats">
        <Tile label="Pipeline Value" value={fmtINR(tiles.pipeline_value) || '₹0'} />
        <Tile label="Conversion" value={tiles.conversion_pct + '%'} />
        <Tile label="Pending Follow-ups" value={tiles.pending_followups} />
        <Tile label="Overdue" value={tiles.overdue} alert={tiles.overdue > 0} />
        <Tile label="Assigned Tasks" value={tiles.open_tasks} />
        <Tile label="Overdue Tasks" value={tiles.overdue_tasks} alert={tiles.overdue_tasks > 0} />
      </div>

      <div className="dash-grid">
        <div className="dash-card">
          <h3>Leads created — last 14 days</h3>
          <div className="chart-box">
            <Bar
              data={{
                labels: per_day.map(d => new Date(d.date + 'T00:00:00')
                  .toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })),
                datasets: [{
                  data: per_day.map(d => d.count),
                  backgroundColor: ACCENT,
                  borderRadius: { topLeft: 4, topRight: 4 },
                  maxBarThickness: 22,
                }],
              }}
              options={{
                responsive: true, maintainAspectRatio: false,
                plugins: { tooltip: { displayColors: false } },
                scales: {
                  x: { grid: { display: false }, ticks: { color: '#66716c', maxRotation: 0, autoSkip: true, font: { size: 11 } } },
                  y: { beginAtZero: true, ticks: { color: '#66716c', precision: 0, font: { size: 11 } }, grid: { color: '#e9ece9' }, border: { display: false } },
                },
              }}
            />
          </div>
        </div>

        <div className="dash-card">
          <h3>Pipeline by stage</h3>
          <div className="hbars">
            {status_dist.map(s => (
              <div className="hbar-row" key={s.status} title={`${s.label}: ${s.count}`}>
                <span className="hbar-label">{s.label}</span>
                <div className="hbar-track">
                  <div className="hbar-fill" style={{ width: `${(s.count / maxStatus) * 100}%` }} />
                </div>
                <span className="hbar-count">{s.count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="dash-card">
          <h3>Employee performance</h3>
          {employees.length === 0 ? <p className="muted small">No assigned leads yet.</p> : (
            <table className="mini-table">
              <thead><tr><th>Employee</th><th>Leads</th><th>Open</th><th>Won</th><th>Lost</th><th>Overdue</th><th>Tasks</th></tr></thead>
              <tbody>
                {employees.map(e => (
                  <tr key={e.id}>
                    <td><strong>{e.name}</strong> <span className="muted small">{e.role}</span></td>
                    <td>{e.total}</td><td>{e.open}</td>
                    <td className="ok">{e.won}</td><td>{e.lost}</td>
                    <td className={e.overdue ? 'late' : ''}>{e.overdue}</td>
                    <td>{e.open_tasks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="dash-card">
          <h3>Lead sources</h3>
          {sources.length === 0 ? <p className="muted small">No leads yet.</p> : (
            <table className="mini-table">
              <thead><tr><th>Source</th><th>Leads</th><th>Won</th><th>Conversion</th></tr></thead>
              <tbody>
                {sources.map(s => (
                  <tr key={s.source}>
                    <td><strong>{s.label}</strong></td>
                    <td>{s.total}</td><td className="ok">{s.won}</td><td>{s.conversion_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="dash-card">
          <h3>Recent WhatsApp / Gmail activity</h3>
          {recent_inbound.length === 0
            ? <p className="muted small">No inbound messages yet — they'll appear once the WhatsApp webhook / Gmail poller are live (or via the AI Inbox simulator).</p>
            : recent_inbound.map((m, i) => (
              <div className="feed-row" key={i}>
                <span>{m.channel === 'whatsapp' ? '💬' : '✉'}</span>
                <div>
                  <strong>{m.sender}</strong> <span className="muted small">→ {m.lead_name || m.status}</span>
                  <div className="small muted">{m.body}</div>
                  <div className="when">{fmtDT(m.created_at)}</div>
                </div>
              </div>
            ))}
        </div>

        <div className="dash-card">
          <h3>Recent lead activity</h3>
          {recent_events.map((e, i) => (
            <div className="feed-row" key={i}>
              <span className="dot" style={{ marginTop: 6 }} />
              <div>
                <strong>{e.lead_name}</strong> <span className="small muted">{e.body}</span>
                <div className="when">{e.actor} · {fmtDT(e.created_at)}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Tile({ label, value, alert }) {
  return (
    <div className={'stat' + (alert ? ' alert' : '')}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  )
}
