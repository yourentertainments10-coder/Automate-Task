import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import { useDepartments } from '../useDepartments'
import { useRoles } from '../useRoles'
import ProofreadText from '../ProofreadText'

const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '—'
const toLocalInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function Notices() {
  const { can } = useAuth()
  const isAdmin = can('settings.manage')
  const [mode, setMode] = useState('feed')   // feed | manage

  return (
    <div>
      <div className="page-head">
        <h1>Notices</h1>
        {isAdmin && (
          <div className="seg">
            <button className={'seg-btn' + (mode === 'feed' ? ' on' : '')} onClick={() => setMode('feed')}>Board</button>
            <button className={'seg-btn' + (mode === 'manage' ? ' on' : '')} onClick={() => setMode('manage')}>Manage</button>
          </div>
        )}
      </div>
      {mode === 'feed' ? <NoticeFeed /> : <NoticeManage />}
    </div>
  )
}

function NoticeFeed() {
  const [rows, setRows] = useState(null)
  const [filter, setFilter] = useState('')     // '' | 'true' | 'false'
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const p = new URLSearchParams()
    if (filter) p.set('read', filter)
    if (q.trim()) p.set('search', q.trim())
    api(`/api/notices/?${p}`).then(setRows).catch(e => setErr(e.message))
  }, [filter, q])
  useEffect(() => { load() }, [load])

  const open = async (n) => {
    setOpenId(openId === n.id ? null : n.id)
    if (!n.read) {
      await api(`/api/notices/${n.id}/read/`, { method: 'POST' }).catch(() => {})
      load()
    }
  }

  if (err) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading notices…</div>

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="filters">
        <div className="seg">
          {[['', 'All'], ['false', 'Unread'], ['true', 'Read']].map(([v, l]) => (
            <button key={l} className={'seg-btn' + (filter === v ? ' on' : '')} onClick={() => setFilter(v)}>{l}</button>
          ))}
        </div>
        <input type="search" placeholder="Search notices…" value={q} onChange={e => setQ(e.target.value)} />
      </div>
      {rows.length === 0 && <p className="muted">No notices here.</p>}
      <div className="notif-list">
        {rows.map(n => (
          <div key={n.id} className={'notif' + (n.read ? '' : ' unread')} onClick={() => open(n)}>
            <span className="notif-icon">{n.priority === 'urgent' ? '📢' : n.priority === 'important' ? '⚠️' : '📌'}</span>
            <div className="notif-main">
              <div className="notif-title">{n.title}
                {n.category && <span className="ai-chip" style={{ marginLeft: 8 }}>{n.category}</span>}
              </div>
              {openId === n.id && (
                <div className="notif-body" style={{ whiteSpace: 'pre-line' }}>
                  {n.content || '—'}
                  {n.attachment_url && <div><a href={n.attachment_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>📎 Attachment</a></div>}
                </div>
              )}
              <div className="when">{n.author_detail?.name || '—'} · {fmtDT(n.publish_at || n.created_at)}</div>
            </div>
            {!n.read && <span className="notif-dot" />}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------- Admin management ---------------- */

function NoticeManage() {
  const [rows, setRows] = useState(null)
  const [editing, setEditing] = useState(null)   // null | 'new' | notice
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api('/api/notices/?manage=true').then(setRows).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const doAction = async (n, action) => {
    setErr('')
    try {
      if (action === 'delete') await api(`/api/notices/${n.id}/`, { method: 'DELETE' })
      else await api(`/api/notices/${n.id}/${action}/`, { method: 'POST' })
      load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>

  return (
    <div>
      <div className="filters">
        <button className="btn btn-primary" onClick={() => setEditing('new')}>+ New notice</button>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No notices created yet.</p>}
      <table className="table" style={{ maxWidth: 900 }}>
        <thead><tr><th>Title</th><th>Audience</th><th>Status</th><th>Publish</th><th>Expires</th><th /></tr></thead>
        <tbody>
          {rows.map(n => (
            <tr key={n.id}>
              <td><strong>{n.title}</strong>{n.category && <div className="small muted">{n.category}</div>}</td>
              <td>{n.audience_display}</td>
              <td><span className={`q-pill q-${n.status}`}>{n.status_display}{n.is_expired && n.status === 'published' ? ' (expired)' : ''}</span></td>
              <td>{fmtDT(n.publish_at)}</td>
              <td>{fmtDT(n.expire_at)}</td>
              <td className="row-actions">
                <button className="btn btn-sm" onClick={() => setEditing(n)}>Edit</button>
                {n.status !== 'published' && <button className="btn btn-sm btn-primary" onClick={() => doAction(n, 'publish')}>Publish</button>}
                {n.status === 'published' && <button className="btn btn-sm" onClick={() => doAction(n, 'archive')}>Archive</button>}
                {n.status === 'draft' && <button className="btn btn-sm" onClick={() => doAction(n, 'delete')}>Delete</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <NoticeModal initial={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }} />
      )}
    </div>
  )
}

function NoticeModal({ initial, onClose, onSaved }) {
  const { rows: ROLES } = useRoles()
  const DEPARTMENTS = useDepartments()
  const [f, setF] = useState(initial ? {
    title: initial.title, content: initial.content, category: initial.category,
    priority: initial.priority, audience_type: initial.audience_type,
    audience_value: initial.audience_value || {},
    publish_at: toLocalInput(initial.publish_at), expire_at: toLocalInput(initial.expire_at),
  } : {
    title: '', content: '', category: '', priority: 'normal',
    audience_type: 'everyone', audience_value: {}, publish_at: '', expire_at: '',
  })
  const [groups, setGroups] = useState([])
  const [team, setTeam] = useState([])
  const [err, setErr] = useState('')
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))

  useEffect(() => {
    api('/api/groups/').then(setGroups).catch(() => {})
    api('/api/team/').then(setTeam).catch(() => {})
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    const body = {
      ...f,
      publish_at: f.publish_at ? new Date(f.publish_at).toISOString() : null,
      expire_at: f.expire_at ? new Date(f.expire_at).toISOString() : null,
    }
    try {
      if (initial) await api(`/api/notices/${initial.id}/`, { method: 'PATCH', body })
      else await api('/api/notices/', { method: 'POST', body })
      onSaved()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  const setAudience = (k, v) => setF(p => ({ ...p, audience_value: { [k]: v } }))

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>{initial ? 'Edit notice' : 'New notice'}</h2>
        <div className="form-grid">
          <div className="wide"><label>Title *</label><input value={f.title} onChange={set('title')} autoFocus /></div>
          <div className="wide">
            <ProofreadText label="Content" value={f.content} rows={4}
              onChange={v => setF(prev => ({ ...prev, content: v }))} />
          </div>
          <div><label>Category</label><input value={f.category} onChange={set('category')} placeholder="e.g. HR, Policy" /></div>
          <div>
            <label>Priority</label>
            <select value={f.priority} onChange={set('priority')}>
              <option value="normal">Normal</option>
              <option value="important">Important</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div>
            <label>Audience</label>
            <select value={f.audience_type} onChange={e => setF(p => ({ ...p, audience_type: e.target.value, audience_value: {} }))}>
              <option value="everyone">Everyone</option>
              <option value="role">Specific role</option>
              <option value="department">Specific department</option>
              <option value="group">Specific group</option>
              <option value="users">Specific users</option>
            </select>
          </div>
          <div>
            {f.audience_type === 'role' && (
              <><label>Role</label>
                <select value={f.audience_value.role || ''} onChange={e => setAudience('role', e.target.value)}>
                  <option value="">Pick…</option>
                  {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select></>
            )}
            {f.audience_type === 'department' && (
              <><label>Department</label>
                <select value={f.audience_value.department || ''} onChange={e => setAudience('department', e.target.value)}>
                  <option value="">Pick…</option>
                  {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select></>
            )}
            {f.audience_type === 'group' && (
              <><label>Group</label>
                <select value={f.audience_value.group || ''} onChange={e => setAudience('group', Number(e.target.value))}>
                  <option value="">Pick…</option>
                  {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                </select></>
            )}
            {f.audience_type === 'users' && (
              <><label>Users (multi-select)</label>
                <select multiple size={4} style={{ width: '100%' }}
                  value={(f.audience_value.users || []).map(String)}
                  onChange={e => setAudience('users', [...e.target.selectedOptions].map(o => Number(o.value)))}>
                  {team.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select></>
            )}
          </div>
          <div><label>Publish at (blank = on publish)</label><input type="datetime-local" value={f.publish_at} onChange={set('publish_at')} /></div>
          <div><label>Expires (optional)</label><input type="datetime-local" value={f.expire_at} onChange={set('expire_at')} /></div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={!f.title.trim()}>
            {initial ? 'Save changes' : 'Save draft'}
          </button>
        </div>
      </form>
    </div>
  )
}
