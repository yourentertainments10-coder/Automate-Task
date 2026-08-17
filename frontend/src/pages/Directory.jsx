import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

/* Industry Task Template Directory — browse industries → categories →
   templates, preview the steps, then use the template. */
export default function Directory() {
  const { can } = useAuth()
  const canManageTemplates = can('tasks.assign')
  const [industries, setIndustries] = useState(null)
  const [industry, setIndustry] = useState(null)
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [templates, setTemplates] = useState(null)
  const [open, setOpen] = useState(null)
  const [team, setTeam] = useState([])
  const [groups, setGroups] = useState([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api('/api/directory/industries/').then(setIndustries).catch(e => setErr(e.message))
    api('/api/groups/?active=true').then(setGroups).catch(() => {})
    if (canManageTemplates) api('/api/leads/assignees/').then(setTeam).catch(() => {})
  }, [canManageTemplates])

  const loadTemplates = useCallback(() => {
    if (!industry && !q.trim()) { setTemplates(null); return }
    const p = new URLSearchParams()
    if (industry) p.set('industry', industry.id)
    if (category) p.set('category', category)
    if (q.trim()) p.set('search', q.trim())
    api(`/api/directory/templates/?${p}`).then(setTemplates).catch(e => setErr(e.message))
  }, [industry, category, q])
  useEffect(() => { loadTemplates() }, [loadTemplates])

  const use = async (tpl, action, body) => {
    setErr(''); setMsg('')
    try {
      const res = await api(`/api/directory/templates/${tpl.id}/${action}/`, { method: 'POST', body })
      setMsg(action === 'create_tasks'
        ? `✅ Created ${res.length} task(s) from "${tpl.name}".`
        : `✅ Added ${res.length} template(s) to your Task Templates.`)
      setOpen(null)
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !industries) return <div className="err">{err}</div>
  if (!industries) return <div className="center-note">Loading directory…</div>

  return (
    <div>
      <div className="filters">
        <input type="search" placeholder="Search all templates…" value={q}
          onChange={e => { setQ(e.target.value); if (e.target.value) setIndustry(null) }} style={{ width: 260 }} />
        {industry && (
          <>
            <button className="btn btn-sm" onClick={() => { setIndustry(null); setCategory('') }}>← All industries</button>
            <select value={category} onChange={e => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {industry.categories.map(c => <option key={c}>{c}</option>)}
            </select>
          </>
        )}
      </div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="placeholder-card" style={{ marginTop: 0, marginBottom: 12 }}><h3>{msg}</h3></div>}

      {!industry && !q.trim() && (
        <div className="group-grid">
          {industries.map(i => (
            <div key={i.id} className="dash-card group-card" onClick={() => { setIndustry(i); setCategory('') }}>
              <div className="task-title"><span style={{ fontSize: 20 }}>{i.icon}</span> {i.name}</div>
              {i.description && <div className="small muted" style={{ marginTop: 4 }}>{i.description}</div>}
              <div className="when" style={{ marginTop: 8 }}>
                {i.template_count} template{i.template_count === 1 ? '' : 's'} · {i.categories.length} categor{i.categories.length === 1 ? 'y' : 'ies'}
              </div>
            </div>
          ))}
        </div>
      )}

      {(industry || q.trim()) && (
        <div style={{ maxWidth: 820 }}>
          {industry && <h3 className="tpl-cat">{industry.icon} {industry.name}</h3>}
          {templates && templates.length === 0 && <p className="muted">No templates match.</p>}
          <div className="task-list">
            {(templates || []).map(t => (
              <div className="task-row" key={t.id} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <div className="task-main" style={{ cursor: 'pointer' }}
                    onClick={() => setOpen(open?.id === t.id ? null : t)}>
                    <div className="task-title">
                      {t.name}
                      <span className="ai-chip">{t.category}</span>
                      {!industry && <span className="ai-chip">{t.industry_icon} {t.industry_name}</span>}
                      {t.frequency !== 'one_time' && <span className="ai-chip">↻ {t.frequency}</span>}
                      {t.priority !== 'normal' && <span className={`prio prio-${t.priority}`}>{t.priority}</span>}
                    </div>
                    {t.description && <div className="small muted">{t.description}</div>}
                    <div className="when">{t.step_count} step{t.step_count === 1 ? '' : 's'}
                      {t.tags?.length > 0 && ` · ${t.tags.join(', ')}`}</div>
                  </div>
                  <button className="btn btn-sm" onClick={() => setOpen(open?.id === t.id ? null : t)}>
                    {open?.id === t.id ? 'Hide' : 'Preview'}
                  </button>
                </div>
                {open?.id === t.id && (
                  <TemplateDetail tpl={t} team={team} groups={groups}
                    canManageTemplates={canManageTemplates} onUse={use} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function TemplateDetail({ tpl, team, groups, canManageTemplates, onUse }) {
  const [assignee, setAssignee] = useState('')
  const [group, setGroup] = useState('')
  return (
    <div style={{ paddingTop: 12 }}>
      <ol className="dir-steps">
        {tpl.steps.map((s, i) => (
          <li key={i}>
            <strong>{s.title}</strong>
            {s.offset_days > 0 && <span className="ai-chip">day +{s.offset_days}</span>}
            {s.description && <div className="small muted">{s.description}</div>}
          </li>
        ))}
      </ol>
      <div className="filters" style={{ marginTop: 10 }}>
        {canManageTemplates && (
          <select value={assignee} onChange={e => setAssignee(e.target.value)}>
            <option value="">Assign to me</option>
            {team.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        )}
        {groups.length > 0 && (
          <select value={group} onChange={e => setGroup(e.target.value)}>
            <option value="">No group</option>
            {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        )}
        <button className="btn btn-primary" onClick={() => onUse(tpl, 'create_tasks', {
          ...(assignee ? { assigned_to: Number(assignee) } : {}),
          ...(group ? { group: Number(group) } : {}),
        })}>
          Create {tpl.step_count} task{tpl.step_count === 1 ? '' : 's'}
        </button>
        {canManageTemplates && (
          <button className="btn" onClick={() => onUse(tpl, 'add_to_my_templates')}>
            Add to my Task Templates
          </button>
        )}
      </div>
    </div>
  )
}
