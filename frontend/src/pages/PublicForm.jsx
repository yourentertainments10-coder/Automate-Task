import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import FormRenderer from './FormRenderer'

/* The share-link page (/f/<token>) — works without login. */
export default function PublicForm() {
  const { token } = useParams()
  const [form, setForm] = useState(null)
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    fetch(`/api/public/forms/${token}/`)
      .then(async r => {
        const data = await r.json().catch(() => null)
        if (!r.ok) throw new Error(data?.detail || 'Form not found.')
        setForm(data)
      })
      .catch(e => setErr(e.message))
  }, [token])

  return (
    <div className="public-wrap">
      <div className="public-card">
        <div className="brand big">
          <span className="brand-mark">CT</span>
          <div>CarTrends <small>{form ? form.name : 'Forms'}</small></div>
        </div>
        {err && <div className="err">{err}</div>}
        {!err && !form && <div className="center-note">Loading…</div>}
        {form && done && (
          <div className="placeholder-card" style={{ marginTop: 0 }}>
            <h3>✅ Thank you!</h3>
            <p>Your response has been recorded. Our team will get back to you shortly.</p>
          </div>
        )}
        {form && !done && (
          <FormRenderer form={form} submitPath={`/api/public/forms/${token}/submit/`}
            onDone={() => setDone(true)} />
        )}
      </div>
    </div>
  )
}
