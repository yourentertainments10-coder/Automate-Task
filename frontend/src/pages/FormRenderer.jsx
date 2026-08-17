import { useState } from 'react'
import { tokens } from '../api'

/* Renders any form's fields and submits as multipart (JSON answers +
   file_<id> uploads). Used by BOTH the in-app fill page (authed) and the
   public /f/<token> page (anonymous). */
export default function FormRenderer({ form, submitPath, authed = false, onDone }) {
  const [values, setValues] = useState({})
  const [files, setFiles] = useState({})
  const [errors, setErrors] = useState({})
  const [topErr, setTopErr] = useState('')
  const [busy, setBusy] = useState(false)

  const setVal = (id, v) => setValues(p => ({ ...p, [id]: v }))
  const toggleCheck = (id, opt) => setValues(p => {
    const cur = p[id] || []
    return { ...p, [id]: cur.includes(opt) ? cur.filter(x => x !== opt) : [...cur, opt] }
  })

  const submit = async (e) => {
    e.preventDefault()
    setErrors({}); setTopErr(''); setBusy(true)
    const fd = new FormData()
    for (const [id, v] of Object.entries(values)) {
      if (Array.isArray(v)) v.forEach(x => fd.append(id, x))
      else fd.append(id, v)
    }
    for (const [id, f] of Object.entries(files)) {
      if (f) fd.append(`file_${id}`, f)
    }
    try {
      const headers = authed && tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {}
      const res = await fetch(submitPath, { method: 'POST', body: fd, headers })
      const data = await res.json().catch(() => null)
      if (res.status === 400 && data) { setErrors(data); return }
      if (!res.ok) { setTopErr(data?.detail || `Submit failed (HTTP ${res.status})`); return }
      onDone?.(data)
    } catch {
      setTopErr('Network error — please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="dash-card" onSubmit={submit}>
      {form.description && <p className="muted" style={{ marginBottom: 14 }}>{form.description}</p>}
      {(form.fields || []).map(field => (
        <div key={field.id} className="ff-field">
          <label className="ff-label">
            {field.label} {field.required && <span className="late">*</span>}
          </label>
          <FieldInput field={field} value={values[String(field.id)]}
            onChange={v => setVal(String(field.id), v)}
            onFile={f => setFiles(p => ({ ...p, [field.id]: f }))}
            onToggle={opt => toggleCheck(String(field.id), opt)} />
          {errors[String(field.id)] && <div className="err">{errors[String(field.id)]}</div>}
        </div>
      ))}
      {topErr && <div className="err">{topErr}</div>}
      <button className="btn btn-primary" disabled={busy} style={{ marginTop: 8 }}>
        {busy ? 'Submitting…' : 'Submit'}
      </button>
    </form>
  )
}

function FieldInput({ field, value, onChange, onFile, onToggle }) {
  const v = value ?? (field.type === 'checkbox' ? [] : '')
  switch (field.type) {
    case 'long_text':
      return <textarea rows={4} className="ff-input" value={v} onChange={e => onChange(e.target.value)} />
    case 'number':
      return <input type="number" className="ff-input" value={v} onChange={e => onChange(e.target.value)} />
    case 'email':
      return <input type="email" className="ff-input" value={v} onChange={e => onChange(e.target.value)} />
    case 'phone':
      return <input type="tel" className="ff-input" value={v} onChange={e => onChange(e.target.value)} placeholder="+91…" />
    case 'date':
      return <input type="date" className="ff-input" value={v} onChange={e => onChange(e.target.value)} />
    case 'dropdown':
      return (
        <select className="ff-input" value={v} onChange={e => onChange(e.target.value)}>
          <option value="">Select…</option>
          {field.options.map(o => <option key={o}>{o}</option>)}
        </select>
      )
    case 'radio':
      return (
        <div className="ff-options">
          {field.options.map(o => (
            <label key={o}><input type="radio" name={`f${field.id}`} checked={v === o}
              onChange={() => onChange(o)} /> {o}</label>
          ))}
        </div>
      )
    case 'checkbox':
      return (
        <div className="ff-options">
          {field.options.map(o => (
            <label key={o}><input type="checkbox" checked={v.includes(o)}
              onChange={() => onToggle(o)} /> {o}</label>
          ))}
        </div>
      )
    case 'file':
      return <input type="file" onChange={e => onFile(e.target.files[0] || null)} />
    default:
      return <input className="ff-input" value={v} onChange={e => onChange(e.target.value)} />
  }
}
