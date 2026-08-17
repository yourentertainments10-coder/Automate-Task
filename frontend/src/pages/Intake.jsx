import { useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

const fmtDT = (iso) => iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

export default function Intake() {
  const { can } = useAuth()
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [fChannel, setFChannel] = useState('')

  const load = () => {
    const p = new URLSearchParams({ page_size: '50' })
    if (fChannel) p.set('channel', fChannel)
    api(`/api/intake/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }
  useEffect(() => { load() }, [fChannel])

  return (
    <div>
      <div className="page-head"><h1>AI Inbox</h1></div>
      <p className="muted" style={{ marginBottom: 14 }}>
        Incoming WhatsApp and Gmail messages, how the AI classified them, and the lead each became.
        Channels go live automatically once their credentials are added to <code>backend/.env</code>.
      </p>
      {can('settings.manage') && <Simulator onDone={load} />}
      <div className="filters">
        <select value={fChannel} onChange={e => setFChannel(e.target.value)}>
          <option value="">All channels</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="gmail">Gmail</option>
        </select>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No inbound messages yet.</p>}
      <div className="intake-list">
        {rows.map(m => (
          <div key={m.id} className="intake-row">
            <div className="intake-top">
              <span className={`ch-tag ch-${m.channel}`}>{m.channel === 'whatsapp' ? '💬 WhatsApp' : '✉ Gmail'}</span>
              <strong>{m.sender_name || m.sender}</strong>
              <span className="muted small">{m.sender}</span>
              <span className={`i-status i-${m.status}`}>{m.status}</span>
              <span className="when" style={{ marginLeft: 'auto' }}>{fmtDT(m.created_at)}</span>
            </div>
            {m.subject && <div className="small"><strong>{m.subject}</strong></div>}
            <div className="intake-body">{m.body}</div>
            {m.ai_result?.intent && (
              <div className="ai-chips">
                <span className="ai-chip">intent: {m.ai_result.intent}</span>
                {m.ai_result.vehicle && <span className="ai-chip">🚚 {m.ai_result.vehicle}</span>}
                {(m.ai_result.items || []).map((it, i) => (
                  <span className="ai-chip item" key={i}>{it.quantity ? `${it.quantity}x ` : ''}{it.name}</span>
                ))}
                <span className="ai-chip">priority: {m.ai_result.priority}</span>
                <span className="ai-chip">dept: {m.ai_result.department}</span>
                <span className="ai-chip provider">via {m.ai_result.provider}</span>
              </div>
            )}
            {m.lead && <div className="small" style={{ marginTop: 6 }}>→ Lead: <strong>{m.lead_name}</strong></div>}
            {m.error && <div className="err">{m.error}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function Simulator({ onDone }) {
  const [f, setF] = useState({ channel: 'whatsapp', sender: '919876543210', sender_name: 'Suresh Kumar', subject: '', body: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))

  const run = async () => {
    setErr(''); setBusy(true)
    try {
      await api('/api/intake/simulate/', { method: 'POST', body: f })
      setF(prev => ({ ...prev, body: '' }))
      onDone()
    } catch (e) { setErr(errorText(e.data) || e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="sim-card">
      <h3>Simulator <span className="muted small">(runs the real pipeline — for testing before the live webhook)</span></h3>
      <div className="sim-grid">
        <select value={f.channel} onChange={set('channel')}>
          <option value="whatsapp">WhatsApp</option>
          <option value="gmail">Gmail</option>
        </select>
        <input value={f.sender} onChange={set('sender')} placeholder={f.channel === 'whatsapp' ? 'Phone e.g. 9198…' : 'Email'} />
        <input value={f.sender_name} onChange={set('sender_name')} placeholder="Sender name" />
        {f.channel === 'gmail' && <input value={f.subject} onChange={set('subject')} placeholder="Subject" />}
      </div>
      <div className="sim-row">
        <input value={f.body} onChange={set('body')} placeholder='Try: "Need brake pad and oil filter for Tata 407."'
          onKeyDown={e => { if (e.key === 'Enter' && f.body.trim()) run() }} />
        <button className="btn btn-primary" disabled={busy || !f.body.trim() || !f.sender.trim()} onClick={run}>
          {busy ? 'Processing…' : 'Send'}
        </button>
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  )
}
