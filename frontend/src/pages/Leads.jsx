import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, apiUpload, errorText } from '../api'
import { useAuth } from '../auth'

export const STAGES = [
  ['new', 'New'],
  ['contacted', 'Contacted'],
  ['quotation_sent', 'Quotation Sent'],
  ['negotiation', 'Negotiation'],
  ['won', 'Won'],
  ['lost', 'Lost'],
]
const SOURCES = [
  ['manual', 'Manual'], ['whatsapp', 'WhatsApp'], ['gmail', 'Gmail'],
  ['web', 'Website'], ['indiamart', 'IndiaMART'], ['tradeindia', 'TradeIndia'], ['other', 'Other'],
]
const PRIORITIES = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High'], ['urgent', 'Urgent']]
const DEPARTMENTS = [
  ['sales', 'Sales'], ['purchase', 'Purchase'], ['accounts', 'Accounts'],
  ['support', 'IT Team'], ['warehouse', 'Warehouse'], ['management', 'Management'],
]

export const fmtINR = (n) => {
  if (n === null || n === undefined || n === '') return null
  const v = Number(n)
  if (v >= 10000000) return '₹' + (v / 10000000).toFixed(2) + ' Cr'
  if (v >= 100000) return '₹' + (v / 100000).toFixed(1) + ' L'
  return '₹' + v.toLocaleString('en-IN')
}
const fmtDT = (iso) => iso
  ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  : '—'
const toLocalInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const initials = (name) => (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()

export default function Leads() {
  const { user, can } = useAuth()
  const [leads, setLeads] = useState([])
  const [assignees, setAssignees] = useState([])
  const [summary, setSummary] = useState(null)
  const [err, setErr] = useState('')
  const [query, setQuery] = useState('')
  const [fPriority, setFPriority] = useState('')
  const [fSource, setFSource] = useState('')
  const [fAssignee, setFAssignee] = useState('')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [dropStage, setDropStage] = useState(null)

  const canAssign = can('leads.assign')

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page_size: '300' })
      if (query.trim()) params.set('search', query.trim())
      if (fPriority) params.set('priority', fPriority)
      if (fSource) params.set('source', fSource)
      if (fAssignee) params.set('assigned_to', fAssignee)
      if (onlyOverdue) params.set('overdue', 'true')
      const [list, sum] = await Promise.all([
        api(`/api/leads/?${params}`),
        api('/api/leads/summary/'),
      ])
      setLeads(list.results || list)
      setSummary(sum)
      setErr('')
    } catch (e) { setErr(e.message) }
  }, [query, fPriority, fSource, fAssignee, onlyOverdue])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    api('/api/leads/assignees/').then(setAssignees).catch(() => setAssignees([]))
  }, [])

  const moveLead = async (id, stage) => {
    const lead = leads.find(l => l.id === Number(id))
    if (!lead || lead.status === stage) return
    if (!lead.can_edit) { setErr('You cannot edit this lead.'); return }
    try {
      await api(`/api/leads/${id}/`, { method: 'PATCH', body: { status: stage } })
      load()
    } catch (e) { setErr(e.message) }
  }

  const openLead = leads.find(l => l.id === openId)

  const pipelineValue = useMemo(() =>
    leads.filter(l => !['won', 'lost'].includes(l.status))
      .reduce((s, l) => s + Number(l.estimated_value || 0), 0), [leads])

  return (
    <div className="leads-page">
      <div className="page-head">
        <h1>Leads</h1>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add Lead</button>
      </div>

      {summary && (
        <div className="stats">
          <div className="stat"><div className="label">Total</div><div className="value">{summary.total}</div></div>
          <div className="stat"><div className="label">Open pipeline</div><div className="value">{fmtINR(pipelineValue) || '₹0'}</div></div>
          <div className="stat"><div className="label">Won</div><div className="value">{summary.by_status.won}</div></div>
          <div className={'stat' + (summary.overdue ? ' alert' : '')}>
            <div className="label">Overdue follow-ups</div><div className="value">{summary.overdue}</div>
          </div>
        </div>
      )}

      <div className="filters">
        <input type="search" placeholder="Search name, company, phone…"
          value={query} onChange={e => setQuery(e.target.value)} />
        <select value={fPriority} onChange={e => setFPriority(e.target.value)}>
          <option value="">All priorities</option>
          {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={fSource} onChange={e => setFSource(e.target.value)}>
          <option value="">All sources</option>
          {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {canAssign && (
          <select value={fAssignee} onChange={e => setFAssignee(e.target.value)}>
            <option value="">All assignees</option>
            {assignees.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
        <button className={'chip' + (onlyOverdue ? ' on' : '')} onClick={() => setOnlyOverdue(v => !v)}>
          ⏰ Overdue only
        </button>
      </div>

      {err && <div className="err">{err}</div>}

      <div className="board">
        {STAGES.map(([stage, label]) => {
          const cards = leads.filter(l => l.status === stage)
          return (
            <div key={stage}
              className={'col' + (dropStage === stage ? ' drop' : '')}
              onDragOver={e => { e.preventDefault(); setDropStage(stage) }}
              onDragLeave={() => setDropStage(s => (s === stage ? null : s))}
              onDrop={e => { e.preventDefault(); setDropStage(null); moveLead(e.dataTransfer.getData('text/lead-id'), stage) }}
            >
              <div className="col-head">
                <h2>{label}</h2>
                <span className="count">{cards.length}</span>
              </div>
              <div className="col-body">
                {cards.length === 0 && <div className="empty">No leads</div>}
                {cards.map(lead => (
                  <div key={lead.id}
                    className={'card' + (lead.is_overdue ? ' overdue' : '') + (lead.priority === 'urgent' ? ' urgent' : '')}
                    draggable={lead.can_edit}
                    onDragStart={e => e.dataTransfer.setData('text/lead-id', String(lead.id))}
                    onClick={() => setOpenId(lead.id)}
                  >
                    <div className="name">{lead.customer_name}</div>
                    <div className="company">{lead.company || '—'} · {lead.source_display}</div>
                    {lead.requirement && <div className="interest">{lead.requirement.slice(0, 80)}</div>}
                    <div className="meta">
                      <span className="owner-dot" title={lead.assigned_to_detail?.name || 'Unassigned'}>
                        {initials(lead.assigned_to_detail?.name)}
                      </span>
                      {lead.priority !== 'normal' && <span className={`prio prio-${lead.priority}`}>{lead.priority_display}</span>}
                      {fmtINR(lead.estimated_value) && <span className="value">{fmtINR(lead.estimated_value)}</span>}
                      {lead.follow_up_at && !['won', 'lost'].includes(lead.status) && (
                        <span className={'follow' + (lead.is_overdue ? ' late' : '')}>↻ {fmtDT(lead.follow_up_at)}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {showAdd && (
        <LeadModal
          canAssign={canAssign} assignees={assignees} user={user}
          onClose={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load() }}
        />
      )}
      {openLead && (
        <LeadDrawer
          lead={openLead} canAssign={canAssign} assignees={assignees}
          onClose={() => setOpenId(null)} onChanged={load}
        />
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
function LeadModal({ canAssign, assignees, user, onClose, onSaved }) {
  const [f, setF] = useState({
    customer_name: '', phone: '', email: '', company: '', requirement: '',
    source: 'manual', department: user.department === 'management' ? 'sales' : user.department,
    priority: 'normal', assigned_to: '', follow_up_at: '', estimated_value: '',
  })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(prev => ({ ...prev, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    const body = { ...f }
    body.assigned_to = f.assigned_to ? Number(f.assigned_to) : null
    body.follow_up_at = f.follow_up_at ? new Date(f.follow_up_at).toISOString() : null
    body.estimated_value = f.estimated_value || null
    try { await api('/api/leads/', { method: 'POST', body }); onSaved() }
    catch (ex) { setErr(errorText(ex.data) || ex.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>Add Lead</h2>
        <div className="form-grid">
          <div className="wide">
            <label>Customer name *</label>
            <input value={f.customer_name} onChange={set('customer_name')} autoFocus />
          </div>
          <div><label>Phone</label><input value={f.phone} onChange={set('phone')} /></div>
          <div><label>Email</label><input type="email" value={f.email} onChange={set('email')} /></div>
          <div className="wide"><label>Company</label><input value={f.company} onChange={set('company')} /></div>
          <div className="wide">
            <label>Requirement</label>
            <input value={f.requirement} onChange={set('requirement')} placeholder="e.g. Brake pads + oil filter for Tata 407" />
          </div>
          <div>
            <label>Source</label>
            <select value={f.source} onChange={set('source')}>
              {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Department</label>
            <select value={f.department} onChange={set('department')}>
              {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label>Priority</label>
            <select value={f.priority} onChange={set('priority')}>
              {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          {canAssign && (
            <div>
              <label>Assign to</label>
              <select value={f.assigned_to} onChange={set('assigned_to')}>
                <option value="">Unassigned</option>
                {assignees.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          )}
          <div><label>Est. value (₹)</label><input type="number" min="0" value={f.estimated_value} onChange={set('estimated_value')} /></div>
          <div><label>Follow-up</label><input type="datetime-local" value={f.follow_up_at} onChange={set('follow_up_at')} /></div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !f.customer_name.trim()}>
            {busy ? 'Saving…' : 'Create lead'}
          </button>
        </div>
      </form>
    </div>
  )
}

/* ------------------------------------------------------------------ */
function LeadDrawer({ lead, canAssign, assignees, onClose, onChanged }) {
  const [tab, setTab] = useState('timeline')
  const [events, setEvents] = useState([])
  const [docs, setDocs] = useState([])
  const [quotes, setQuotes] = useState([])
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const ro = !lead.can_edit

  const refresh = useCallback(() => {
    api(`/api/leads/${lead.id}/events/`).then(setEvents).catch(() => {})
    api(`/api/leads/${lead.id}/documents/`).then(setDocs).catch(() => {})
    api(`/api/leads/${lead.id}/quotations/`).then(setQuotes).catch(() => {})
  }, [lead.id])
  useEffect(() => { refresh() }, [refresh])

  const patch = async (body) => {
    setErr('')
    try { await api(`/api/leads/${lead.id}/`, { method: 'PATCH', body }); onChanged(); refresh() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const addNote = async () => {
    if (!note.trim()) return
    setErr('')
    try {
      await api(`/api/leads/${lead.id}/notes/`, { method: 'POST', body: { body: note.trim() } })
      setNote(''); refresh()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const upload = async (file) => {
    if (!file) return
    setErr('')
    const fd = new FormData()
    fd.append('file', file)
    try { await apiUpload(`/api/leads/${lead.id}/documents/`, fd); refresh() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const addQuote = async (amount, notes) => {
    setErr('')
    try {
      await api(`/api/leads/${lead.id}/quotations/`, { method: 'POST', body: { amount, notes } })
      refresh()
    } catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const setQuoteStatus = async (q, statusValue) => {
    setErr('')
    try { await api(`/api/quotations/${q.id}/`, { method: 'PATCH', body: { status: statusValue } }); refresh() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-head">
          <div className="row">
            <div>
              <h2>{lead.customer_name}</h2>
              <div className="company">{lead.company || '—'} · {lead.source_display} · {lead.department_display}</div>
            </div>
            <button className="close" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>

        <div className="drawer-body">
          <div className="field-grid">
            <div className="field"><div className="k">Phone</div><div className="v">{lead.phone || '—'}</div></div>
            <div className="field"><div className="k">Email</div><div className="v">{lead.email || '—'}</div></div>
            <div className="field wide"><div className="k">Requirement</div><div className="v">{lead.requirement || '—'}</div></div>
            <div className="field">
              <div className="k">Status</div>
              <select value={lead.status} disabled={ro} onChange={e => patch({ status: e.target.value })}>
                {STAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div className="field">
              <div className="k">Priority</div>
              <select value={lead.priority} disabled={ro} onChange={e => patch({ priority: e.target.value })}>
                {PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div className="field">
              <div className="k">Assigned to</div>
              {canAssign && !ro ? (
                <select value={lead.assigned_to || ''} onChange={e => patch({ assigned_to: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">Unassigned</option>
                  {assignees.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              ) : <div className="v">{lead.assigned_to_detail?.name || 'Unassigned'}</div>}
            </div>
            <div className="field">
              <div className="k">Follow-up</div>
              <input type="datetime-local" disabled={ro} value={toLocalInput(lead.follow_up_at)}
                onChange={e => patch({ follow_up_at: e.target.value ? new Date(e.target.value).toISOString() : null })} />
            </div>
            <div className="field">
              <div className="k">Est. value</div>
              <div className="v">{fmtINR(lead.estimated_value) || '—'}</div>
            </div>
          </div>

          <div className="tabs">
            {['timeline', 'documents', 'quotations'].map(t => (
              <button key={t} className={'tab' + (tab === t ? ' on' : '')} onClick={() => setTab(t)}>
                {t === 'timeline' ? `Timeline (${events.length})` : t === 'documents' ? `Documents (${docs.length})` : `Quotations (${quotes.length})`}
              </button>
            ))}
          </div>

          {err && <div className="err">{err}</div>}

          {tab === 'timeline' && (
            <div className="section">
              {!ro && (
                <div className="note-input">
                  <textarea placeholder="Add a note…" value={note} onChange={e => setNote(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); addNote() } }} />
                  <button className="btn" onClick={addNote}>Save</button>
                </div>
              )}
              <ul className="timeline">
                {events.map(ev => (
                  <li key={ev.id}>
                    <span className={`dot dot-${ev.type}`} />
                    <span>
                      <span className="ev-type">{ev.type_display}</span> {ev.body}
                      <div className="when">{ev.actor?.name || 'System'} · {fmtDT(ev.created_at)}</div>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === 'documents' && (
            <div className="section">
              {!ro && (
                <label className="btn upload-btn">
                  Upload document
                  <input type="file" hidden onChange={e => { upload(e.target.files[0]); e.target.value = '' }} />
                </label>
              )}
              {docs.length === 0 && <div className="empty">No documents</div>}
              {docs.map(d => (
                <div className="doc-row" key={d.id}>
                  <a href={d.url} target="_blank" rel="noreferrer">{d.filename}</a>
                  <span className="when">{d.uploaded_by?.name} · {fmtDT(d.created_at)}</span>
                </div>
              ))}
            </div>
          )}

          {tab === 'quotations' && (
            <div className="section">
              {!ro && <QuoteForm onAdd={addQuote} />}
              {quotes.length === 0 && <div className="empty">No quotations</div>}
              {quotes.map(q => (
                <div className="quote-row" key={q.id}>
                  <div>
                    <strong>{q.number}</strong> · {fmtINR(q.amount)}
                    {q.notes && <div className="small muted">{q.notes}</div>}
                    <div className="when">{q.created_by?.name} · {fmtDT(q.created_at)}</div>
                  </div>
                  {ro ? <span className={`q-pill q-${q.status}`}>{q.status_display}</span> : (
                    <select value={q.status} onChange={e => setQuoteStatus(q, e.target.value)}>
                      <option value="draft">Draft</option>
                      <option value="sent">Sent</option>
                      <option value="accepted">Accepted</option>
                      <option value="rejected">Rejected</option>
                    </select>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </>
  )
}

function QuoteForm({ onAdd }) {
  const [amount, setAmount] = useState('')
  const [notes, setNotes] = useState('')
  return (
    <div className="quote-form">
      <input type="number" min="0" step="0.01" placeholder="Amount (₹)" value={amount} onChange={e => setAmount(e.target.value)} />
      <input placeholder="Notes (optional)" value={notes} onChange={e => setNotes(e.target.value)} />
      <button className="btn" disabled={!amount} onClick={() => { onAdd(amount, notes); setAmount(''); setNotes('') }}>
        Add quotation
      </button>
    </div>
  )
}
