import { useCallback, useEffect, useState } from 'react'
import {
  BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate,
} from 'react-router-dom'
import { api } from './api'
import { AuthProvider, useAuth } from './auth'
import Login from './pages/Login'
import Users from './pages/Users'
import Home from './pages/Home'
import Leads from './pages/Leads'
import Notifications from './pages/Notifications'
import Settings from './pages/Settings'
import Intake from './pages/Intake'
import Tasks from './pages/Tasks'
import Groups from './pages/Groups'
import Notices from './pages/Notices'
import Links from './pages/Links'
import Ideas from './pages/Ideas'
import Forms from './pages/Forms'
import PublicForm from './pages/PublicForm'
import HR from './pages/HR'
import Mistakes from './pages/Mistakes'

/* Page titles for the mobile top bar */
const TITLES = {
  '/': 'Dashboard', '/leads': 'Leads', '/tasks': 'Tasks', '/groups': 'Groups',
  '/notices': 'Notices', '/links': 'Links', '/ideas': 'Idea Board',
  '/forms': 'Forms', '/hr': 'Attendance', '/mistakes': 'Mistake Register',
  '/notifications': 'Notifications',
  '/intake': 'AI Inbox', '/users': 'My Team', '/settings': 'Automation',
}

function Shell({ children }) {
  const { user, can, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [unread, setUnread] = useState(0)
  const [navOpen, setNavOpen] = useState(false)
  const [pwOpen, setPwOpen] = useState(false)

  const refreshUnread = useCallback(() => {
    api('/api/notifications/unread_count/').then(d => setUnread(d.count)).catch(() => {})
  }, [])
  useEffect(() => {
    refreshUnread()
    const t = setInterval(refreshUnread, 30000)
    return () => clearInterval(t)
  }, [refreshUnread])

  // Close the drawer whenever the route changes (tapping a link on a phone)
  useEffect(() => { setNavOpen(false) }, [location.pathname])

  const kids = typeof children === 'function' ? children({ refreshUnread }) : children

  return (
    <div className={'shell' + (navOpen ? ' nav-open' : '')}>
      <header className="mobile-bar">
        <button className="icon-btn" onClick={() => setNavOpen(v => !v)} aria-label="Menu">
          <span className="burger" />
        </button>
        <span className="mobile-title">{TITLES[location.pathname] || 'CarTrends'}</span>
        <button className="icon-btn" onClick={() => navigate('/notifications')} aria-label="Notifications">
          🔔{unread > 0 && <span className="badge-dot">{unread > 9 ? '9+' : unread}</span>}
        </button>
      </header>

      <div className="nav-scrim" onClick={() => setNavOpen(false)} />

      <aside className="sidebar">
        <div className="brand">
          <img src="/logo.png" alt="CarTrends"
            style={{ height: 30, width: 'auto', background: '#fff', borderRadius: 6, padding: '3px 5px' }} />
          <div>Automation Task<small>CarTrends</small></div>
        </div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          {user.capabilities.some(c => c.startsWith('leads.view')) && <NavLink to="/leads">Leads</NavLink>}
          <NavLink to="/tasks">Tasks</NavLink>
          <NavLink to="/groups">Groups</NavLink>
          <NavLink to="/notices">Notices</NavLink>
          <NavLink to="/links">Links</NavLink>
          <NavLink to="/ideas">Idea Board</NavLink>
          <NavLink to="/forms">Forms</NavLink>
          <NavLink to="/hr">Attendance</NavLink>
          <NavLink to="/mistakes">Mistakes</NavLink>
          <NavLink to="/notifications">
            Notifications {unread > 0 && <span className="badge">{unread}</span>}
          </NavLink>
          {can('intake.view') && <NavLink to="/intake">AI Inbox</NavLink>}
          <NavLink to="/users">My Team</NavLink>
          {can('settings.manage') && <NavLink to="/settings">Automation</NavLink>}
        </nav>
        <div className="side-foot">
          <div className="who">
            <div className="who-name">{user.first_name || user.username}</div>
            <div className="who-role">{user.role_display}</div>
          </div>
          <button className="btn btn-ghost" onClick={() => setPwOpen(true)}>Change password</button>
          <button
            className="btn btn-ghost"
            onClick={async () => { await logout(); navigate('/login') }}
          >
            Sign out
          </button>
        </div>
      </aside>

      <main className="content">{kids}</main>
      {pwOpen && <ChangePasswordModal onClose={() => setPwOpen(false)} />}
      <UpdateToast />
    </div>
  )
}

/* New deploy detected -> one-tap update. The waiting service worker is told
   to take over; controllerchange (main.jsx) reloads onto the new version. */
function UpdateToast() {
  const [waiting, setWaiting] = useState(() => window.__swWaiting || null)
  useEffect(() => {
    const onUpdate = (e) => setWaiting(e.detail)
    window.addEventListener('sw-update-available', onUpdate)
    return () => window.removeEventListener('sw-update-available', onUpdate)
  }, [])
  if (!waiting) return null
  return (
    <div style={{
      position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      zIndex: 90, display: 'flex', gap: 10, alignItems: 'center',
      background: '#14201c', color: '#fff', padding: '10px 14px',
      borderRadius: 12, boxShadow: '0 8px 30px rgba(20,32,28,.35)', maxWidth: '92vw',
    }}>
      <span style={{ fontSize: 13 }}>🔄 App ka naya version aa gaya hai</span>
      <button className="btn btn-sm btn-primary"
        onClick={() => waiting.postMessage({ type: 'SKIP_WAITING' })}>
        Update
      </button>
      <button className="btn btn-sm" style={{ color: '#fff', background: 'transparent', border: '1px solid #3a4a44' }}
        onClick={() => setWaiting(null)} title="Agli baar app kholne pe khud update ho jayega">
        Later
      </button>
    </div>
  )
}

/* Self-service password change — the only way anyone (admin included)
   ever "sees" a password is by setting a new one; stored hashes are unreadable. */
function ChangePasswordModal({ onClose }) {
  const [f, setF] = useState({ current: '', next: '', again: '' })
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setMsg('')
    if (f.next !== f.again) { setErr('New passwords do not match.'); return }
    if (f.next.length < 8) { setErr('Use at least 8 characters.'); return }
    setBusy(true)
    try {
      await api('/api/auth/change-password', {
        method: 'POST', body: { current_password: f.current, new_password: f.next },
      })
      setMsg('Password changed. Use the new one from your next login.')
      setF({ current: '', next: '', again: '' })
    } catch (ex) {
      const d = ex.data || {}
      setErr(d.detail || Object.values(d).flat().join(' ') || ex.message)
    } finally { setBusy(false) }
  }

  return (
    <div className="modal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={submit} style={{ width: 400 }}>
        <h2>Change password</h2>
        <div className="form-grid">
          <div className="wide"><label>Current password</label>
            <input type="password" value={f.current} onChange={set('current')} autoFocus required /></div>
          <div className="wide"><label>New password (8+ characters)</label>
            <input type="password" value={f.next} onChange={set('next')} required /></div>
          <div className="wide"><label>New password again</label>
            <input type="password" value={f.again} onChange={set('again')} required /></div>
        </div>
        {err && <div className="err">{err}</div>}
        {msg && <div className="ok" style={{ marginTop: 8 }}>{msg}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Close</button>
          <button className="btn btn-primary" disabled={busy || !f.current || !f.next}>
            {busy ? 'Saving…' : 'Change password'}
          </button>
        </div>
      </form>
    </div>
  )
}

/* Public page — Meta requires a Privacy Policy URL to take the app Live. */
function Privacy() {
  return (
    <div style={{ maxWidth: 680, margin: '40px auto', padding: '0 20px', lineHeight: 1.6 }}>
      <h1>Privacy Policy — Automation Task</h1>
      <p><em>CarTrends internal operations system · effective August 2026</em></p>
      <p>
        Automation Task is an internal tool used only by CarTrends employees
        for work management: tasks, attendance, leave, payroll and internal
        communication.
      </p>
      <h3>What we store</h3>
      <p>
        Employee work profile (name, work email, phone number, role,
        department), work records (tasks, status updates, attendance
        check-ins including optional location and face-match data where
        enabled, leave and payroll records) and notification logs.
      </p>
      <h3>How it is used</h3>
      <p>
        Only to run CarTrends&rsquo; internal operations — assigning work,
        attendance, payroll and sending work notifications in-app, by email
        and on WhatsApp. Data is never sold or shared with third parties,
        except the delivery providers used to send notifications
        (Google Gmail API, Meta WhatsApp Business API).
      </p>
      <h3>Access &amp; contact</h3>
      <p>
        Access is restricted by role. Employees can view their own records in
        the app. For questions or corrections, contact
        {' '}<a href="mailto:developer.team@cartrends.in">developer.team@cartrends.in</a>.
      </p>
    </div>
  )
}

function Protected({ children, capability }) {
  const { user, ready, can } = useAuth()
  if (!ready) return <div className="center-note">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  if (capability && !can(capability)) return <Navigate to="/" replace />
  return <Shell>{children}</Shell>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/f/:token" element={<PublicForm />} />
          <Route path="/" element={<Protected><Home /></Protected>} />
          <Route path="/leads" element={<Protected><Leads /></Protected>} />
          <Route path="/tasks" element={<Protected><Tasks /></Protected>} />
          <Route path="/groups" element={<Protected><Groups /></Protected>} />
          <Route path="/notices" element={<Protected><Notices /></Protected>} />
          <Route path="/links" element={<Protected><Links /></Protected>} />
          <Route path="/ideas" element={<Protected><Ideas /></Protected>} />
          <Route path="/forms" element={<Protected><Forms /></Protected>} />
          <Route path="/hr" element={<Protected><HR /></Protected>} />
          <Route path="/mistakes" element={<Protected><Mistakes /></Protected>} />
          <Route path="/notifications" element={
            <Protected>{({ refreshUnread }) => <Notifications onCountChange={refreshUnread} />}</Protected>
          } />
          <Route path="/intake" element={<Protected capability="intake.view"><Intake /></Protected>} />
          <Route path="/users" element={<Protected><Users /></Protected>} />
          <Route path="/settings" element={<Protected capability="settings.manage"><Settings /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
