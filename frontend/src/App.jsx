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
          <span className="brand-mark">CT</span>
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
          <button
            className="btn btn-ghost"
            onClick={async () => { await logout(); navigate('/login') }}
          >
            Sign out
          </button>
        </div>
      </aside>

      <main className="content">{kids}</main>
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
