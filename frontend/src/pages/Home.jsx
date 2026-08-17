import { useEffect, useState } from 'react'
import {
  BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { api } from '../api'
import { useAuth } from '../auth'
import { fmtINR } from './Leads'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

const ACCENT = '#0d7a5f'
const fmtDT = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export default function Home() {
  const { user, can } = useAuth()
  if (!can('dashboard.view')) return <Welcome user={user} />
  return <Dashboard user={user} />
}

function Welcome({ user }) {
  return (
    <div>
      <h1>Welcome, {user.first_name || user.username}</h1>
      <p className="muted">
        Signed in as <strong>{user.role_display}</strong> · {user.department_display} department.
      </p>
      <div className="placeholder-card">
        <h3>Your workspace</h3>
        <p>Use <strong>Leads</strong> to work your pipeline and <strong>Notifications</strong> for
          assignments and follow-up reminders. Your role's permissions:</p>
        <div className="cap-list">
          {user.capabilities.map(c => <code key={c}>{c}</code>)}
        </div>
      </div>
    </div>
  )
}

function Dashboard({ user }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api('/api/dashboard/').then(setData).catch(e => setErr(e.message))
  }, [])

  if (err) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading dashboard…</div>

  const { tiles, status_dist, per_day, employees, sources, recent_inbound, recent_events } = data
  const maxStatus = Math.max(1, ...status_dist.map(s => s.count))

  return (
    <div>
      <div className="page-head">
        <h1>Dashboard</h1>
        <span className="muted small">
          {user.role === 'admin' ? 'All departments' : `${user.department_display} department`}
        </span>
      </div>

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
