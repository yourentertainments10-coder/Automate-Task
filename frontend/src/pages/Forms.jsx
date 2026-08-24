import { useCallback, useEffect, useState } from 'react'
import { api, errorText, tokens } from '../api'
import { useAuth } from '../auth'
import FormRenderer from './FormRenderer'

const fmtDT = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export const FIELD_TYPES = [
  ['short_text', 'Short text'], ['long_text', 'Long text'], ['number', 'Number'],
  ['email', 'Email'], ['phone', 'Phone'], ['date', 'Date'],
  ['dropdown', 'Dropdown'], ['radio', 'Radio'], ['checkbox', 'Checkbox'], ['file', 'File upload'],
]
const LEAD_ATTRS = [
  ['', '—'], ['customer_name', 'Customer name'], ['phone', 'Phone'],
  ['email', 'Email'], ['company', 'Company'], ['requirement', 'Requirement'],
]
const DEPARTMENTS = [
  ['sales', 'Sales'], ['purchase', 'Purchase'], ['accounts', 'Accounts'],
  ['support', 'IT Team'], ['management', 'Management'],
]
const NEEDS_OPTIONS = ['dropdown', 'radio', 'checkbox']

export default function Forms() {
  const { can } = useAuth()
  const canBuild = can('tasks.assign')
  const [mode, setMode] = useState('fill')          // fill | manage
  const [openForm, setOpenForm] = useState(null)     // form being built
  const [viewSubs, setViewSubs] = useState(null)     // form whose submissions are open
  const [fillForm, setFillForm] = useState(null)     // form being filled in-app

  if (fillForm) return <FillInApp form={fillForm} onBack={() => setFillForm(null)} />
  if (viewSubs) return <Submissions form={viewSubs} onBack={() => setViewSubs(null)} />
  if (openForm) return <Builder formId={openForm} onBack={() => setOpenForm(null)} onSubs={setViewSubs} />

  return (
    <div>
      <div className="page-head">
        <h1>Forms</h1>
        {canBuild && (
          <div className="seg">
            <button className={'seg-btn' + (mode === 'fill' ? ' on' : '')} onClick={() => setMode('fill')}>Fill</button>
            <button className={'seg-btn' + (mode === 'manage' ? ' on' : '')} onClick={() => setMode('manage')}>My Forms</button>
          </div>
        )}
      </div>
      {mode === 'fill'
        ? <FillList onFill={setFillForm} />
        : <ManageList onOpen={setOpenForm} onSubs={setViewSubs} />}
    </div>
  )
}

/* ---------------- Fill (everyone) ---------------- */

function FillList({ onFill }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { api('/api/forms/').then(setRows).catch(e => setErr(e.message)) }, [])
  if (err) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading forms…</div>
  return (
    <div>
      {rows.length === 0 && <p className="muted">No published forms right now.</p>}
      <div className="group-grid">
        {rows.map(f => (
          <div key={f.id} className="dash-card group-card" onClick={() => onFill(f)}>
            <div className="task-title">{f.name}</div>
            {f.description && <div className="small muted" style={{ marginTop: 4 }}>{f.description}</div>}
            <div className="when" style={{ marginTop: 8 }}>{f.fields.length} field(s)</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FillInApp({ form, onBack }) {
  const [done, setDone] = useState(false)
  return (
    <div style={{ maxWidth: 560 }}>
      <div className="page-head">
        <h1><button className="btn btn-sm" onClick={onBack}>←</button> {form.name}</h1>
      </div>
      {done ? (
        <div className="placeholder-card"><h3>✅ Submitted</h3><p>Your response has been recorded.</p></div>
      ) : (
        <FormRenderer
          form={form}
          submitPath={`/api/forms/${form.id}/submit/`}
          authed
          onDone={() => setDone(true)}
        />
      )}
    </div>
  )
}

/* ---------------- Manage list ---------------- */

function ManageList({ onOpen, onSubs }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [name, setName] = useState('')

  const load = useCallback(() => {
    api('/api/forms/?manage=true').then(setRows).catch(e => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const create = async () => {
    if (!name.trim()) return
    setErr('')
    try {
      const f = await api('/api/forms/', { method: 'POST', body: { name: name.trim() } })
      setName(''); onOpen(f.id)
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading…</div>
  return (
    <div style={{ maxWidth: 860 }}>
      <div className="filters">
        <input placeholder="New form name…" value={name} onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') create() }} style={{ width: 260 }} />
        <button className="btn btn-primary" disabled={!name.trim()} onClick={create}>+ Create form</button>
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No forms yet — create your first one.</p>}
      <table className="table">
        <thead><tr><th>Form</th><th>Status</th><th>Fields</th><th>Submissions</th><th>Integrations</th><th /></tr></thead>
        <tbody>
          {rows.map(f => (
            <tr key={f.id}>
              <td><strong>{f.name}</strong><div className="muted small">by {f.created_by_detail?.name}</div></td>
              <td><span className={`q-pill q-${f.status}`}>{f.status_display}</span></td>
              <td>{f.fields.length}</td>
              <td>{f.submission_count}</td>
              <td className="small">
                {f.create_lead && <span className="ai-chip">→ Lead</span>}{' '}
                {f.create_task && <span className="ai-chip">→ Task</span>}
              </td>
              <td className="row-actions">
                <button className="btn btn-sm" onClick={() => onOpen(f.id)}>Build</button>
                <button className="btn btn-sm" onClick={() => onSubs(f)}>Submissions</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ---------------- Builder ---------------- */

function Builder({ formId, onBack, onSubs }) {
  const [form, setForm] = useState(null)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState(false)

  const load = useCallback(() => {
    api(`/api/forms/${formId}/`).then(setForm).catch(e => setErr(e.message))
  }, [formId])
  useEffect(() => { load() }, [load])

  const patch = async (body) => {
    setErr('')
    try { setForm(await api(`/api/forms/${formId}/`, { method: 'PATCH', body })) }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const doAction = async (action) => {
    setErr('')
    try { setForm(await api(`/api/forms/${formId}/${action}/`, { method: 'POST' })) }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !form) return <div className="err">{err}</div>
  if (!form) return <div className="center-note">Loading builder…</div>

  const shareUrl = `${window.location.origin}/f/${form.public_token}`

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="page-head">
        <h1><button className="btn btn-sm" onClick={onBack}>←</button> {form.name}</h1>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={`q-pill q-${form.status}`}>{form.status_display}</span>
          {form.status !== 'published' && <button className="btn btn-primary" onClick={() => doAction(form.status === 'closed' ? 'reopen' : 'publish')}>{form.status === 'closed' ? 'Reopen' : 'Publish'}</button>}
          {form.status === 'published' && <button className="btn" onClick={() => doAction('close')}>Disable</button>}
          <button className="btn" onClick={() => onSubs(form)}>Submissions ({form.submission_count})</button>
        </span>
      </div>
      {err && <div className="err">{err}</div>}

      {form.status === 'published' && (
        <div className="dash-card" style={{ marginBottom: 14 }}>
          <h3>Share link</h3>
          <div className="sim-row">
            <input readOnly value={shareUrl} onFocus={e => e.target.select()} />
            <button className="btn" onClick={() => {
              navigator.clipboard?.writeText(shareUrl).catch(() => {})
              setCopied(true); setTimeout(() => setCopied(false), 1500)
            }}>{copied ? 'Copied!' : 'Copy'}</button>
          </div>
          <p className="muted small" style={{ marginTop: 6 }}>Anyone with this link can submit — no login needed.</p>
        </div>
      )}

      <div className="dash-card" style={{ marginBottom: 14 }}>
        <h3>Details & integrations</h3>
        <div className="form-grid">
          <div><label>Name</label>
            <input defaultValue={form.name} onBlur={e => e.target.value !== form.name && patch({ name: e.target.value })} /></div>
          <div><label>Description</label>
            <input defaultValue={form.description} onBlur={e => e.target.value !== form.description && patch({ description: e.target.value })} /></div>
          <div>
            <label className="switch" style={{ marginTop: 20 }}>
              <input type="checkbox" checked={form.create_lead}
                onChange={e => patch({ create_lead: e.target.checked })} />
              <span>Create a Lead on submission (auto-assigned)</span>
            </label>
          </div>
          {form.create_lead && (
            <div><label>Lead department</label>
              <select value={form.lead_department} onChange={e => patch({ lead_department: e.target.value })}>
                {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select></div>
          )}
          <div>
            <label className="switch" style={{ marginTop: 20 }}>
              <input type="checkbox" checked={form.create_task}
                onChange={e => patch({ create_task: e.target.checked })} />
              <span>Create a follow-up Task on submission</span>
            </label>
          </div>
          {form.create_task && (
            <div><label>Task title</label>
              <input defaultValue={form.task_title} placeholder={`Follow up: ${form.name}`}
                onBlur={e => e.target.value !== form.task_title && patch({ task_title: e.target.value })} /></div>
          )}
        </div>
        {form.create_lead && (
          <p className="muted small" style={{ marginTop: 8 }}>
            Map fields to lead attributes below ("Maps to") so submissions fill the lead's name, phone, requirement…
          </p>
        )}
      </div>

      <FieldEditor form={form} onChanged={load} />
    </div>
  )
}

function FieldEditor({ form, onChanged }) {
  const [f, setF] = useState({ label: '', type: 'short_text', required: false, options: '', lead_attr: '' })
  const [err, setErr] = useState('')
  const set = k => e => setF(p => ({ ...p, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  const add = async () => {
    setErr('')
    const body = {
      label: f.label, type: f.type, required: f.required, lead_attr: f.lead_attr,
      options: NEEDS_OPTIONS.includes(f.type) ? f.options.split(',').map(s => s.trim()).filter(Boolean) : [],
    }
    try {
      await api(`/api/forms/${form.id}/add_field/`, { method: 'POST', body })
      setF({ label: '', type: 'short_text', required: false, options: '', lead_attr: '' })
      onChanged()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const patchField = async (field, body) => {
    setErr('')
    try { await api(`/api/form-fields/${field.id}/`, { method: 'PATCH', body }); onChanged() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const removeField = async (field) => {
    setErr('')
    try { await api(`/api/form-fields/${field.id}/`, { method: 'DELETE' }); onChanged() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }
  const move = async (idx, dir) => {
    const ids = form.fields.map(x => x.id)
    const j = idx + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[idx], ids[j]] = [ids[j], ids[idx]]
    setErr('')
    try { await api(`/api/forms/${form.id}/reorder_fields/`, { method: 'POST', body: { order: ids } }); onChanged() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <div className="dash-card">
      <h3>Fields ({form.fields.length})</h3>
      {err && <div className="err">{err}</div>}
      {form.fields.length === 0 && <p className="muted small">No fields yet — add the first one below. Publishing needs at least one field.</p>}
      {form.fields.map((field, idx) => (
        <div className="task-row" key={field.id} style={{ marginBottom: 8 }}>
          <div className="task-main">
            <div className="task-title">
              {field.label}
              <span className="ai-chip">{FIELD_TYPES.find(([v]) => v === field.type)?.[1]}</span>
              {field.required && <span className="prio prio-high">required</span>}
              {field.lead_attr && <span className="ai-chip">→ {LEAD_ATTRS.find(([v]) => v === field.lead_attr)?.[1]}</span>}
            </div>
            {field.options.length > 0 && <div className="small muted">{field.options.join(' · ')}</div>}
          </div>
          <span style={{ display: 'flex', gap: 4 }}>
            <select value={field.lead_attr} title="Maps to lead attribute"
              onChange={e => patchField(field, { lead_attr: e.target.value })}>
              {LEAD_ATTRS.map(([v, l]) => <option key={v} value={v}>{v ? `→ ${l}` : 'Maps to…'}</option>)}
            </select>
            <button className="btn btn-sm" title="Toggle required"
              onClick={() => patchField(field, { required: !field.required })}>
              {field.required ? 'Optional' : 'Require'}
            </button>
            <button className="btn btn-sm" onClick={() => move(idx, -1)}>▲</button>
            <button className="btn btn-sm" onClick={() => move(idx, 1)}>▼</button>
            <button className="btn btn-sm" onClick={() => removeField(field)}>✕</button>
          </span>
        </div>
      ))}
      <div className="form-grid" style={{ marginTop: 12 }}>
        <div><label>Field label *</label><input value={f.label} onChange={set('label')} /></div>
        <div><label>Type</label>
          <select value={f.type} onChange={set('type')}>
            {FIELD_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></div>
        {NEEDS_OPTIONS.includes(f.type) && (
          <div className="wide"><label>Options (comma-separated) *</label>
            <input value={f.options} onChange={set('options')} placeholder="Option A, Option B, Option C" /></div>
        )}
        <div>
          <label className="switch" style={{ marginTop: 20 }}>
            <input type="checkbox" checked={f.required} onChange={set('required')} /><span>Required</span>
          </label>
        </div>
        <div><label>Maps to (lead)</label>
          <select value={f.lead_attr} onChange={set('lead_attr')}>
            {LEAD_ATTRS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></div>
      </div>
      <div style={{ marginTop: 10 }}>
        <button className="btn btn-primary" disabled={!f.label.trim()} onClick={add}>+ Add field</button>
      </div>
    </div>
  )
}

/* ---------------- Submissions ---------------- */

function Submissions({ form, onBack }) {
  const [rows, setRows] = useState(null)
  const [detail, setDetail] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api(`/api/forms/${form.id}/submissions/`).then(setRows).catch(e => setErr(e.message))
  }, [form.id])

  const exportCsv = async () => {
    setErr('')
    try {
      const res = await fetch(`/api/forms/${form.id}/export/`,
        { headers: { Authorization: `Bearer ${tokens.access}` } })
      if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`)
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${form.name}-submissions.csv`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) { setErr(e.message) }
  }

  const fieldLabel = (id) => form.fields?.find(f => String(f.id) === String(id))?.label || `#${id}`

  if (err && !rows) return <div className="err">{err}</div>
  if (!rows) return <div className="center-note">Loading submissions…</div>
  return (
    <div style={{ maxWidth: 860 }}>
      <div className="page-head">
        <h1><button className="btn btn-sm" onClick={onBack}>←</button> {form.name} — Submissions</h1>
        {rows.length > 0 && <button className="btn btn-primary" onClick={exportCsv}>Export CSV</button>}
      </div>
      {err && <div className="err">{err}</div>}
      {rows.length === 0 && <p className="muted">No submissions yet. Share the form link to start collecting.</p>}
      <table className="table">
        <thead><tr><th>ID</th><th>Date</th><th>Person</th><th>Lead</th><th>Task</th><th /></tr></thead>
        <tbody>
          {rows.map(s => (
            <tr key={s.id}>
              <td>#{s.id}</td>
              <td>{fmtDT(s.created_at)}</td>
              <td><strong>{s.person}</strong></td>
              <td>{s.lead_name || '—'}</td>
              <td>{s.task_title || '—'}</td>
              <td className="row-actions">
                <button className="btn btn-sm" onClick={() => setDetail(detail === s.id ? null : s.id)}>
                  {detail === s.id ? 'Hide' : 'View'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {detail && (() => {
        const s = rows.find(x => x.id === detail)
        return (
          <div className="dash-card" style={{ marginTop: 12 }}>
            <h3>Submission #{s.id}</h3>
            {Object.entries(s.answers).map(([fid, v]) => (
              <div className="doc-row" key={fid}>
                <strong>{fieldLabel(fid)}</strong>
                <span>{Array.isArray(v) ? v.join(', ') : String(v)}</span>
              </div>
            ))}
            {s.files.map(f => (
              <div className="doc-row" key={f.url}>
                <strong>{fieldLabel(f.field_id)}</strong>
                <a href={f.url} target="_blank" rel="noreferrer">📎 {f.filename}</a>
              </div>
            ))}
          </div>
        )
      })()}
    </div>
  )
}
