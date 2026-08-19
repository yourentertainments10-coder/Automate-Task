import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : null

export default function Groups() {
  const { can } = useAuth()
  const [groups, setGroups] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api('/api/groups/').then(setGroups).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  if (err) return <div className="err">{err}</div>
  if (!groups) return <div className="center-note">Loading groups…</div>

  const open = groups.find(g => g.id === openId)
  if (open) return <GroupDetail group={open} onBack={() => { setOpenId(null); load() }} onChanged={load} />

  return (
    <div>
      <div className="page-head">
        <h1>Groups</h1>
        {can('tasks.assign') && <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ New group</button>}
      </div>
      {groups.length === 0 && (
        <p className="muted">No groups yet{can('tasks.assign') ? ' — create one to give a team its own workspace.' : ' — you will see groups here once you are added to one.'}</p>
      )}
      <div className="group-grid">
        {groups.map(g => (
          <div key={g.id} className={'dash-card group-card' + (g.active ? '' : ' inactive')} onClick={() => setOpenId(g.id)}>
            <div className="task-title">{g.name} {!g.active && <span className="off">Archived</span>}</div>
            {g.category && <span className="ai-chip">{g.category}</span>}
            {g.description && <div className="small muted" style={{ marginTop: 6 }}>{g.description}</div>}
            <div className="when" style={{ marginTop: 8 }}>
              {g.member_count} member{g.member_count === 1 ? '' : 's'} · owner {g.owner_detail?.name || '—'}
            </div>
          </div>
        ))}
      </div>
      {showAdd && <GroupModal onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); load() }} />}
    </div>
  )
}

function GroupModal({ initial, onClose, onSaved }) {
  const [f, setF] = useState(initial
    ? { name: initial.name, description: initial.description, category: initial.category }
    : { name: '', description: '', category: '' })
  const [err, setErr] = useState('')
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))
  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    try {
      if (initial) await api(`/api/groups/${initial.id}/`, { method: 'PATCH', body: f })
      else await api('/api/groups/', { method: 'POST', body: f })
      onSaved()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }
  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>{initial ? `Edit ${initial.name}` : 'New group'}</h2>
        <div className="form-grid">
          <div className="wide"><label>Name *</label><input value={f.name} onChange={set('name')} autoFocus /></div>
          <div className="wide"><label>Description</label><input value={f.description} onChange={set('description')} /></div>
          <div><label>Category</label><input value={f.category} onChange={set('category')} placeholder="e.g. Sales, HR" /></div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={!f.name.trim()}>{initial ? 'Save' : 'Create group'}</button>
        </div>
      </form>
    </div>
  )
}

/* ---------------- Group detail with tabs ---------------- */

const TABS = ['Dashboard', 'Tasks', 'Ideas', 'Links', 'Members']

function GroupDetail({ group, onBack, onChanged }) {
  const [tab, setTab] = useState('Dashboard')
  const [showEdit, setShowEdit] = useState(false)
  const [err, setErr] = useState('')

  const archive = async () => {
    setErr('')
    try { await api(`/api/groups/${group.id}/`, { method: 'DELETE' }); onBack() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <div>
      <div className="page-head">
        <h1><button className="btn btn-sm" onClick={onBack}>←</button> {group.name}</h1>
        {group.can_manage && (
          <span style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => setShowEdit(true)}>Edit</button>
            {group.active && <button className="btn" onClick={archive}>Archive</button>}
          </span>
        )}
      </div>
      {err && <div className="err">{err}</div>}
      <div className="area-tabs">
        {TABS.map(t => (
          <button key={t} className={'tab' + (tab === t ? ' on' : '')} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'Dashboard' && <GroupDashboard group={group} />}
      {tab === 'Tasks' && <GroupTasks group={group} />}
      {tab === 'Ideas' && <GroupIdeas group={group} />}
      {tab === 'Links' && <GroupLinks group={group} />}
      {tab === 'Members' && <GroupMembers group={group} onChanged={onChanged} />}
      {showEdit && (
        <GroupModal initial={group} onClose={() => setShowEdit(false)}
          onSaved={() => { setShowEdit(false); onChanged() }} />
      )}
    </div>
  )
}

function GroupDashboard({ group }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api(`/api/groups/${group.id}/dashboard/`).then(setData).catch(e => setErr(e.message))
  }, [group.id])
  if (err) return <div className="err">{err}</div>
  if (!data) return <div className="center-note">Loading…</div>
  const t = data.tiles
  return (
    <div>
      <div className="stats">
        {[['Total tasks', t.total], ['Pending', t.pending], ['In progress', t.in_progress],
          ['Completed', t.completed], ['Overdue', t.overdue, t.overdue > 0], ['Members', t.members]]
          .map(([label, value, alert]) => (
            <div key={label} className={'stat' + (alert ? ' alert' : '')}>
              <div className="label">{label}</div><div className="value">{value}</div>
            </div>
          ))}
      </div>
      <div className="dash-card" style={{ maxWidth: 680 }}>
        <h3>Recent activity</h3>
        {data.recent_activity.length === 0 && <p className="muted small">No task activity in this group yet.</p>}
        {data.recent_activity.map((a, i) => (
          <div className="feed-row" key={i}>
            <span className="dot" style={{ marginTop: 6 }} />
            <div>
              <strong>{a.task_title}</strong> <span className="small muted">{a.text}</span>
              <div className="when">{a.actor} · {fmtDT(a.created_at)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function GroupTasks({ group }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(() => {
    api(`/api/tasks/?group=${group.id}&page_size=200`)
      .then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [group.id])
  useEffect(() => { load() }, [load])

  const setStatus = async (t, status) => {
    setErr('')
    try { await api(`/api/tasks/${t.id}/`, { method: 'PATCH', body: { status } }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>
  return (
    <div>
      <p className="muted small">Create group tasks from the Tasks page — pick "{group.name}" in the Group field.</p>
      {rows.length === 0 && <p className="muted">No tasks in this group yet.</p>}
      <div className="task-list">
        {rows.map(t => (
          <div key={t.id} className={'task-row' + (t.is_overdue ? ' overdue' : '') + (t.status === 'done' ? ' done' : '')}>
            <input type="checkbox" checked={t.status === 'done'}
              onChange={e => setStatus(t, e.target.checked ? 'done' : 'open')} />
            <div className="task-main">
              <div className="task-title">{t.title}</div>
              <div className="when">
                {t.assigned_to_detail?.name}
                {t.due_at && <span className={t.is_overdue ? ' late' : ''}> · due {fmtDT(t.due_at)}</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function GroupIdeas({ group }) {
  const [rows, setRows] = useState(null)
  const [title, setTitle] = useState('')
  const [err, setErr] = useState('')
  const load = useCallback(() => {
    api(`/api/ideas/?group=${group.id}&page_size=100`)
      .then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [group.id])
  useEffect(() => { load() }, [load])

  const add = async () => {
    if (!title.trim()) return
    setErr('')
    try {
      await api('/api/ideas/', { method: 'POST', body: { title: title.trim(), group: group.id } })
      setTitle(''); load()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>
  return (
    <div>
      <div className="filters">
        <input placeholder="Add an idea for this group…" value={title}
          onChange={e => setTitle(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} style={{ width: 320 }} />
        <button className="btn btn-primary" disabled={!title.trim()} onClick={add}>Add</button>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No ideas yet — drop the first one.</p>}
      <div className="task-list">
        {rows.map(i => (
          <div className="task-row" key={i.id}>
            <div className="task-main">
              <div className="task-title">{i.title} <span className={`q-pill q-${i.status}`}>{i.status_display}</span></div>
              <div className="when">{i.author_detail?.name} · {fmtDT(i.created_at)} · ▲ {i.vote_count}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function GroupLinks({ group }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api(`/api/links/?group=${group.id}`).then(setRows).catch(e => setErr(e.message))
  }, [group.id])
  if (err) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>
  return (
    <div>
      <p className="muted small">Add group links from the Links page — pick "{group.name}" as the group.</p>
      {rows.length === 0 && <p className="muted">No links scoped to this group.</p>}
      {rows.map(l => (
        <div className="doc-row" key={l.id} style={{ maxWidth: 620 }}>
          <a href={l.url} target="_blank" rel="noreferrer">{l.title}</a>
          <span className="when">{l.collection_name}</span>
        </div>
      ))}
    </div>
  )
}

function GroupMembers({ group, onChanged }) {
  const [team, setTeam] = useState([])
  const [adding, setAdding] = useState('')
  const [err, setErr] = useState('')
  // assignees = ALL active users -- a group owner can add any colleague,
  // not just the people who report to them (which is what /api/team/ returns now)
  useEffect(() => { api('/api/leads/assignees/').then(setTeam).catch(() => {}) }, [])

  const memberIds = group.members_detail.map(m => m.id)
  const available = team.filter(t => !memberIds.includes(t.id))

  const change = async (action, userId) => {
    setErr('')
    try {
      await api(`/api/groups/${group.id}/${action}/`, { method: 'POST', body: { user: userId } })
      onChanged()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <div style={{ maxWidth: 560 }}>
      {err && <div className="err">{err}</div>}
      {group.can_manage && (
        <div className="filters">
          <select value={adding} onChange={e => {
            const id = Number(e.target.value)
            if (id) { change('add_member', id); setAdding('') }
          }}>
            <option value="">+ Add member…</option>
            {available.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      )}
      <table className="table">
        <thead><tr><th>Member</th><th>Role</th>{group.can_manage && <th />}</tr></thead>
        <tbody>
          {group.members_detail.map(m => (
            <tr key={m.id}>
              <td><strong>{m.name}</strong>{m.id === group.owner_detail?.id && <span className="ai-chip" style={{ marginLeft: 8 }}>owner</span>}</td>
              <td>{m.role}</td>
              {group.can_manage && (
                <td className="row-actions">
                  {m.id !== group.owner_detail?.id && (
                    <button className="btn btn-sm" onClick={() => change('remove_member', m.id)}>Remove</button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
