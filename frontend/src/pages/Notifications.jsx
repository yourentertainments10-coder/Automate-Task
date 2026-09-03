import { useEffect, useState } from 'react'
import { api, errorText } from '../api'

const fmtDT = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const TYPE_ICONS = {
  lead_assigned: '🧲', follow_up_due: '⏰', status_change: '🔁',
}

export default function Notifications({ onCountChange }) {
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(false)
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

  // Deleting for good, so it asks first and says exactly how many go.
  const clear = async (onlyRead) => {
    const n = onlyRead ? rows.filter(r => r.read_at).length : rows.length
    const unread = rows.filter(r => !r.read_at).length
    const warn = onlyRead
      ? `Delete ${n} notification${n === 1 ? '' : 's'} you have already read?`
      : `Delete all ${n} notification${n === 1 ? '' : 's'}?`
        + (unread ? `\n\n${unread} of them ${unread === 1 ? 'is' : 'are'} still unread.` : '')
    if (!window.confirm(`${warn}\n\nThis cannot be undone.`)) return
    setErr(''); setBusy(true)
    try {
      await api(`/api/notifications/clear/${onlyRead ? '?only=read' : ''}`, { method: 'POST' })
      await load(); onCountChange?.()
    } catch (e) { setErr(errorText(e.data) || e.message) }
    finally { setBusy(false) }
  }

  const deleteOne = async (e, n) => {
    e.stopPropagation()
    setErr('')
    try {
      await api(`/api/notifications/${n.id}/`, { method: 'DELETE' })
      await load(); onCountChange?.()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  return (
    <div>
      <div className="page-head">
        <h1>Notifications</h1>
        <span style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {rows.some(n => !n.read_at) && (
            <button className="btn" onClick={readAll} disabled={busy}>Mark all read</button>
          )}
          {rows.some(n => n.read_at) && (
            <button className="btn" onClick={() => clear(true)} disabled={busy}>Clear read</button>
          )}
          {rows.length > 0 && (
            <button className="btn btn-danger" onClick={() => clear(false)} disabled={busy}>
              {busy ? 'Clearing…' : 'Clear all'}
            </button>
          )}
        </span>
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
            <button className="btn btn-sm notif-del" title="Delete this notification"
              onClick={e => deleteOne(e, n)}>✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}
