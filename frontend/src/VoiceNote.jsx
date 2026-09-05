import { useEffect, useRef, useState } from 'react'
import { apiUpload, errorText } from './api'

/* T-00136: speak a task instead of typing it.
 *
 * Records, sends the clip up, and hands back everything the server managed to
 * work out. It does NOT create anything -- the caller fills the form and a
 * person still presses Create. A misheard name or date has to be visible
 * before it becomes somebody's work.
 */

const MAX_SECONDS = 120        // a task, not a meeting

/* Whatever this browser will actually record. Chrome and Android give webm,
   Safari and iOS give mp4 -- Gemini takes both. */
function pickMime() {
  const R = window.MediaRecorder
  if (!R) return null
  for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']) {
    if (R.isTypeSupported?.(m)) return m
  }
  return ''
}

export default function VoiceNote({ onDraft, disabled }) {
  const [state, setState] = useState('idle')   // idle | recording | working
  const [secs, setSecs] = useState(0)
  const [err, setErr] = useState('')
  const rec = useRef(null)
  const chunks = useRef([])
  const timer = useRef(null)

  // never leave the microphone light on
  useEffect(() => () => {
    try { rec.current?.stream?.getTracks().forEach(t => t.stop()) } catch { /* gone */ }
    clearInterval(timer.current)
  }, [])

  const supported = typeof window !== 'undefined'
    && !!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder

  async function start() {
    setErr('')
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setErr('No microphone access. Allow it in the browser, or type the task.')
      return
    }
    const mime = pickMime()
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    chunks.current = []
    r.ondataavailable = e => { if (e.data.size) chunks.current.push(e.data) }
    r.onstop = () => {
      stream.getTracks().forEach(t => t.stop())
      clearInterval(timer.current)
      const blob = new Blob(chunks.current, { type: r.mimeType || 'audio/webm' })
      if (blob.size < 1200) {           // a tap, not a sentence
        setState('idle'); setSecs(0)
        setErr('That was too short — hold on and say the whole task.')
        return
      }
      send(blob)
    }
    rec.current = r
    r.start()
    setState('recording'); setSecs(0)
    timer.current = setInterval(() => setSecs(s => {
      if (s + 1 >= MAX_SECONDS) { try { r.stop() } catch { /* already stopped */ } }
      return s + 1
    }), 1000)
  }

  function stop() {
    setState('working')
    try { rec.current?.stop() } catch { setState('idle') }
  }

  async function send(blob) {
    setState('working')
    try {
      const fd = new FormData()
      const ext = (blob.type.includes('mp4') && 'm4a') || (blob.type.includes('ogg') && 'ogg') || 'webm'
      fd.append('audio', blob, `note.${ext}`)
      const draft = await apiUpload('/api/tasks/voice_draft/', fd)
      onDraft(draft)
    } catch (e) {
      setErr(errorText(e.data) || e.message)
    } finally {
      setState('idle'); setSecs(0)
    }
  }

  if (!supported) return null

  const mmss = `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`

  return (
    <>
      {state === 'recording' ? (
        <button type="button" className="btn btn-sm voice-btn on" onClick={stop}>
          <span className="voice-dot" /> Stop · {mmss}
        </button>
      ) : (
        <button type="button" className="btn btn-sm voice-btn" onClick={start}
          disabled={disabled || state === 'working'}
          title="Say the task out loud — who it is for and when it is due">
          {state === 'working' ? 'Listening…' : '🎤 Speak the task'}
        </button>
      )}
      {err && <div className="err" style={{ marginTop: 6 }}>{err}</div>}
    </>
  )
}
