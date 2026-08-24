import { useEffect, useState } from 'react'
import { api, errorText } from '../api'

const DEPARTMENTS = [
  ['sales', 'Sales'], ['purchase', 'Purchase'], ['accounts', 'Accounts'],
  ['support', 'IT Team'], ['management', 'Management'],
]

export default function Settings() {
  const [rules, setRules] = useState([])
  const [team, setTeam] = useState([])
  const [taskCfg, setTaskCfg] = useState(null)
  const [err, setErr] = useState('')

  const load = () => Promise.all([
    api('/api/assignment-rules/'),
    api('/api/leads/assignees/'),
    api('/api/task-settings/'),
  ]).then(([r, t, c]) => { setRules(r.results || r); setTeam(t); setTaskCfg(c) }).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const setPolicy = async (key, value) => {
    setErr('')
    try { setTaskCfg(await api('/api/task-settings/', { method: 'POST', body: { [key]: value } })) }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <div>
      <div className="page-head"><h1>Automation Settings</h1></div>
      {taskCfg && (
        <div className="rule-card">
          <div className="rule-head"><h3>Task completion evidence</h3></div>
          <p className="muted small">
            Force proof-of-work when someone completes a task — stops the
            "just keeps ticking it daily" problem.
          </p>
          <div className="rule-members" style={{ gap: 18 }}>
            <span className="muted small">✓ Completion description: <strong>always required</strong> (org rule, not a toggle)</span>
            <label className="switch">
              <input type="checkbox" checked={taskCfg.require_completion_attachment}
                onChange={e => setPolicy('require_completion_attachment', e.target.checked)} />
              <span>File / photo proof required</span>
            </label>
          </div>
        </div>
      )}
      <CategoryManager onError={setErr} />
      <p className="muted" style={{ marginBottom: 16 }}>
        Auto-assignment rules: when a new lead arrives without an assignee (manual entry,
        or WhatsApp/Gmail/AI intake in Phase 3), the rule for its department picks the owner.
      </p>
      {err && <div className="err">{err}</div>}
      {DEPARTMENTS.map(([dept, label]) => (
        <RuleCard key={dept} dept={dept} label={label}
          rule={rules.find(r => r.department === dept)}
          team={team} onChanged={load} onError={setErr} />
      ))}
    </div>
  )
}

/* F1: managed task categories — admin CRUD with live task counts */
function CategoryManager({ onError }) {
  const [cats, setCats] = useState(null)
  const [f, setF] = useState({ name: '', department: '' })

  const load = () => api('/api/task-categories/?counts=true')
    .then(setCats).catch(e => onError(e.message))
  useEffect(() => { load() }, [])

  const add = async () => {
    onError('')
    try {
      await api('/api/task-categories/', { method: 'POST', body: f })
      setF({ name: '', department: '' }); load()
    } catch (e) { onError(errorText(e.data) || e.message) }
  }
  const remove = async (c) => {
    onError('')
    try { await api(`/api/task-categories/${c.id}/`, { method: 'DELETE' }); load() }
    catch (e) { onError(errorText(e.data) || e.message) }
  }

  return (
    <div className="rule-card">
      <div className="rule-head"><h3>Task categories</h3></div>
      <p className="muted small">
        The dropdown employees pick from (managers can also add inline while
        creating a task). Deleting hides a category from the dropdown —
        existing tasks keep their history; re-adding the name brings it back.
      </p>
      <div className="filters">
        <input placeholder="New category name" value={f.name}
          onChange={e => setF(p => ({ ...p, name: e.target.value }))} />
        <select value={f.department} onChange={e => setF(p => ({ ...p, department: e.target.value }))}>
          <option value="">General (all departments)</option>
          {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          <option value="development">Developer Team</option>
          <option value="hr">Human Resources</option>
        </select>
        <button className="btn btn-primary" disabled={!f.name.trim()} onClick={add}>Add</button>
      </div>
      {cats && (
        <table className="table" style={{ maxWidth: 560 }}>
          <thead><tr><th>Category</th><th>Department</th><th>Tasks</th><th /></tr></thead>
          <tbody>
            {cats.map(c => (
              <tr key={c.id}>
                <td><strong>{c.name}</strong></td>
                <td>{c.department_display || 'General'}</td>
                <td>{c.task_count ?? 0}</td>
                <td className="row-actions">
                  <button className="btn btn-sm" onClick={() => remove(c)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function RuleCard({ dept, label, rule, team, onChanged, onError }) {
  const [adding, setAdding] = useState('')

  const save = async (body) => {
    onError('')
    try {
      if (rule) await api(`/api/assignment-rules/${rule.id}/`, { method: 'PATCH', body })
      else await api('/api/assignment-rules/', { method: 'POST', body: { department: dept, strategy: 'round_robin', member_ids: [], active: true, ...body } })
      onChanged()
    } catch (e) { onError(errorText(e.data) || e.message) }
  }

  const members = rule?.members_detail || []
  const memberIds = rule?.member_ids || []
  const available = team.filter(t => !memberIds.includes(t.id))

  const move = (idx, dir) => {
    const next = [...memberIds]
    const j = idx + dir
    if (j < 0 || j >= next.length) return
    ;[next[idx], next[j]] = [next[j], next[idx]]
    save({ member_ids: next })
  }

  return (
    <div className="rule-card">
      <div className="rule-head">
        <h3>{label}</h3>
        {rule && (
          <label className="switch">
            <input type="checkbox" checked={rule.active}
              onChange={e => save({ active: e.target.checked })} />
            <span>{rule.active ? 'Active' : 'Off'}</span>
          </label>
        )}
        <select value={rule?.strategy || 'round_robin'}
          onChange={e => save({ strategy: e.target.value })}>
          <option value="round_robin">Round robin</option>
          <option value="fixed">Fixed (first member)</option>
        </select>
      </div>
      <div className="rule-members">
        {members.length === 0 && <span className="muted small">No members — leads stay unassigned.</span>}
        {members.map((m, i) => (
          <span className="member-pill" key={m.id}>
            <em>{i + 1}</em> {m.name}
            <button title="Move up" onClick={() => move(i, -1)}>▲</button>
            <button title="Move down" onClick={() => move(i, 1)}>▼</button>
            <button title="Remove" onClick={() => save({ member_ids: memberIds.filter(id => id !== m.id) })}>✕</button>
          </span>
        ))}
        <select value={adding} onChange={e => {
          const id = Number(e.target.value)
          if (id) { save({ member_ids: [...memberIds, id] }); setAdding('') }
        }}>
          <option value="">+ Add member…</option>
          {available.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      {rule?.strategy === 'round_robin' && members.length > 0 && (
        <div className="small muted">Next in rotation: <strong>{members[(rule.rr_index) % members.length]?.name}</strong></div>
      )}
    </div>
  )
}
