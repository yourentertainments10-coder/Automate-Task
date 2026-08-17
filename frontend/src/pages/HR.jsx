import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

const fmtT = (iso) => iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—'
const fmtD = (d) => new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const hrs = (m) => m ? `${Math.floor(m / 60)}h ${m % 60}m` : '—'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const STATUS_LABEL = {
  present: 'Present', absent: 'Absent', half_day: 'Half Day', late: 'Late',
  leave: 'Leave', holiday: 'Holiday', week_off: 'Week Off', not_checked_in: 'Not checked in',
}

export default function HR() {
  const { can } = useAuth()
  const [tab, setTab] = useState('today')
  const tabs = [
    ['today', 'Today'], ['history', 'My Attendance'], ['leave', 'My Leave'],
    ...(can('hr.approve') ? [['team', 'Team'], ['approvals', 'Approvals']] : []),
    ...(can('hr.manage') ? [['settings', 'HR Settings']] : []),
  ]
  return (
    <div>
      <div className="page-head"><h1>Leave &amp; Attendance</h1></div>
      <div className="area-tabs">
        {tabs.map(([v, l]) => (
          <button key={v} className={'tab' + (tab === v ? ' on' : '')} onClick={() => setTab(v)}>{l}</button>
        ))}
      </div>
      {tab === 'today' && <Today />}
      {tab === 'history' && <MyAttendance />}
      {tab === 'leave' && <MyLeave />}
      {tab === 'team' && <TeamToday />}
      {tab === 'approvals' && <Approvals />}
      {tab === 'settings' && <HRSettings />}
    </div>
  )
}

/* ---------------- Today: check in / out ---------------- */

function Today() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    api('/api/attendance/today/').then(setData).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const getPosition = () => new Promise((resolve) => {
    if (!navigator.geolocation) return resolve({})
    navigator.geolocation.getCurrentPosition(
      p => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
      () => resolve({}),               // permission denied / unavailable -> server decides
      { timeout: 8000, enableHighAccuracy: true },
    )
  })

  const mark = async (which) => {
    setErr(''); setMsg(''); setBusy(true)
    try {
      const pos = await getPosition()
      await api(`/api/attendance/${which}/`, { method: 'POST', body: pos })
      setMsg(which === 'check_in' ? 'Checked in ✅' : 'Checked out ✅')
      load()
    } catch (e) {
      setErr(errorText(e.data) || e.message)
    } finally { setBusy(false) }
  }

  if (err && !data) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading…</div>
  const a = data.attendance

  return (
    <div style={{ maxWidth: 620 }}>
      <div className="stats">
        <div className="stat"><div className="label">Check in</div><div className="value">{fmtT(a?.check_in)}</div></div>
        <div className="stat"><div className="label">Check out</div><div className="value">{fmtT(a?.check_out)}</div></div>
        <div className="stat"><div className="label">Worked</div><div className="value">{hrs(a?.working_minutes)}</div></div>
        <div className={'stat' + (a?.is_late ? ' alert' : '')}>
          <div className="label">Status</div>
          <div className="value" style={{ fontSize: 17 }}>{a ? STATUS_LABEL[a.status] : '—'}</div>
        </div>
      </div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="placeholder-card" style={{ marginTop: 0 }}><h3>{msg}</h3></div>}
      <div className="dash-card">
        <h3>Mark attendance</h3>
        <p className="muted small" style={{ marginBottom: 10 }}>
          Office hours {data.work_start}–{data.work_end}.
          {data.geofence_enabled
            ? ' Location check is ON — allow GPS access.'
            : ' Location check is off.'}
          {data.face_enabled && (data.face_enrolled
            ? ' Face verification is ON.'
            : ' Face verification is ON but you are not enrolled — ask an admin.')}
        </p>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-primary" disabled={busy || !data.can_check_in}
            onClick={() => mark('check_in')}>
            {busy ? 'Working…' : 'Check in'}
          </button>
          <button className="btn" disabled={busy || !data.can_check_out}
            onClick={() => mark('check_out')}>Check out</button>
        </div>
      </div>
    </div>
  )
}

/* ---------------- My attendance: month view ---------------- */

function MyAttendance({ userId, userName }) {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [showCorrection, setShowCorrection] = useState(null)

  const load = useCallback(() => {
    const p = new URLSearchParams({ year, month })
    if (userId) p.set('user', userId)
    api(`/api/attendance/monthly/?${p}`).then(setData).catch(e => setErr(e.message))
  }, [year, month, userId])
  useEffect(() => { load() }, [load])

  if (err) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading…</div>
  const t = data.totals

  return (
    <div style={{ maxWidth: 820 }}>
      <div className="filters">
        <select value={month} onChange={e => setMonth(Number(e.target.value))}>
          {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
        </select>
        <select value={year} onChange={e => setYear(Number(e.target.value))}>
          {[year - 1, year, year + 1].map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        {userName && <span className="muted">· {userName}</span>}
        <span className="muted small" style={{ marginLeft: 'auto' }}>Total {data.total_hours} h</span>
      </div>
      <div className="stats">
        {[['Present', t.present], ['Late', t.late], ['Half Day', t.half_day],
          ['Leave', t.leave], ['Absent', t.absent, t.absent > 0], ['Week Off', t.week_off]]
          .map(([l, v, alert]) => (
            <div key={l} className={'stat' + (alert ? ' alert' : '')}>
              <div className="label">{l}</div><div className="value">{v || 0}</div>
            </div>
          ))}
      </div>
      <table className="table">
        <thead><tr><th>Date</th><th>Status</th><th>In</th><th>Out</th><th>Worked</th><th>Flags</th>{!userId && <th />}</tr></thead>
        <tbody>
          {data.days.filter(d => d.status).map(d => (
            <tr key={d.date}>
              <td>{fmtD(d.date)}</td>
              <td><span className={`q-pill q-${d.status}`}>{STATUS_LABEL[d.status]}{d.holiday ? `: ${d.holiday}` : ''}</span></td>
              <td>{fmtT(d.check_in)}</td>
              <td>{fmtT(d.check_out)}</td>
              <td>{hrs(d.working_minutes)}</td>
              <td className="small">
                {d.is_late && <span className="prio prio-high">late</span>}{' '}
                {d.is_early_checkout && <span className="ai-chip">early out</span>}{' '}
                {d.missing_checkout && <span className="prio prio-urgent">no checkout</span>}
              </td>
              {!userId && (
                <td className="row-actions">
                  {['present', 'late', 'half_day', 'absent'].includes(d.status) && (
                    <button className="btn btn-sm" onClick={() => setShowCorrection(d)}>Fix</button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {showCorrection && (
        <CorrectionModal day={showCorrection} onClose={() => setShowCorrection(null)}
          onSaved={() => { setShowCorrection(null); load() }} />
      )}
    </div>
  )
}

function CorrectionModal({ day, onClose, onSaved }) {
  const [f, setF] = useState({ in: '', out: '', reason: '' })
  const [err, setErr] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    const body = { date: day.date, reason: f.reason }
    if (f.in) body.requested_check_in = new Date(`${day.date}T${f.in}`).toISOString()
    if (f.out) body.requested_check_out = new Date(`${day.date}T${f.out}`).toISOString()
    try { await api('/api/attendance-corrections/', { method: 'POST', body }); onSaved() }
    catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }
  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>Correction request — {fmtD(day.date)}</h2>
        <div className="form-grid">
          <div><label>Correct check-in</label><input type="time" value={f.in} onChange={e => setF(p => ({ ...p, in: e.target.value }))} /></div>
          <div><label>Correct check-out</label><input type="time" value={f.out} onChange={e => setF(p => ({ ...p, out: e.target.value }))} /></div>
          <div className="wide"><label>Reason *</label><input value={f.reason} onChange={e => setF(p => ({ ...p, reason: e.target.value }))} placeholder="e.g. Forgot to check out" /></div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!f.reason.trim() || (!f.in && !f.out)}>Send request</button>
        </div>
      </form>
    </div>
  )
}

/* ---------------- My leave ---------------- */

function MyLeave() {
  const [balances, setBalances] = useState([])
  const [rows, setRows] = useState(null)
  const [types, setTypes] = useState([])
  const [showApply, setShowApply] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    Promise.all([
      api('/api/leaves/balances/'),
      api('/api/leaves/?page_size=100'),
      api('/api/leave-types/'),
    ]).then(([b, l, t]) => { setBalances(b); setRows(l.results || l); setTypes(t) })
      .catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const cancel = async (l) => {
    setErr('')
    try { await api(`/api/leaves/${l.id}/cancel/`, { method: 'POST' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>

  return (
    <div style={{ maxWidth: 820 }}>
      <div className="filters">
        <button className="btn btn-primary" onClick={() => setShowApply(true)}>+ Apply for leave</button>
      </div>
      {balances.length === 0 && <p className="muted">No leave types configured yet — an admin can add them in HR Settings.</p>}
      <div className="stats">
        {balances.map(b => (
          <div key={b.leave_type} className="stat">
            <div className="label">{b.name}{b.paid ? '' : ' (unpaid)'}</div>
            <div className="value">{b.balance}<span style={{ fontSize: 13, color: 'var(--muted)' }}> / {b.quota}</span></div>
            {b.pending > 0 && <div className="small muted">{b.pending} pending</div>}
          </div>
        ))}
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No leave requests yet.</p>}
      <table className="table">
        <thead><tr><th>Type</th><th>Dates</th><th>Days</th><th>Status</th><th>Remarks</th><th /></tr></thead>
        <tbody>
          {rows.map(l => (
            <tr key={l.id}>
              <td><strong>{l.leave_type_name}</strong><div className="muted small">{l.reason}</div></td>
              <td>{fmtD(l.start_date)} – {fmtD(l.end_date)}</td>
              <td>{l.days}</td>
              <td><span className={`q-pill q-${l.status}`}>{l.status_display}</span></td>
              <td className="small">{l.remarks || '—'}{l.reviewed_by_detail && <div className="muted">by {l.reviewed_by_detail.name}</div>}</td>
              <td className="row-actions">
                {['pending', 'approved'].includes(l.status) && (
                  <button className="btn btn-sm" onClick={() => cancel(l)}>Cancel</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {showApply && (
        <ApplyModal types={types} onClose={() => setShowApply(false)}
          onSaved={() => { setShowApply(false); load() }} />
      )}
    </div>
  )
}

function ApplyModal({ types, onClose, onSaved }) {
  const [f, setF] = useState({ leave_type: types[0]?.id || '', start_date: '', end_date: '', reason: '' })
  const [doc, setDoc] = useState(null)
  const [err, setErr] = useState('')
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))
  const selected = types.find(t => String(t.id) === String(f.leave_type))

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    try {
      if (doc) {
        const fd = new FormData()
        Object.entries(f).forEach(([k, v]) => fd.append(k, v))
        fd.append('document', doc)
        const { apiUpload } = await import('../api')
        await apiUpload('/api/leaves/', fd)
      } else {
        await api('/api/leaves/', { method: 'POST', body: f })
      }
      onSaved()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>Apply for leave</h2>
        <div className="form-grid">
          <div className="wide">
            <label>Leave type *</label>
            <select value={f.leave_type} onChange={set('leave_type')}>
              {types.map(t => <option key={t.id} value={t.id}>{t.name} ({t.annual_quota}/yr)</option>)}
            </select>
          </div>
          <div><label>From *</label><input type="date" value={f.start_date} onChange={set('start_date')} /></div>
          <div><label>To *</label><input type="date" value={f.end_date} onChange={set('end_date')} /></div>
          <div className="wide"><label>Reason *</label><input value={f.reason} onChange={set('reason')} /></div>
          {selected?.requires_document && (
            <div className="wide">
              <label>Supporting document * ({selected.name})</label>
              <input type="file" onChange={e => setDoc(e.target.files[0] || null)} />
            </div>
          )}
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!f.leave_type || !f.start_date || !f.end_date || !f.reason.trim()}>
            Submit request
          </button>
        </div>
      </form>
    </div>
  )
}

/* ---------------- Team today ---------------- */

function TeamToday() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [viewUser, setViewUser] = useState(null)
  useEffect(() => {
    api('/api/attendance/team_today/').then(setData).catch(e => setErr(e.message))
  }, [])
  if (err) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading…</div>
  if (viewUser) return (
    <div>
      <button className="btn btn-sm" onClick={() => setViewUser(null)}>← Back to team</button>
      <div style={{ height: 12 }} />
      <MyAttendance userId={viewUser.user_id} userName={viewUser.name} />
    </div>
  )
  const c = data.counts
  return (
    <div style={{ maxWidth: 820 }}>
      <div className="stats">
        {[['Present', c.present], ['Late', c.late, c.late > 0], ['Half Day', c.half_day],
          ['On Leave', c.leave], ['Not checked in', c.not_checked_in, c.not_checked_in > 0]]
          .map(([l, v, alert]) => (
            <div key={l} className={'stat' + (alert ? ' alert' : '')}>
              <div className="label">{l}</div><div className="value">{v || 0}</div>
            </div>
          ))}
      </div>
      <table className="table">
        <thead><tr><th>Employee</th><th>Department</th><th>Status</th><th>In</th><th>Out</th><th>Worked</th><th /></tr></thead>
        <tbody>
          {data.rows.map(r => (
            <tr key={r.user_id}>
              <td><strong>{r.name}</strong></td>
              <td>{r.department}</td>
              <td><span className={`q-pill q-${r.status}`}>{STATUS_LABEL[r.status]}</span></td>
              <td>{fmtT(r.check_in)}</td>
              <td>{fmtT(r.check_out)}</td>
              <td>{hrs(r.working_minutes)}</td>
              <td className="row-actions"><button className="btn btn-sm" onClick={() => setViewUser(r)}>History</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ---------------- Approvals ---------------- */

function Approvals() {
  const [leaves, setLeaves] = useState([])
  const [corrections, setCorrections] = useState([])
  const [err, setErr] = useState('')
  const [remarks, setRemarks] = useState({})

  const load = useCallback(() => {
    Promise.all([
      api('/api/leaves/?scope=team&status=pending&page_size=100'),
      api('/api/attendance-corrections/?scope=team&page_size=100'),
    ]).then(([l, c]) => {
      setLeaves(l.results || l)
      setCorrections((c.results || c).filter(x => x.status === 'pending'))
    }).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const review = async (kind, id, decision) => {
    setErr('')
    const path = kind === 'leave' ? `/api/leaves/${id}/review/` : `/api/attendance-corrections/${id}/review/`
    try {
      await api(path, { method: 'POST', body: { decision, remarks: remarks[`${kind}${id}`] || '' } })
      load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const Row = ({ kind, id, title, sub, meta }) => (
    <div className="task-row">
      <div className="task-main">
        <div className="task-title">{title}</div>
        <div className="small muted">{sub}</div>
        <div className="when">{meta}</div>
      </div>
      <input placeholder="Remarks…" style={{ width: 150 }}
        value={remarks[`${kind}${id}`] || ''}
        onChange={e => setRemarks(p => ({ ...p, [`${kind}${id}`]: e.target.value }))} />
      <button className="btn btn-sm btn-primary" onClick={() => review(kind, id, 'approved')}>Approve</button>
      <button className="btn btn-sm" onClick={() => review(kind, id, 'rejected')}>Reject</button>
    </div>
  )

  return (
    <div style={{ maxWidth: 820 }}>
      {err && <div className="err">{err}</div>}
      <h3 className="tpl-cat">Leave requests ({leaves.length})</h3>
      {leaves.length === 0 && <p className="muted">Nothing pending.</p>}
      <div className="task-list" style={{ marginBottom: 20 }}>
        {leaves.map(l => (
          <Row key={l.id} kind="leave" id={l.id}
            title={`${l.user_detail?.name} — ${l.leave_type_name} (${l.days} day${l.days > 1 ? 's' : ''})`}
            sub={l.reason}
            meta={`${fmtD(l.start_date)} – ${fmtD(l.end_date)}`} />
        ))}
      </div>
      <h3 className="tpl-cat">Attendance corrections ({corrections.length})</h3>
      {corrections.length === 0 && <p className="muted">Nothing pending.</p>}
      <div className="task-list">
        {corrections.map(c => (
          <Row key={c.id} kind="correction" id={c.id}
            title={`${c.user_detail?.name} — ${fmtD(c.date)}`}
            sub={c.reason}
            meta={`in ${fmtT(c.requested_check_in)} · out ${fmtT(c.requested_check_out)}`} />
        ))}
      </div>
    </div>
  )
}

/* ---------------- HR settings (admin) ---------------- */

function HRSettings() {
  const [config, setConfig] = useState(null)
  const [offices, setOffices] = useState([])
  const [types, setTypes] = useState([])
  const [office, setOffice] = useState({ name: '', latitude: '', longitude: '', radius_m: 200 })
  const [type, setType] = useState({ name: '', annual_quota: 12, paid: true, requires_document: false })
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    Promise.all([api('/api/hr/config/'), api('/api/office-locations/'), api('/api/leave-types/')])
      .then(([c, o, t]) => { setConfig(c); setOffices(o); setTypes(t) })
      .catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const addOffice = async () => {
    setErr('')
    try {
      await api('/api/office-locations/', { method: 'POST', body: {
        ...office, latitude: Number(office.latitude), longitude: Number(office.longitude),
        radius_m: Number(office.radius_m) } })
      setOffice({ name: '', latitude: '', longitude: '', radius_m: 200 }); load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const useMyLocation = () => {
    navigator.geolocation?.getCurrentPosition(p => setOffice(o => ({
      ...o, latitude: p.coords.latitude.toFixed(6), longitude: p.coords.longitude.toFixed(6),
    })))
  }
  const delOffice = async (o) => {
    try { await api(`/api/office-locations/${o.id}/`, { method: 'DELETE' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const addType = async () => {
    setErr('')
    try {
      await api('/api/leave-types/', { method: 'POST', body: { ...type, annual_quota: Number(type.annual_quota) } })
      setType({ name: '', annual_quota: 12, paid: true, requires_document: false }); load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !config) return <div className="err">{err}</div>
  if (!config) return <div className="center-note">Loading…</div>

  return (
    <div style={{ maxWidth: 720 }}>
      {err && <div className="err">{err}</div>}
      <div className="dash-card" style={{ marginBottom: 14 }}>
        <h3>Policy (from backend/.env)</h3>
        <div className="cap-list">
          <code>work {config.work_start}–{config.work_end}</code>
          <code>geo-fence {config.geofence_enabled ? 'ON' : 'off'}</code>
          <code>face {config.face_enabled ? 'ON' : 'off'}</code>
          <code>week-offs {config.week_offs.join(',') || 'none'}</code>
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>
          Change these in <code>backend/.env</code> (HR_* / GEOFENCE_ENABLED / FACE_RECOGNITION_ENABLED) and restart the API.
        </p>
      </div>

      <div className="dash-card" style={{ marginBottom: 14 }}>
        <h3>Office locations (geo-fence)</h3>
        {offices.length === 0 && <p className="muted small">No office added. Geo-fencing cannot be enforced until one exists.</p>}
        {offices.map(o => (
          <div className="doc-row" key={o.id}>
            <div><strong>{o.name}</strong><div className="small muted">{o.latitude}, {o.longitude} · {o.radius_m} m</div></div>
            <button className="btn btn-sm" onClick={() => delOffice(o)}>✕</button>
          </div>
        ))}
        <div className="form-grid" style={{ marginTop: 10 }}>
          <div><label>Name</label><input value={office.name} onChange={e => setOffice(o => ({ ...o, name: e.target.value }))} /></div>
          <div><label>Radius (m)</label><input type="number" value={office.radius_m} onChange={e => setOffice(o => ({ ...o, radius_m: e.target.value }))} /></div>
          <div><label>Latitude</label><input value={office.latitude} onChange={e => setOffice(o => ({ ...o, latitude: e.target.value }))} /></div>
          <div><label>Longitude</label><input value={office.longitude} onChange={e => setOffice(o => ({ ...o, longitude: e.target.value }))} /></div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="btn" onClick={useMyLocation}>Use my current location</button>
          <button className="btn btn-primary" disabled={!office.name || !office.latitude} onClick={addOffice}>Add office</button>
        </div>
      </div>

      <div className="dash-card">
        <h3>Leave types</h3>
        {types.map(t => (
          <div className="doc-row" key={t.id}>
            <div><strong>{t.name}</strong><div className="small muted">{t.annual_quota}/yr · {t.paid ? 'paid' : 'unpaid'}{t.requires_document ? ' · document required' : ''}</div></div>
          </div>
        ))}
        <div className="form-grid" style={{ marginTop: 10 }}>
          <div><label>Name</label><input value={type.name} onChange={e => setType(t => ({ ...t, name: e.target.value }))} placeholder="e.g. Casual" /></div>
          <div><label>Annual quota</label><input type="number" value={type.annual_quota} onChange={e => setType(t => ({ ...t, annual_quota: e.target.value }))} /></div>
          <div><label className="switch" style={{ marginTop: 20 }}><input type="checkbox" checked={type.paid} onChange={e => setType(t => ({ ...t, paid: e.target.checked }))} /><span>Paid</span></label></div>
          <div><label className="switch" style={{ marginTop: 20 }}><input type="checkbox" checked={type.requires_document} onChange={e => setType(t => ({ ...t, requires_document: e.target.checked }))} /><span>Document required</span></label></div>
        </div>
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={!type.name.trim()} onClick={addType}>Add leave type</button>
      </div>
    </div>
  )
}
