import { useEffect, useMemo, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import PersonProfile from './PersonProfile'
import { WorkloadPanel } from './TaskExtras'

/* C2: fetch-on-expand workload for one team member */
function WorkloadCell({ userId }) {
  const [w, setW] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api(`/api/tasks/workload/?user=${userId}`)
      .then(setW).catch(e => setErr(errorText(e.data) || e.message))
  }, [userId])
  if (err) return <div className="muted small">{err}</div>
  if (!w) return <div className="muted small">Loading workload…</div>
  return <WorkloadPanel w={w} />
}

const ROLES = [
  ['admin', 'Admin'],
  ['hr_manager', 'HR Manager'],
  ['sales_manager', 'Sales Manager'],
  ['purchase_manager', 'Purchase Manager'],
  ['accounts_manager', 'Accounts Manager'],
  ['developer_manager', 'Developer Manager'],
  ['sales_executive', 'Sales'],
  ['purchase', 'Purchase Team'],
  ['accounts', 'Accounts'],
  ['it_lead', 'IT Lead'],
  ['warehouse_manager', 'Warehouse Manager'],
  ['warehouse', 'Warehouse Team'],
  ['rider', 'Rider'],
  ['developer', 'Developer'],
]
const DEPARTMENTS = [
  ['sales', 'Sales'],
  ['purchase', 'Purchase'],
  ['accounts', 'Accounts'],
  ['support', 'IT Team'],
  ['development', 'Developer Team'],
  ['warehouse', 'Warehouse'],
  ['hr', 'Human Resources'],
  ['management', 'Management'],
]

const EMPTY = {
  username: '', email: '', first_name: '', last_name: '',
  role: 'sales_executive', department: 'sales', whatsapp_phone: '',
  reporting_manager: '', password: '',
}

export default function Users() {
  const { can } = useAuth()
  return can('users.manage') ? <ManageTeam /> : <Directory />
}

/* ---------- Read-only directory (every role) ---------- */

function Directory() {
  const { user } = useAuth()
  const isManager = user.role === 'sales_manager'
  const [rows, setRows] = useState(null)
  const [q, setQ] = useState('')
  const [fRole, setFRole] = useState('')
  const [wlFor, setWlFor] = useState(null)   // C2: which member's workload is open
  const [profileFor, setProfileFor] = useState(null)  // name click -> full drill-down
  const [viewable, setViewable] = useState(new Set()) // whose task profile I may open
  const [err, setErr] = useState('')

  useEffect(() => { api('/api/team/').then(setRows).catch(e => setErr(e.message)) }, [])
  useEffect(() => {
    api('/api/tasks/people/').then(d => setViewable(new Set(d.map(p => p.id)))).catch(() => {})
  }, [])

  const shown = useMemo(() => (rows || []).filter(u => {
    if (fRole && u.role !== fRole) return false
    if (q.trim() && !`${u.name} ${u.username} ${u.email} ${u.mobile}`.toLowerCase().includes(q.trim().toLowerCase())) return false
    return true
  }), [rows, q, fRole])

  if (err) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>

  return (
    <div>
      <div className="page-head">
        <h1>My Team</h1>
        <span className="muted small">
          {isManager ? 'Reporting to you' : 'Your department'} · {rows.length} member{rows.length === 1 ? '' : 's'}
        </span>
      </div>
      {isManager && rows.length === 0 && (
        <p className="muted">No one reports to you yet — ask Admin/HR to set "Reports to" on your team members.</p>
      )}
      <div className="filters">
        <input type="search" placeholder="Search team member…" value={q} onChange={e => setQ(e.target.value)} />
        <select value={fRole} onChange={e => setFRole(e.target.value)}>
          <option value="">All roles</option>
          {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      {err && <div className="err">{err}</div>}
      <table className="table">
        <thead><tr><th>User</th><th>Mobile</th><th>Reports To</th><th>Department</th><th>Role</th><th /></tr></thead>
        <tbody>
          {shown.map(u => (
            <>
              <tr key={u.id}>
                <td>
                  {viewable.has(u.id) ? (
                    <button className="link-name" title="Open full task profile"
                      onClick={() => setProfileFor(u)}>{u.name}</button>
                  ) : <strong>{u.name}</strong>}
                  <div className="muted small">{u.email || '@' + u.username}</div>
                </td>
                <td>{u.mobile || '—'}</td>
                <td>{u.reports_to || 'NA'}</td>
                <td>{u.department_display}</td>
                <td><span className={`role-pill role-${u.role}`}>{u.role_display}</span></td>
                <td>
                  <button className="btn btn-sm" title="Open tasks & pending effort"
                    onClick={() => setWlFor(wlFor === u.id ? null : u.id)}>
                    {wlFor === u.id ? 'Hide' : '📊 Workload'}
                  </button>
                </td>
              </tr>
              {wlFor === u.id && (
                <tr key={`wl-${u.id}`}>
                  <td colSpan={6} style={{ paddingTop: 0 }}><WorkloadCell userId={u.id} /></td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
      {profileFor && (
        <PersonProfile userId={profileFor.id} name={profileFor.name}
          onClose={() => setProfileFor(null)} />
      )}
    </div>
  )
}

/* ---------- Admin management ---------- */

function ManageTeam() {
  const { user: me } = useAuth()
  const [rows, setRows] = useState([])
  const [editing, setEditing] = useState(null)   // null | 'new' | user object
  const [q, setQ] = useState('')
  const [fRole, setFRole] = useState('')
  const [fManager, setFManager] = useState('')
  const [wlFor, setWlFor] = useState(null)       // C2: which member's workload is open
  const [profileFor, setProfileFor] = useState(null)  // name click -> full drill-down
  const [viewable, setViewable] = useState(new Set()) // whose task profile I may open
  const [err, setErr] = useState('')

  const load = () => api('/api/users/?page_size=200').then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])
  useEffect(() => {
    api('/api/tasks/people/').then(d => setViewable(new Set(d.map(p => p.id)))).catch(() => {})
  }, [])

  const managers = useMemo(() =>
    rows.filter(u => ['admin', 'sales_manager', 'hr_manager', 'it_lead',
                      'warehouse_manager', 'purchase_manager', 'accounts_manager',
                      'developer_manager'].includes(u.role) && u.is_active), [rows])

  const shown = useMemo(() => rows.filter(u => {
    if (fRole && u.role !== fRole) return false
    if (fManager && String(u.reporting_manager || '') !== fManager) return false
    if (q.trim()) {
      const hay = `${u.first_name} ${u.last_name} ${u.username} ${u.email} ${u.whatsapp_phone}`.toLowerCase()
      if (!hay.includes(q.trim().toLowerCase())) return false
    }
    return true
  }), [rows, q, fRole, fManager])

  const toggleActive = async (u) => {
    setErr('')
    try {
      await api(`/api/users/${u.id}/${u.is_active ? 'deactivate' : 'activate'}/`, { method: 'POST' })
      load()
    } catch (e) { setErr(e.message) }
  }

  return (
    <div>
      <div className="page-head">
        <h1>My Team</h1>
        <button className="btn btn-primary" onClick={() => setEditing('new')}>+ Add user</button>
      </div>
      <div className="filters">
        <input type="search" placeholder="Search team member…" value={q} onChange={e => setQ(e.target.value)} />
        <select value={fRole} onChange={e => setFRole(e.target.value)}>
          <option value="">All roles</option>
          {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={fManager} onChange={e => setFManager(e.target.value)}>
          <option value="">Reporting manager…</option>
          {managers.map(m => <option key={m.id} value={m.id}>{m.first_name || m.username}</option>)}
        </select>
        <span className="muted small">{shown.length}/{rows.length} members</span>
      </div>
      {err && <div className="err">{err}</div>}
      <table className="table">
        <thead>
          <tr><th>User</th><th>Mobile</th><th>Reports To</th><th>Role</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {shown.map(u => (
            <>
              <tr key={u.id} className={u.is_active ? '' : 'inactive'}>
                <td>
                  {viewable.has(u.id) ? (
                    <button className="link-name" title="Open full task profile"
                      onClick={() => setProfileFor(u)}>
                      {u.first_name || u.username} {u.last_name}
                    </button>
                  ) : <strong>{u.first_name || u.username} {u.last_name}</strong>}
                  <div className="muted small">{u.email || '@' + u.username}</div>
                </td>
                <td>{u.whatsapp_phone || '—'}</td>
                <td>{u.reporting_manager_name || 'NA'}</td>
                <td><span className={`role-pill role-${u.role}`}>{u.role_display}</span></td>
                <td>{u.is_active ? <span className="ok">Active</span> : <span className="off">Deactivated</span>}</td>
                <td className="row-actions">
                  {u.is_active && (
                    <button className="btn btn-sm" title="Open tasks & pending effort"
                      onClick={() => setWlFor(wlFor === u.id ? null : u.id)}>
                      {wlFor === u.id ? 'Hide' : '📊'}
                    </button>
                  )}
                  <button className="btn btn-sm" onClick={() => setEditing(u)}>Edit</button>
                  {u.id !== me.id && (
                    <button className="btn btn-sm" onClick={() => toggleActive(u)}>
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  )}
                </td>
              </tr>
              {wlFor === u.id && (
                <tr key={`wl-${u.id}`}>
                  <td colSpan={6} style={{ paddingTop: 0 }}><WorkloadCell userId={u.id} /></td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>

      {profileFor && (
        <PersonProfile userId={profileFor.id}
          name={`${profileFor.first_name || profileFor.username} ${profileFor.last_name || ''}`.trim()}
          onClose={() => setProfileFor(null)} />
      )}

      {editing && (
        <UserModal
          initial={editing === 'new' ? null : editing}
          managers={managers}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
        />
      )}
    </div>
  )
}

function UserModal({ initial, managers, onClose, onSaved }) {
  const [f, setF] = useState(initial
    ? { ...EMPTY, ...initial, reporting_manager: initial.reporting_manager || '', password: '' }
    : EMPTY)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    setBusy(true)
    const body = {
      username: f.username, email: f.email, first_name: f.first_name, last_name: f.last_name,
      role: f.role, department: f.department, whatsapp_phone: f.whatsapp_phone,
      reporting_manager: f.reporting_manager ? Number(f.reporting_manager) : null,
    }
    if (f.password) body.password = f.password
    try {
      if (initial) await api(`/api/users/${initial.id}/`, { method: 'PATCH', body })
      else await api('/api/users/', { method: 'POST', body: { ...body, password: f.password } })
      onSaved()
    } catch (ex) {
      setErr(errorText(ex.data) || ex.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>{initial ? `Edit ${initial.username}` : 'Add user'}</h2>
        <div className="form-grid">
          <div>
            <label>Username *</label>
            <input value={f.username} onChange={set('username')} disabled={!!initial} autoFocus={!initial} />
          </div>
          <div>
            <label>Email</label>
            <input type="email" value={f.email} onChange={set('email')} />
          </div>
          <div>
            <label>First name</label>
            <input value={f.first_name} onChange={set('first_name')} />
          </div>
          <div>
            <label>Last name</label>
            <input value={f.last_name} onChange={set('last_name')} />
          </div>
          <div>
            <label>Role *</label>
            <select value={f.role} onChange={set('role')}>
              {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Department *</label>
            <select value={f.department} onChange={set('department')}>
              {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>WhatsApp / Mobile</label>
            <input value={f.whatsapp_phone} onChange={set('whatsapp_phone')} placeholder="9198XXXXXXXX" />
          </div>
          <div>
            <label>Reports to</label>
            <select value={f.reporting_manager} onChange={set('reporting_manager')}>
              <option value="">NA</option>
              {managers.filter(m => !initial || m.id !== initial.id)
                .map(m => <option key={m.id} value={m.id}>{m.first_name || m.username}</option>)}
            </select>
          </div>
          <div className="wide">
            <label>{initial ? 'New password (blank = keep)' : 'Password *'}</label>
            <input type="password" value={f.password} onChange={set('password')} autoComplete="new-password" />
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : initial ? 'Save changes' : 'Create user'}
          </button>
        </div>
      </form>
    </div>
  )
}
