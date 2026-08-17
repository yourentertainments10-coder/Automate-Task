import { useEffect, useState } from 'react'
import { api } from '../api'

const fmtDT = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const TYPE_ICONS = {
  lead_assigned: '🧲', follow_up_due: '⏰', status_change: '🔁',
}

export default function Notifications({ onCountChange }) {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')

  const load = () => api('/api/notifications/?page_size=50')
    .then(d => setRows(d.results || d))
    .catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const markRead = async (n) => {
    if (n.read_at) return
    await api(`/api/notifications/${n.id}/read/`, { method: 'POST' }).catch(() => {})
    load(); onCountChange?.()
  }
  const readAll = async () => {
    await api('/api/notifications/read_all/', { method: 'POST' }).catch(() => {})
    load(); onCountChange?.()
  }

  return (
    <div>
      <div className="page-head">
        <h1>Notifications</h1>
        {rows.some(n => !n.read_at) && <button className="btn" onClick={readAll}>Mark all read</button>}
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">Nothing yet — you'll see lead assignments, follow-up reminders and status changes here.</p>}
      <div className="notif-list">
        {rows.map(n => (
          <div key={n.id} className={'notif' + (n.read_at ? '' : ' unread')} onClick={() => markRead(n)}>
            <span className="notif-icon">{TYPE_ICONS[n.type] || '🔔'}</span>
            <div className="notif-main">
              <div className="notif-title">{n.title}</div>
              {n.body && <div className="notif-body">{n.body}</div>}
              <div className="when">
                {fmtDT(n.created_at)}
                {n.channels?.map(c => (
                  <span key={c.channel} className={`ch ch-${c.status}`} title={c.detail || c.status}>
                    {c.channel === 'gmail' ? '✉' : '💬'} {c.status}
                  </span>
                ))}
              </div>
            </div>
            {!n.read_at && <span className="notif-dot" />}
          </div>
        ))}
      </div>
    </div>
  )
}
