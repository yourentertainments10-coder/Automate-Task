/* Mistake / Error Register — three-level accountability (Sir's 20 Aug spec).
   Employee owns the mistake → manager owns the correction → dept head owns
   repeats → founder sees only what matters. */
import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : null

const SEVERITIES = [
  ['low', 'Low', 'Minor mistake, negligible impact'],
  ['medium', 'Medium', 'Rework / customer delay / internal impact'],
  ['high', 'High', 'Significant financial or customer impact'],
  ['critical', 'Critical', 'Major loss, compliance issue, fraud risk'],
]
const ROOT_CAUSES = [
  ['lack_of_training', 'Lack of training'], ['lack_of_attention', 'Lack of attention'],
  ['sop_not_followed', 'SOP not followed'], ['sop_missing', 'SOP missing'],
  ['sop_unclear', 'SOP unclear'], ['wrong_information', 'Wrong information provided'],
  ['communication_failure', 'Communication failure'], ['system_issue', 'System issue'],
  ['data_issue', 'Data issue'], ['workload_issue', 'Workload issue'],
  ['time_pressure', 'Time pressure'], ['approval_failure', 'Approval failure'],
  ['human_error', 'Human error'], ['managerial_failure', 'Managerial failure'],
  ['vendor_issue', 'Vendor issue'], ['customer_issue', 'Customer issue'],
  ['other', 'Other'],
]
const CLASSIFICATIONS = [
  ['human', 'Human Mistake'], ['process', 'Process/SOP Failure'],
  ['system', 'Software/System Failure'], ['management', 'Management/Training Failure'],
  ['external', 'External Failure'],
]
const LEVEL3_ACTIONS = [
  ['coaching', 'Coaching'], ['retraining', 'Retraining'],
  ['written_warning', 'Written warning'], ['pip', 'Performance Improvement Plan'],
  ['role_reassignment', 'Role reassignment'],
  ['additional_approval', 'Additional approval requirement'],
  ['process_change', 'Process change'],
  ['permission_suspension', 'Suspension of certain permissions'],
  ['other', 'Other HR-approved action'],
]

const sevClass = (s) => ({ low: '', medium: '', high: 'prio prio-high', critical: 'prio prio-urgent' }[s] || '')

export default function Mistakes() {
  const { user, can } = useAuth()
  const isAdmin = can('tasks.view_all')
  const canLog = can('tasks.assign')
  const [rows, setRows] = useState(null)
  const [filters, setFilters] = useState({ status: '', severity: '', important: false })
  const [openId, setOpenId] = useState(null)
  const [showLog, setShowLog] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const p = new URLSearchParams({ page_size: '100' })
    if (filters.status) p.set('status', filters.status)
    if (filters.severity) p.set('severity', filters.severity)
    if (filters.important) p.set('important', 'true')
    api(`/api/mistakes/?${p}`).then(d => setRows(d.results || d)).catch(e => setErr(e.message))
  }, [filters])
  useEffect(() => { load() }, [load])

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading register…</div>

  return (
    <div>
      <div className="page-head">
        <h1>Mistake Register</h1>
        <span className="muted small">Record → explain → correct → prevent. Nobody gets blamed automatically.</span>
      </div>
      <div className="filters">
        <select value={filters.status} onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}>
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="explained">Explained</option>
          <option value="resolved">Resolved</option>
        </select>
        <select value={filters.severity} onChange={e => setFilters(f => ({ ...f, severity: e.target.value }))}>
          <option value="">All severities</option>
          {SEVERITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {isAdmin && (
          <button className={'chip' + (filters.important ? ' on' : '')}
            title="Critical / escalated / overdue / third occurrences only"
            onClick={() => setFilters(f => ({ ...f, important: !f.important }))}>
            ⚑ Action required
          </button>
        )}
        <span style={{ flex: 1 }} />
        <button className="btn btn-primary" onClick={() => setShowLog(true)}>
          + Log mistake
        </button>
      </div>
      {err && <div className="err">{err}</div>}
      <InsightsPanel isAdmin={isAdmin} isManager={isAdmin || can('tasks.view_department')} />
      {rows.length === 0 && <p className="muted">Nothing here — clean register. 🎉</p>}
      <div className="task-list">
        {rows.map(m => (
          <MistakeRow key={m.id} m={m} me={user} open={openId === m.id}
            onToggle={() => setOpenId(openId === m.id ? null : m.id)}
            onChanged={load} />
        ))}
      </div>
      {showLog && (
        <LogMistakeModal user={user} canLogOthers={canLog}
          onClose={() => setShowLog(false)}
          onSaved={() => { setShowLog(false); load() }} />
      )}
    </div>
  )
}

/* M3/M4: founder "Action Required" card, process-pattern smells, dept scores */
function InsightsPanel({ isAdmin, isManager }) {
  const [summary, setSummary] = useState(null)
  const [pats, setPats] = useState(null)
  const [depts, setDepts] = useState(null)
  const [open, setOpen] = useState(true)
  useEffect(() => {
    if (isAdmin) api('/api/mistakes/founder_summary/').then(setSummary).catch(() => {})
    if (isManager) {
      api('/api/mistakes/patterns/?days=90').then(setPats).catch(() => {})
      api('/api/mistakes/department_scores/?range=this_month').then(setDepts).catch(() => {})
    }
  }, [isAdmin, isManager])
  if (!isManager) return null
  const smells = pats?.categories?.filter(c => c.process_suspect) || []
  return (
    <div className="rule-card" style={{ marginBottom: 14 }}>
      <div className="rule-head" style={{ cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <h3>{isAdmin ? '⚑ Action required (founder view)' : '📊 Team insights'} {open ? '▾' : '▸'}</h3>
      </div>
      {open && (
        <>
          {summary && (
            <div className="stats" style={{ gridTemplateColumns: 'repeat(6, 1fr)' }}>
              <div className={'stat' + (summary.critical_open ? ' alert' : '')}><div className="label">Critical open</div><div className="value">{summary.critical_open}</div></div>
              <div className={'stat' + (summary.sla_missed ? ' alert' : '')}><div className="label">SLA missed</div><div className="value">{summary.sla_missed}</div></div>
              <div className={'stat' + (summary.escalated_to_founder ? ' alert' : '')}><div className="label">Escalated to you</div><div className="value">{summary.escalated_to_founder}</div></div>
              <div className="stat"><div className="label">3rd occurrences</div><div className="value">{summary.level3_open}</div></div>
              <div className="stat"><div className="label">Loss this month</div><div className="value">₹{Number(summary.loss_this_month).toLocaleString('en-IN')}</div></div>
              <div className="stat"><div className="label">Open total</div><div className="value">{summary.open_total}</div></div>
            </div>
          )}
          {smells.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <strong className="small">Process smells (90 days) — fix the process, not the people</strong>
              {smells.map(c => (
                <div key={c.category} className="small" style={{ padding: '3px 0' }}>
                  🔁 <strong>{c.category}</strong> — {c.message}
                  {c.financial_loss > 0 && <> ₹{Number(c.financial_loss).toLocaleString('en-IN')} loss.</>}
                </div>
              ))}
            </div>
          )}
          {pats?.repeat_offenders?.length > 0 && (
            <div className="small muted" style={{ marginTop: 6 }}>
              Repeat (90d): {pats.repeat_offenders.slice(0, 5).map(o => `${o.name} ×${o.count} ${o.category}`).join(' · ')}
            </div>
          )}
          {depts?.rows?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <strong className="small" title={depts.formula}>Department accountability score (this month) ⓘ</strong>
              <table className="table" style={{ maxWidth: 720, marginTop: 4 }}>
                <thead><tr><th>Department</th><th>Score</th><th>Mistakes</th><th>Repeats</th><th>SLA</th><th>Loss</th><th>vs last period</th></tr></thead>
                <tbody>
                  {depts.rows.map(r => (
                    <tr key={r.department}>
                      <td><strong>{r.label}</strong></td>
                      <td title={`−${r.breakdown.repeat_penalty} repeats · −${r.breakdown.sla_penalty} SLA · −${r.breakdown.loss_penalty} loss · +${r.breakdown.improvement_bonus} improvement`}>
                        <strong>{r.score}</strong></td>
                      <td>{r.mistakes}</td>
                      <td className={r.repeats ? 'late' : ''}>{r.repeats}</td>
                      <td>{r.sla_compliance ?? '—'}{r.sla_compliance != null && '%'}</td>
                      <td>{r.financial_loss ? `₹${Number(r.financial_loss).toLocaleString('en-IN')}` : '—'}</td>
                      <td className={r.improvement_pct > 0 ? 'ok' : r.improvement_pct < 0 ? 'late' : ''}>
                        {r.improvement_pct == null ? '—' : `${r.improvement_pct > 0 ? '▼' : '▲'} ${Math.abs(r.improvement_pct)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function LevelBanner({ m }) {
  if (m.occurrence_level >= 3) {
    return <div className="err" style={{ marginTop: 6 }}>
      🔺 THIRD OCCURRENCE — PERFORMANCE ESCALATION · department-head action required
    </div>
  }
  if (m.occurrence_level === 2) {
    return <div className="err" style={{ marginTop: 6, background: 'rgba(240,160,0,.12)', color: '#9a6700' }}>
      ⚠ REPEAT ERROR DETECTED (earlier: {m.repeat_of_code}) — root cause + corrective + preventive action mandatory
    </div>
  }
  return null
}

function MistakeRow({ m, me, open, onToggle, onChanged }) {
  return (
    <div className={'task-row' + (m.sla_overdue ? ' overdue' : '')} style={{ flexWrap: 'wrap' }}>
      <div className="task-main" style={{ cursor: 'pointer' }} onClick={onToggle}>
        <div className="task-title">
          <span className="t-code">{m.code}</span>
          {m.category}
          <span className={sevClass(m.severity)}>{m.severity_display}</span>
          <span className={`q-pill q-${m.status === 'resolved' ? 'approved' : 'under_review'}`}>{m.status_display}</span>
          {m.occurrence_level > 1 && <span className="prio prio-urgent">×{m.occurrence_level}</span>}
          {m.escalation_level > 0 && (
            <span className="ai-chip">↑ {m.escalation_level === 1 ? 'dept head' : 'founder'}</span>
          )}
          {m.classification && <span className="ai-chip">{m.classification_display}</span>}
        </div>
        <div className="small muted">{m.description}</div>
        <div className="when">
          {m.employee_detail?.name}
          {m.manager_detail && <> · manager: {m.manager_detail.name}</>}
          {m.financial_loss && <> · ₹{Number(m.financial_loss).toLocaleString('en-IN')} loss</>}
          {' · '}{fmtDT(m.created_at)}
          {m.sla_due_at && m.status !== 'resolved' && (
            <span className={m.sla_overdue ? ' late' : ''}>
              {' · SLA '}{m.sla_overdue ? 'MISSED' : `till ${fmtDT(m.sla_due_at)}`}
            </span>
          )}
        </div>
      </div>
      {open && <MistakeDetail m={m} me={me} onChanged={onChanged} />}
    </div>
  )
}

function MistakeDetail({ m, me, onChanged }) {
  const { can } = useAuth()
  const [detail, setDetail] = useState(null)
  const [events, setEvents] = useState(null)
  const [err, setErr] = useState('')
  const isEmployee = m.employee_detail?.id === me.id
  const isReviewer = !isEmployee && (can('tasks.view_all') || m.manager_detail?.id === me.id
    || can('tasks.view_department'))

  useEffect(() => {
    api(`/api/mistakes/${m.id}/`).then(setDetail).catch(() => setDetail({}))
    api(`/api/mistakes/${m.id}/events/`).then(setEvents).catch(() => {})
  }, [m.id, m.updated_at])

  const post = async (path, body) => {
    setErr('')
    try { await api(`/api/mistakes/${m.id}/${path}/`, { method: 'POST', body }); onChanged() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <div style={{ flexBasis: '100%', borderTop: '1px solid var(--line)', marginTop: 8, paddingTop: 8 }}>
      <LevelBanner m={m} />
      {err && <div className="err">{err}</div>}

      {m.explanation && (
        <p className="small" style={{ marginTop: 6 }}>
          <strong>Explanation:</strong> {m.explanation}
          {m.root_cause_display && <> · <strong>Root cause:</strong> {m.root_cause_display}</>}
          {m.corrective_action && <><br /><strong>Corrective:</strong> {m.corrective_action}</>}
          {m.preventive_action && <><br /><strong>Preventive:</strong> {m.preventive_action}</>}
        </p>
      )}
      {m.sop_name && (
        <p className="small muted">
          SOP: {m.sop_name} {m.sop_version && `v${m.sop_version}`}
          {m.sop_followed != null && <> · followed: {m.sop_followed ? 'yes' : 'NO — employee side'}</>}
          {m.sop_adequate != null && <> · adequate: {m.sop_adequate ? 'yes' : 'NO — fix the process, not the person'}</>}
        </p>
      )}
      {m.corrective_task_code && (
        <p className="small muted">Corrective task: <strong>{m.corrective_task_code}</strong> ({m.corrective_task_status})</p>
      )}
      {m.manager_remarks && <p className="small"><strong>Manager:</strong> {m.manager_remarks}
        {m.level3_action_display && <> · <strong>Action:</strong> {m.level3_action_display}</>}</p>}

      {isEmployee && m.status !== 'resolved' && <ExplainForm m={m} onPost={post} />}
      {isReviewer && detail?.possible_repeats?.length > 0 && !m.repeat_of && (
        <RepeatPrompt candidates={detail.possible_repeats} onPost={post} />
      )}
      {isReviewer && m.status !== 'resolved' && <ReviewForm m={m} onPost={post} />}

      {events?.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="small muted" style={{ cursor: 'pointer' }}>History ({events.length})</summary>
          {events.map(ev => (
            <div key={ev.id} className="small muted" style={{ padding: '2px 0 2px 12px' }}>
              {fmtDT(ev.created_at)} — {ev.actor?.name || 'System'}: {ev.text}
            </div>
          ))}
        </details>
      )}
    </div>
  )
}

function ExplainForm({ m, onPost }) {
  const [f, setF] = useState({ explanation: '', root_cause: '', root_cause_note: '',
    corrective_action: '', preventive_action: '' })
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))
  const needsCapa = m.occurrence_level >= 2
  return (
    <div style={{ marginTop: 8, padding: 10, background: 'var(--bg)', borderRadius: 8 }}>
      <strong className="small">Your response</strong>
      <div className="form-grid" style={{ marginTop: 6 }}>
        <div className="wide">
          <label>What happened? *</label>
          <input value={f.explanation} onChange={set('explanation')}
            placeholder="'Mistake happened' is not an explanation — say what actually went wrong" />
        </div>
        <div>
          <label>Root cause *</label>
          <select value={f.root_cause} onChange={set('root_cause')}>
            <option value="">— pick —</option>
            {ROOT_CAUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div>
          <label>Root cause detail</label>
          <input value={f.root_cause_note} onChange={set('root_cause_note')} />
        </div>
        <div>
          <label>Corrective action {needsCapa ? '*' : ''} (fix it now)</label>
          <input value={f.corrective_action} onChange={set('corrective_action')} />
        </div>
        <div>
          <label>Preventive action {needsCapa ? '*' : ''} (never again)</label>
          <input value={f.preventive_action} onChange={set('preventive_action')} />
        </div>
      </div>
      <div style={{ marginTop: 8 }}>
        <button className="btn btn-sm btn-primary"
          disabled={!f.explanation.trim() || !f.root_cause
            || (needsCapa && (!f.corrective_action.trim() || !f.preventive_action.trim()))}
          onClick={() => onPost('explain', f)}>Submit response</button>
      </div>
    </div>
  )
}

function RepeatPrompt({ candidates, onPost }) {
  return (
    <div style={{ marginTop: 8, padding: 10, background: 'rgba(240,160,0,.1)', borderRadius: 8 }}>
      <strong className="small">⚠ Possible repeat — is this the same error as before?</strong>
      {candidates.map(c => (
        <div key={c.id} className="small" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
          <span style={{ flex: 1 }}><strong>{c.code}</strong> · {c.description} ({fmtDT(c.created_at)})</span>
          <button className="btn btn-sm btn-primary"
            onClick={() => onPost('confirm_repeat', { same: true, repeat_of: c.id })}>Same error</button>
        </div>
      ))}
      <div style={{ marginTop: 6 }}>
        <button className="btn btn-sm" onClick={() => onPost('confirm_repeat', { same: false })}>
          Different error
        </button>
      </div>
    </div>
  )
}

function ReviewForm({ m, onPost }) {
  const [f, setF] = useState({
    classification: m.classification || '', manager_remarks: m.manager_remarks || '',
    sop_name: m.sop_name || '', sop_followed: m.sop_followed, sop_adequate: m.sop_adequate,
    level3_action: m.level3_action || '', level3_action_note: '',
  })
  const [task, setTask] = useState(false)
  const [taskTitle, setTaskTitle] = useState('')
  const [hint, setHint] = useState(null)     // M3: AI/rules suggestion
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))
  const askSuggestion = async () => {
    try {
      const s = await api(`/api/mistakes/${m.id}/ai_suggest/`, { method: 'POST' })
      setHint(s)
    } catch { setHint({ reasoning: 'Could not fetch a suggestion.' }) }
  }
  const useHint = () => setF(p => ({
    ...p,
    classification: hint.classification || p.classification,
    manager_remarks: p.manager_remarks
      || `Corrective: ${hint.corrective_action} Preventive: ${hint.preventive_action}`,
  }))
  const setB = k => e => setF(p => ({ ...p, [k]: e.target.value === '' ? null : e.target.value === 'yes' }))
  const body = (resolve) => ({
    ...f,
    sop_followed: f.sop_followed, sop_adequate: f.sop_adequate,
    resolve,
  })
  return (
    <div style={{ marginTop: 8, padding: 10, background: 'var(--bg)', borderRadius: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong className="small">Manager review — a review is a decision, not a click</strong>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn-sm" onClick={askSuggestion}
          title="Suggests classification + corrective/preventive action — you still decide">✨ Suggest</button>
      </div>
      {hint && (
        <div className="small" style={{ margin: '6px 0', padding: 8, background: 'rgba(13,122,95,.08)', borderRadius: 6 }}>
          {hint.classification && <><strong>Suggested:</strong> {CLASSIFICATIONS.find(([v]) => v === hint.classification)?.[1]} — </>}
          {hint.reasoning}
          {hint.corrective_action && <><br /><strong>Corrective:</strong> {hint.corrective_action}</>}
          {hint.preventive_action && <><br /><strong>Preventive:</strong> {hint.preventive_action}</>}
          {hint.classification && (
            <div style={{ marginTop: 4 }}>
              <button type="button" className="btn btn-sm" onClick={useHint}>Use suggestion</button>
              <span className="muted"> ({hint.provider})</span>
            </div>
          )}
        </div>
      )}
      <div className="form-grid" style={{ marginTop: 6 }}>
        <div>
          <label>What failed? *</label>
          <select value={f.classification} onChange={set('classification')}>
            <option value="">— classify —</option>
            {CLASSIFICATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div>
          <label>SOP name (if any)</label>
          <input value={f.sop_name} onChange={set('sop_name')} />
        </div>
        <div>
          <label>SOP followed?</label>
          <select value={f.sop_followed == null ? '' : f.sop_followed ? 'yes' : 'no'} onChange={setB('sop_followed')}>
            <option value="">—</option><option value="yes">Yes</option>
            <option value="no">No — employee side</option>
          </select>
        </div>
        <div>
          <label>SOP adequate?</label>
          <select value={f.sop_adequate == null ? '' : f.sop_adequate ? 'yes' : 'no'} onChange={setB('sop_adequate')}>
            <option value="">—</option><option value="yes">Yes</option>
            <option value="no">No — fix the process</option>
          </select>
        </div>
        {m.occurrence_level >= 3 && (
          <>
            <div>
              <label>Level-3 action * (human decision)</label>
              <select value={f.level3_action} onChange={set('level3_action')}>
                <option value="">— decide —</option>
                {LEVEL3_ACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label>Action note</label>
              <input value={f.level3_action_note} onChange={set('level3_action_note')} />
            </div>
          </>
        )}
        <div className="wide">
          <label>Remarks / decision *</label>
          <input value={f.manager_remarks} onChange={set('manager_remarks')}
            placeholder="training / SOP change / system fix / no action because…" />
        </div>
      </div>
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-sm" onClick={() => onPost('review', body(false))}>Save review</button>
        <button className="btn btn-sm btn-primary" onClick={() => onPost('review', body(true))}>
          Save &amp; resolve
        </button>
        {!m.corrective_task_code && !task && (
          <button className="btn btn-sm" onClick={() => setTask(true)}>+ Corrective task</button>
        )}
        {task && (
          <span style={{ display: 'flex', gap: 6 }}>
            <input placeholder={`Audit: ${m.category}`} value={taskTitle}
              onChange={e => setTaskTitle(e.target.value)} style={{ width: 220 }} />
            <button className="btn btn-sm btn-primary"
              onClick={() => onPost('create_task', { title: taskTitle, due_days: 1 })}>
              Create (due tomorrow)
            </button>
          </span>
        )}
      </div>
    </div>
  )
}

function LogMistakeModal({ user, canLogOthers, onClose, onSaved }) {
  const [team, setTeam] = useState([])
  const [cats, setCats] = useState([])
  const [f, setF] = useState({
    employee: String(user.id), category: '', severity: 'medium',
    description: '', impact: '', financial_loss: '', sop_name: '',
  })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))

  useEffect(() => {
    api('/api/mistake-categories/').then(setCats).catch(() => {})
    if (canLogOthers) api('/api/tasks/assignees/').then(setTeam).catch(() => {})
  }, [canLogOthers])

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await api('/api/mistakes/', {
        method: 'POST',
        body: {
          employee: Number(f.employee), category: f.category, severity: f.severity,
          description: f.description, impact: f.impact,
          financial_loss: f.financial_loss ? Number(f.financial_loss) : null,
          sop_name: f.sop_name,
        },
      })
      onSaved()
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>Log a mistake</h2>
        <p className="muted small">
          Recording is the first step of fixing — this is about the process
          as much as the person.
        </p>
        <div className="form-grid">
          <div>
            <label>Employee *</label>
            {canLogOthers ? (
              <select value={f.employee} onChange={set('employee')}>
                {team.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            ) : (
              <input value={user.first_name || user.username} disabled />
            )}
          </div>
          <div>
            <label>Category *</label>
            <select value={f.category} onChange={set('category')}>
              <option value="">— pick —</option>
              {cats.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div className="wide">
            <label>Severity *</label>
            <select value={f.severity} onChange={set('severity')}>
              {SEVERITIES.map(([v, l, hint]) => <option key={v} value={v}>{l} — {hint}</option>)}
            </select>
          </div>
          <div className="wide">
            <label>What happened? *</label>
            <textarea rows={3} value={f.description} onChange={set('description')}
              style={{ width: '100%', border: '1px solid var(--line)', borderRadius: 9, padding: '9px 11px' }}
              placeholder="e.g. Wrong Hyundai part ordered for customer XYZ" />
          </div>
          <div>
            <label>Impact</label>
            <input value={f.impact} onChange={set('impact')}
              placeholder="time loss / delay / customer anger…" />
          </div>
          <div>
            <label>Financial loss (₹)</label>
            <input type="number" min="0" step="0.01" value={f.financial_loss}
              onChange={set('financial_loss')} placeholder="optional" />
          </div>
          <div className="wide">
            <label>Related SOP (if known)</label>
            <input value={f.sop_name} onChange={set('sop_name')} placeholder="optional" />
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary"
            disabled={busy || !f.category || !f.description.trim()}>
            {busy ? 'Saving…' : 'Log mistake'}
          </button>
        </div>
      </form>
    </div>
  )
}
