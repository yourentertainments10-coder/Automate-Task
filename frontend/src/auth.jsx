import { createContext, useContext, useEffect, useState } from 'react'
import { api, login as apiLogin, logout as apiLogout, setUnauthorizedHandler, tokens } from './api'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    if (!tokens.access) { setReady(true); return }
    api('/api/auth/me')
      .then(setUser)
      .catch(() => {})
      .finally(() => setReady(true))
  }, [])

  const value = {
    user,
    ready,
    can: (capability) => !!user?.capabilities?.includes(capability),
    async login(username, password) {
      const me = await apiLogin(username, password)
      setUser(me)
      return me
    },
    async logout() {
      await apiLogout()
      setUser(null)
    },
  }
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}
