import { useState } from 'react'
import { api } from './api'

/* Spelling and grammar help for every box a person writes a sentence in.
 *
 * The browser already underlines misspellings, but it only offers the fix on
 * right-click, which nobody finds. This is that fix as a button.
 *
 *   <SpellCheck>     just the button — for composers that are already laid out
 *   <ProofreadText>  label + box + button + undo — the normal prose field
 *
 * Both share one implementation, so the icon, the wording, the undo and the
 * "AI is unreachable" behaviour are identical everywhere, and a new prose
 * field never means re-implementing any of it.
 */

function useProofread(value, onChange) {
  // `before` is only set when a fix was actually applied, so it doubles as
  // "is there something to undo"
  const [before, setBefore] = useState(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const clear = () => { setMsg(''); setBefore(null) }

  async function check() {
    const original = value
    if (!original.trim() || busy) return
    setBusy(true); clear()
    try {
      const r = await api('/api/tasks/proofread/', { method: 'POST', body: { text: original } })
      if (r.changed) {
        onChange(r.text)
        setBefore(original)
        setMsg('Spelling and grammar fixed.')
      } else {
        setMsg(r.provider === 'rules'
          ? 'Spell check is unavailable right now — right-click a red word instead.'
          : 'Looks good, nothing to fix.')
      }
    } catch {
      setMsg('Could not check right now — right-click a red word instead.')
    } finally {
      setBusy(false)
    }
  }

  const undo = () => { onChange(before); clear() }
  return { check, busy, msg, canUndo: before !== null, undo, clear }
}

export function SpellCheck({ value, onChange, disabled = false }) {
  const { check, busy, msg, canUndo, undo } = useProofread(value, onChange)
  return (
    <>
      <button type="button" className="spell-btn" onClick={check}
        disabled={busy || disabled || !value.trim()}
        data-tip="Check spelling" aria-label="Check spelling">
        {busy ? '…' : 'ABC✓'}
      </button>
      {canUndo && (
        <button type="button" className="linkish" onClick={undo} title={msg}>Undo</button>
      )}
    </>
  )
}

export default function ProofreadText({
  label, value, onChange, rows = 3, required = false, placeholder = '',
  disabled = false, autoFocus = false, hint = null,
}) {
  const { check, busy, msg, canUndo, undo, clear } = useProofread(value, onChange)

  function edited(e) {
    onChange(e.target.value)
    clear()                       // their own edit supersedes any suggestion
  }

  return (
    <>
      <div className="label-row">
        {label ? <label>{label}</label> : <span />}
        <button type="button" className="spell-btn" onClick={check}
          disabled={busy || disabled || !value.trim()}
          data-tip="Check spelling" aria-label="Check spelling">
          {busy ? '…' : 'ABC✓'}
        </button>
      </div>
      <textarea className="prose-field" value={value} onChange={edited}
        rows={rows} required={required} placeholder={placeholder}
        disabled={disabled} autoFocus={autoFocus} spellCheck="true" />
      {(msg || hint) && (
        <div className="small muted" style={{ marginTop: 4 }}>
          {msg || hint}
          {canUndo && (
            <button type="button" className="linkish" style={{ marginLeft: 8 }}
              onClick={undo}>Undo</button>
          )}
        </div>
      )}
    </>
  )
}
