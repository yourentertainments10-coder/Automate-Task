import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useAuth } from '../auth'

export default function Links() {
  const { can } = useAuth()
  const canManage = can('tasks.assign')
  const [collections, setCollections] = useState([])
  const [links, setLinks] = useState(null)
  const [groups, setGroups] = useState([])
  const [q, setQ] = useState('')
  const [fCollection, setFCollection] = useState('')
  const [onlyFav, setOnlyFav] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [newColl, setNewColl] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const p = new URLSearchParams()
    if (q.trim()) p.set('search', q.trim())
    if (fCollection) p.set('collection', fCollection)
    if (onlyFav) p.set('favorites', 'true')
    Promise.all([api('/api/link-collections/'), api(`/api/links/?${p}`)])
      .then(([c, l]) => { setCollections(c); setLinks(l) })
      .catch(e => setErr(e.message))
  }, [q, fCollection, onlyFav])
  useEffect(() => { load() }, [load])
  useEffect(() => { api('/api/groups/').then(setGroups).catch(() => {}) }, [])

  const addCollection = async () => {
    if (!newColl.trim()) return
    setErr('')
    try { await api('/api/link-collections/', { method: 'POST', body: { name: newColl.trim() } }); setNewColl(''); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  const toggleFav = async (l) => {
    await api(`/api/links/${l.id}/favorite/`, { method: 'POST' }).catch(() => {})
    load()
  }

  const remove = async (l) => {
    setErr('')
    try { await api(`/api/links/${l.id}/`, { method: 'DELETE' }); load() }
    catch (e) { setErr(errorText(e.data) || e.message) }
  }

  if (err && !links) return <div className="err">{err}</div>
  if (!links) return <div className="center-note">Loading links…</div>

  const grouped = collections
    .map(c => [c, links.filter(l => l.collection === c.id)])
    .filter(([c, ls]) => !fCollection || String(c.id) === fCollection ? true : false)

  return (
    <div>
      <div className="page-head">
        <h1>Links</h1>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add link</button>
      </div>
      <div className="filters">
        <input type="search" placeholder="Search links…" value={q} onChange={e => setQ(e.target.value)} />
        <select value={fCollection} onChange={e => setFCollection(e.target.value)}>
          <option value="">All collections</option>
          {collections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button className={'chip' + (onlyFav ? ' on-accent' : '')} onClick={() => setOnlyFav(v => !v)}>★ Favorites</button>
        {canManage && (
          <span style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
            <input placeholder="New collection…" value={newColl} onChange={e => setNewColl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addCollection() }} />
            <button className="btn" disabled={!newColl.trim()} onClick={addCollection}>Add</button>
          </span>
        )}
      </div>
      {err && <div className="err">{err}</div>}
      {links.length === 0 && <p className="muted">No links yet — add your first company bookmark.</p>}
      {grouped.map(([c, ls]) => ls.length === 0 && (q || onlyFav) ? null : (
        <div key={c.id} style={{ marginBottom: 18, maxWidth: 680 }}>
          <h3 className="tpl-cat">{c.name} ({ls.length})</h3>
          {ls.length === 0 && <p className="muted small">Empty collection.</p>}
          {ls.map(l => (
            <div className="doc-row" key={l.id}>
              <div>
                <button className={'bell' + (l.favorited ? ' on' : '')} style={{ fontSize: 14 }}
                  title={l.favorited ? 'Unfavorite' : 'Favorite'} onClick={() => toggleFav(l)}>★</button>
                <a href={l.url} target="_blank" rel="noreferrer">{l.title}</a>
                {l.group_name && <span className="ai-chip" style={{ marginLeft: 8 }}>{l.group_name}</span>}
                {l.description && <div className="small muted">{l.description}</div>}
              </div>
              <span className="when">
                {l.added_by_detail?.name}
                <button className="btn btn-sm" style={{ marginLeft: 8 }} onClick={() => remove(l)}>✕</button>
              </span>
            </div>
          ))}
        </div>
      ))}
      {showAdd && (
        <LinkModal collections={collections} groups={groups} canManage={canManage}
          onQuickCreate={async (name) => {
            const c = await api('/api/link-collections/', { method: 'POST', body: { name } })
            load()
            return c
          }}
          onClose={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load() }} />
      )}
    </div>
  )
}

function LinkModal({ collections, groups, canManage, onQuickCreate, onClose, onSaved }) {
  const [f, setF] = useState({
    collection: collections[0]?.id || '', title: '', url: '', description: '', group: '',
  })
  const [newColl, setNewColl] = useState('')
  const [err, setErr] = useState('')
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))

  // collections can arrive/refresh while the modal is open — adopt the first
  useEffect(() => {
    if (!f.collection && collections[0]) setF(p => ({ ...p, collection: collections[0].id }))
  }, [collections])  // eslint-disable-line react-hooks/exhaustive-deps

  const quickCreate = async () => {
    if (!newColl.trim()) return
    setErr('')
    try {
      const c = await onQuickCreate(newColl.trim())
      setF(p => ({ ...p, collection: c.id }))
      setNewColl('')
    } catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    if (!f.collection) { setErr('Create a collection first (ask a manager).'); return }
    const body = { ...f, collection: Number(f.collection), group: f.group ? Number(f.group) : null }
    try { await api('/api/links/', { method: 'POST', body }); onSaved() }
    catch (ex) { setErr(errorText(ex.data) || ex.message) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit}>
        <h2>Add link</h2>
        <div className="form-grid">
          <div className="wide"><label>Title *</label><input value={f.title} onChange={set('title')} autoFocus placeholder="e.g. Google Drive" /></div>
          <div className="wide"><label>URL *</label><input value={f.url} onChange={set('url')} placeholder="https://…" /></div>
          <div className="wide"><label>Description</label><input value={f.description} onChange={set('description')} /></div>
          <div>
            <label>Collection * (the folder this link lives in)</label>
            {collections.length > 0 ? (
              <select value={f.collection} onChange={set('collection')}>
                {collections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            ) : canManage ? (
              <div style={{ display: 'flex', gap: 6 }}>
                <input placeholder="e.g. Important Tools" value={newColl} autoFocus
                  onChange={e => setNewColl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); quickCreate() } }} />
                <button type="button" className="btn btn-sm btn-primary"
                  disabled={!newColl.trim()} onClick={quickCreate}>Create</button>
              </div>
            ) : (
              <p className="muted small" style={{ margin: 0 }}>
                No collections yet — ask a manager/admin to create one first.
              </p>
            )}
          </div>
          <div>
            <label>Visible to</label>
            <select value={f.group} onChange={set('group')}>
              <option value="">Everyone</option>
              {groups.map(g => <option key={g.id} value={g.id}>Group: {g.name}</option>)}
            </select>
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={!f.title.trim() || !f.url.trim()}>Add link</button>
        </div>
      </form>
    </div>
  )
}
