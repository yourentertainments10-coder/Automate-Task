import { useCallback, useEffect, useState } from 'react'
import { api, errorText, tokens } from '../api'
import { useAuth } from '../auth'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const inr = (n) => '₹' + Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
const fmtD = (d) => d ? new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

/* ============ HR/Admin: run payroll ============ */
export function PayrollAdmin() {
  const [tab, setTab] = useState('runs')
  return (
    <div>
      <div className="filters">
        <div className="seg">
          {[['runs', 'Monthly payroll'], ['salaries', 'Salaries'], ['advances', 'Advances']].map(([v, l]) => (
            <button key={v} className={'seg-btn' + (tab === v ? ' on' : '')} onClick={() => setTab(v)}>{l}</button>
          ))}
        </div>
      </div>
      {tab === 'runs' && <Runs />}
      {tab === 'salaries' && <Salaries />}
      {tab === 'advances' && <Advances />}
    </div>
  )
}

function Runs() {
  const today = new Date()
  const [runs, setRuns] = useState(null)
  const [open, setOpen] = useState(null)
  const [slips, setSlips] = useState([])
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [f, setF] = useState({ year: today.getFullYear(), month: today.getMonth() + 1 })

  const load = useCallback(() => {
    api('/api/payroll-runs/').then(setRuns).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const openRun = async (run) => {
    setOpen(run); setErr('')
    try { setSlips(await api(`/api/payroll-runs/${run.id}/payslips/`)) }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const create = async () => {
    setErr(''); setMsg('')
    try {
      const run = await api('/api/payroll-runs/', { method: 'POST', body: { year: Number(f.year), month: Number(f.month) } })
      setMsg(`Draft payroll created for ${MONTHS[f.month - 1]} ${f.year}.`)
      load(); openRun(run)
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const act = async (run, action) => {
    setErr(''); setMsg('')
    try {
      const res = await api(`/api/payroll-runs/${run.id}/${action}/`, { method: 'POST' })
      setMsg(action === 'finalise'
        ? `Payroll finalised. ${res.advances_settled} advance(s) settled.`
        : `Recalculated: ${res.payslips} payslip(s)` + (res.skipped_no_salary?.length
          ? ` · skipped (no salary set): ${res.skipped_no_salary.join(', ')}` : ''))
      load(); openRun({ ...run, ...res.run })
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const exportCsv = async (run) => {
    try {
      const res = await fetch(`/api/payroll-runs/${run.id}/export/`, { headers: { Authorization: `Bearer ${tokens.access}` } })
      if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(await res.blob())
      a.download = `payroll-${run.year}-${String(run.month).padStart(2, '0')}.csv`
      a.click(); URL.revokeObjectURL(a.href)
    } catch (e) { setErr(e.message) }
  }

  if (err && !runs) return <div className="err">{err}</div>
  if (!runs) return <div className="center-note">Loading payroll…</div>

  return (
    <div style={{ maxWidth: 900 }}>
      <div className="filters">
        <select value={f.month} onChange={e => setF(p => ({ ...p, month: e.target.value }))}>
          {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
        </select>
        <select value={f.year} onChange={e => setF(p => ({ ...p, year: e.target.value }))}>
          {[today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1].map(y => <option key={y}>{y}</option>)}
        </select>
        <button className="btn btn-primary" onClick={create}>+ Run payroll</button>
      </div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="placeholder-card" style={{ marginTop: 0, marginBottom: 12 }}><h3>{msg}</h3></div>}

      {runs.length === 0 && <p className="muted">No payroll run yet. Pick a month and press "Run payroll" — salaries are computed from attendance.</p>}
      {runs.length > 0 && (
        <table className="table">
          <thead><tr><th>Month</th><th>Status</th><th>Working days</th><th>Payslips</th><th>Total net</th><th /></tr></thead>
          <tbody>
            {runs.map(r => (
              <tr key={r.id}>
                <td><strong>{MONTHS[r.month - 1]} {r.year}</strong></td>
                <td><span className={`q-pill q-${r.status === 'finalised' ? 'approved' : 'draft'}`}>{r.status}</span></td>
                <td>{r.working_days}</td>
                <td>{r.payslip_count}</td>
                <td><strong>{inr(r.total_net)}</strong></td>
                <td className="row-actions">
                  <button className="btn btn-sm" onClick={() => openRun(r)}>View</button>
                  {r.status === 'draft' && <button className="btn btn-sm" onClick={() => act(r, 'generate')}>Recalculate</button>}
                  {r.status === 'draft' && <button className="btn btn-sm btn-primary" onClick={() => act(r, 'finalise')}>Finalise</button>}
                  <button className="btn btn-sm" onClick={() => exportCsv(r)}>CSV</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {open && (
        <div className="dash-card" style={{ marginTop: 16 }}>
          <h3>{MONTHS[open.month - 1]} {open.year} — {slips.length} payslip(s)</h3>
          {slips.length === 0 && <p className="muted small">No payslips. Employees need a salary structure first (Salaries tab).</p>}
          {slips.length > 0 && (
            <div className="tablewrap">
              <table className="table">
                <thead>
                  <tr><th>Employee</th><th>Gross</th><th>Paid days</th><th>LWP</th><th>Earned</th>
                    <th>PF</th><th>PT</th><th>Advance</th><th>Other</th><th>Net</th></tr>
                </thead>
                <tbody>
                  {slips.map(s => (
                    <tr key={s.id}>
                      <td><strong>{s.user_detail?.name}</strong></td>
                      <td>{inr(s.monthly_gross)}</td>
                      <td>{s.payable_days} / {s.working_days}</td>
                      <td className={Number(s.lwp_days) > 0 ? 'late' : ''}>{s.lwp_days}</td>
                      <td>{inr(s.earned_gross)}</td>
                      <td>{inr(s.pf)}</td><td>{inr(s.professional_tax)}</td>
                      <td>{inr(s.advance_deduction)}</td><td>{inr(s.other_deduction)}</td>
                      <td><strong>{inr(s.net_payable)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Salaries() {
  const [rows, setRows] = useState(null)
  const [team, setTeam] = useState([])
  const [err, setErr] = useState('')
  const [f, setF] = useState({ user: '', monthly_gross: '', basic: '', pf_percent: '0',
    professional_tax: '0', other_deduction: '0', effective_from: '', note: '' })

  const load = useCallback(() => {
    api('/api/salary-structures/').then(setRows).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load(); api('/api/team/').then(setTeam).catch(() => {}) }, [load])

  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))
  const save = async () => {
    setErr('')
    try {
      await api('/api/salary-structures/', { method: 'POST', body: {
        ...f, user: Number(f.user), basic: f.basic || null } })
      setF(p => ({ ...p, user: '', monthly_gross: '', basic: '', note: '' })); load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>
  return (
    <div style={{ maxWidth: 860 }}>
      {err && <div className="err">{err}</div>}
      <div className="dash-card" style={{ marginBottom: 14 }}>
        <h3>Set a salary</h3>
        <p className="muted small">A new entry doesn't overwrite the old one — the latest date that has arrived is used, so past payslips stay explainable.</p>
        <div className="form-grid">
          <div><label>Employee *</label>
            <select value={f.user} onChange={set('user')}>
              <option value="">Choose…</option>
              {team.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select></div>
          <div><label>Monthly gross (₹) *</label><input type="number" value={f.monthly_gross} onChange={set('monthly_gross')} /></div>
          <div><label>Basic (optional)</label><input type="number" value={f.basic} onChange={set('basic')} placeholder="PF base" /></div>
          <div><label>PF % (employee)</label><input type="number" value={f.pf_percent} onChange={set('pf_percent')} /></div>
          <div><label>Professional tax (₹)</label><input type="number" value={f.professional_tax} onChange={set('professional_tax')} /></div>
          <div><label>Other deduction (₹)</label><input type="number" value={f.other_deduction} onChange={set('other_deduction')} /></div>
          <div><label>Effective from *</label><input type="date" value={f.effective_from} onChange={set('effective_from')} /></div>
          <div><label>Note</label><input value={f.note} onChange={set('note')} placeholder="e.g. Appraisal 2026" /></div>
        </div>
        <button className="btn btn-primary" style={{ marginTop: 10 }}
          disabled={!f.user || !f.monthly_gross || !f.effective_from} onClick={save}>Save salary</button>
      </div>
      {rows.length === 0 && <p className="muted">No salaries set yet.</p>}
      {rows.length > 0 && (
        <table className="table">
          <thead><tr><th>Employee</th><th>Gross</th><th>Basic</th><th>PF %</th><th>PT</th><th>Other</th><th>Effective from</th></tr></thead>
          <tbody>
            {rows.map(s => (
              <tr key={s.id}>
                <td><strong>{s.user_detail?.name}</strong>{s.note && <div className="muted small">{s.note}</div>}</td>
                <td>{inr(s.monthly_gross)}</td><td>{s.basic ? inr(s.basic) : '—'}</td>
                <td>{s.pf_percent}%</td><td>{inr(s.professional_tax)}</td><td>{inr(s.other_deduction)}</td>
                <td>{fmtD(s.effective_from)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Advances() {
  const [rows, setRows] = useState(null)
  const [team, setTeam] = useState([])
  const [err, setErr] = useState('')
  const [f, setF] = useState({ user: '', amount: '', given_on: '', reason: '' })

  const load = useCallback(() => {
    api('/api/advances/').then(setRows).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load(); api('/api/team/').then(setTeam).catch(() => {}) }, [load])

  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))
  const save = async () => {
    setErr('')
    try {
      await api('/api/advances/', { method: 'POST', body: { ...f, user: Number(f.user) } })
      setF({ user: '', amount: '', given_on: '', reason: '' }); load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const remove = async (a) => {
    setErr('')
    try { await api(`/api/advances/${a.id}/`, { method: 'DELETE' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>
  return (
    <div style={{ maxWidth: 760 }}>
      {err && <div className="err">{err}</div>}
      <div className="filters">
        <select value={f.user} onChange={set('user')}>
          <option value="">Employee…</option>
          {team.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <input type="number" placeholder="Amount ₹" value={f.amount} onChange={set('amount')} style={{ width: 120 }} />
        <input type="date" value={f.given_on} onChange={set('given_on')} />
        <input placeholder="Reason" value={f.reason} onChange={set('reason')} />
        <button className="btn btn-primary" disabled={!f.user || !f.amount || !f.given_on} onClick={save}>Add advance</button>
      </div>
      <p className="muted small">Pending advances are deducted from the next payroll automatically, and never push a payslip below zero.</p>
      {rows.length === 0 && <p className="muted">No advances recorded.</p>}
      {rows.length > 0 && (
        <table className="table">
          <thead><tr><th>Employee</th><th>Amount</th><th>Given on</th><th>Reason</th><th>Status</th><th /></tr></thead>
          <tbody>
            {rows.map(a => (
              <tr key={a.id}>
                <td><strong>{a.user_detail?.name}</strong></td>
                <td>{inr(a.amount)}</td><td>{fmtD(a.given_on)}</td><td>{a.reason || '—'}</td>
                <td><span className={`q-pill q-${a.recovered ? 'approved' : 'under_review'}`}>{a.recovered ? 'Recovered' : 'Pending'}</span></td>
                <td className="row-actions">{!a.recovered && <button className="btn btn-sm" onClick={() => remove(a)}>✕</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* ============ Everyone: my payslips ============ */
export function MySalary() {
  const { user } = useAuth()
  const [slips, setSlips] = useState(null)
  const [salary, setSalary] = useState([])
  const [open, setOpen] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api('/api/payslips/').then(setSlips).catch(e => setErr(e.message))
    api('/api/salary-structures/').then(setSalary).catch(() => {})
  }, [])

  if (err) return <div className="err">{err}</div>
  if (!slips) return <div className="center-note">Loading…</div>
  const current = salary[0]

  return (
    <div style={{ maxWidth: 700 }}>
      {current ? (
        <div className="stats">
          <div className="stat"><div className="label">My monthly salary</div><div className="value">{inr(current.monthly_gross)}</div></div>
          <div className="stat"><div className="label">Effective from</div><div className="value" style={{ fontSize: 16 }}>{fmtD(current.effective_from)}</div></div>
        </div>
      ) : <p className="muted">Your salary hasn't been set yet — ask HR.</p>}

      {slips.length === 0 && <p className="muted">No payslips yet. They appear here once HR finalises the month.</p>}
      {slips.length > 0 && (
        <table className="table">
          <thead><tr><th>Month</th><th>Paid days</th><th>Earned</th><th>Deductions</th><th>Net paid</th><th /></tr></thead>
          <tbody>
            {slips.map(s => (
              <tr key={s.id}>
                <td><strong>{MONTHS[s.month - 1]} {s.year}</strong></td>
                <td>{s.payable_days} / {s.working_days}</td>
                <td>{inr(s.earned_gross)}</td>
                <td>{inr(s.total_deductions)}</td>
                <td><strong>{inr(s.net_payable)}</strong></td>
                <td className="row-actions"><button className="btn btn-sm" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? 'Hide' : 'Details'}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {open && (() => {
        const s = slips.find(x => x.id === open)
        const b = s.breakdown || {}
        return (
          <div className="dash-card" style={{ marginTop: 14 }}>
            <h3>Payslip — {MONTHS[s.month - 1]} {s.year} · {user.first_name || user.username}</h3>
            <div className="doc-row"><span>Present days</span><strong>{b.present ?? '—'}</strong></div>
            <div className="doc-row"><span>Half days</span><strong>{b.half_day ?? 0}</strong></div>
            <div className="doc-row"><span>Paid leave</span><strong>{b.paid_leave ?? 0}</strong></div>
            <div className="doc-row"><span>Unpaid leave / absent (LWP)</span><strong>{s.lwp_days}</strong></div>
            <div className="doc-row"><span>Per-day rate</span><strong>{inr(b.per_day)}</strong></div>
            <div className="doc-row"><span>Earned gross</span><strong>{inr(s.earned_gross)}</strong></div>
            {Number(s.pf) > 0 && <div className="doc-row"><span>PF</span><strong>− {inr(s.pf)}</strong></div>}
            {Number(s.professional_tax) > 0 && <div className="doc-row"><span>Professional tax</span><strong>− {inr(s.professional_tax)}</strong></div>}
            {Number(s.advance_deduction) > 0 && <div className="doc-row"><span>Advance recovered</span><strong>− {inr(s.advance_deduction)}</strong></div>}
            {Number(s.other_deduction) > 0 && <div className="doc-row"><span>Other deduction</span><strong>− {inr(s.other_deduction)}</strong></div>}
            <div className="doc-row" style={{ borderBottom: 'none', fontSize: 16 }}>
              <span><strong>Net paid</strong></span><strong>{inr(s.net_payable)}</strong>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
