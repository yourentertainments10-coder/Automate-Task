import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login() {
  const { user, ready, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)      // 👁 show/hide password
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  if (ready && user) return <Navigate to="/" replace />

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      await login(username.trim(), password)
      navigate('/')
    } catch (ex) {
      setErr(ex.status === 401 ? 'Invalid username or password, or account deactivated.' : ex.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand big">
          <span className="brand-mark">CT</span>
          <div>CarTrends <small>Internal CRM</small></div>
        </div>
        <label>Username or email</label>
        <input value={username} onChange={e => setUsername(e.target.value)} autoFocus autoComplete="username" />
        <label>Password</label>
        <div style={{ position: 'relative' }}>
          <input type={show ? 'text' : 'password'} value={password}
            onChange={e => setPassword(e.target.value)} autoComplete="current-password"
            style={{ width: '100%', paddingRight: 42 }} />
          <button type="button" tabIndex={-1}
            title={show ? 'Hide password' : 'Show password'}
            aria-label={show ? 'Hide password' : 'Show password'}
            onClick={() => setShow(v => !v)}
            style={{
              position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)',
              border: 'none', background: 'transparent', cursor: 'pointer',
              fontSize: 17, lineHeight: 1, padding: '4px 6px', color: '#66716c',
            }}>
            {show ? '🙈' : '👁'}
          </button>
        </div>
        {err && <div className="err">{err}</div>}
        <button className="btn btn-primary" disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="fine">Internal system — accounts are created by an administrator.</p>
      </form>
    </div>
  )
}
