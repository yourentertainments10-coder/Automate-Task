import { useEffect, useMemo, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

const ROLES = [
  ['admin', 'Admin'],
  ['hr_manager', 'HR Manager'],
  ['sales_manager', 'Sales Manager'],
  ['sales_executive', 'Sales Executive'],
  ['purchase', 'Purchase Team'],
  ['accounts', 'Accounts'],
  ['support', 'Customer Support'],
]
const DEPARTMENTS = [
  ['sales', 'Sales'],
  ['purchase', 'Purchase'],
  ['accounts', 'Accounts'],
  ['support', 'Customer Support'],
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
  const [rows, setRows] = useState([])
  const [q, setQ] = useState('')
  const [fRole, setFRole] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => { api('/api/team/').then(setRows).catch(e => setErr(e.message)) }, [])

  const shown = useMemo(() => rows.filter(u => {
    if (fRole && u.role !== fRole) return false
    if (q.trim() && !`${u.name} ${u.username} ${u.email} ${u.mobile}`.toLowerCase().includes(q.trim().toLowerCase())) return false
    return true
  }), [rows, q, fRole])

  return (
    <div>
      <div className="page-head">
        <h1>My Team</h1>
        <span className="muted small">{rows.length} members</span>
      </div>
      <div className="filters">
        <input type="search" placeholder="Search team member…" value={q} onChange={e => setQ(e.target.value)} />
        <select value={fRole} onChange={e => setFRole(e.target.value)}>
          <option value="">All roles</option>
          {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      {err && <div className="err">{err}</div>}
      <table className="table">
        <thead><tr><th>User</th><th>Mobile</th><th>Reports To</th><th>Department</th><th>Role</th></tr></thead>
        <tbody>
          {shown.map(u => (
            <tr key={u.id}>
              <td>
                <strong>{u.name}</strong>
                <div className="muted small">{u.email || '@' + u.username}</div>
              </td>
              <td>{u.mobile || '—'}</td>
              <td>{u.reports_to || 'NA'}</td>
              <td>{u.department_display}</td>
              <td><span className={`role-pill role-${u.role}`}>{u.role_display}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
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
  const [err, setErr] = useState('')

  const load = () => api('/api/users/?page_size=200').then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const managers = useMemo(() =>
    rows.filter(u => ['admin', 'sales_manager'].includes(u.role) && u.is_active), [rows])

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
            <tr key={u.id} className={u.is_active ? '' : 'inactive'}>
              <td>
                <strong>{u.first_name || u.username} {u.last_name}</strong>
                <div className="muted small">{u.email || '@' + u.username}</div>
              </td>
              <td>{u.whatsapp_phone || '—'}</td>
              <td>{u.reporting_manager_name || 'NA'}</td>
              <td><span className={`role-pill role-${u.role}`}>{u.role_display}</span></td>
              <td>{u.is_active ? <span className="ok">Active</span> : <span className="off">Deactivated</span>}</td>
              <td className="row-actions">
                <button className="btn btn-sm" onClick={() => setEditing(u)}>Edit</button>
                {u.id !== me.id && (
                  <button className="btn btn-sm" onClick={() => toggleActive(u)}>
                    {u.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

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
