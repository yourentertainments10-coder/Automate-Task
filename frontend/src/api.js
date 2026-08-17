// Minimal API client: JWT in localStorage, one automatic refresh-and-retry
// on 401, hard logout when the refresh token itself is dead.

const store = {
  get access() { return localStorage.getItem('ct.access') },
  get refresh() { return localStorage.getItem('ct.refresh') },
  set(tokens) {
    if (tokens.access) localStorage.setItem('ct.access', tokens.access)
    if (tokens.refresh) localStorage.setItem('ct.refresh', tokens.refresh)
  },
  clear() { localStorage.removeItem('ct.access'); localStorage.removeItem('ct.refresh') },
}

export const tokens = store

async function rawRequest(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (auth && store.access) headers.Authorization = `Bearer ${store.access}`
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  return res
}

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

export async function api(path, opts = {}) {
  let res = await rawRequest(path, opts)
  if (res.status === 401 && store.refresh && opts.auth !== false) {
    const rr = await rawRequest('/api/auth/refresh', {
      method: 'POST', body: { refresh: store.refresh }, auth: false,
    })
    if (rr.ok) {
      store.set(await rr.json())
      res = await rawRequest(path, opts)
    } else {
      store.clear()
      onUnauthorized()
      throw new ApiError(401, { detail: 'Session expired. Please sign in again.' })
    }
  }
  if (res.status === 204) return null
  let data = null
  try { data = await res.json() } catch { /* empty body */ }
  if (!res.ok) throw new ApiError(res.status, data)
  return data
}

export class ApiError extends Error {
  constructor(status, data) {
    super(errorText(data) || `HTTP ${status}`)
    this.status = status
    this.data = data
  }
}

export function errorText(data) {
  if (!data) return ''
  if (typeof data === 'string') return data
  if (data.detail) return data.detail
  // DRF field errors: {field: ["msg"]}
  return Object.entries(data)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : v}`)
    .join(' · ')
}

export async function apiUpload(path, formData) {
  const doSend = () => fetch(path, {
    method: 'POST',
    headers: store.access ? { Authorization: `Bearer ${store.access}` } : {},
    body: formData,
  })
  let res = await doSend()
  if (res.status === 401 && store.refresh) {
    const rr = await rawRequest('/api/auth/refresh', { method: 'POST', body: { refresh: store.refresh }, auth: false })
    if (rr.ok) { store.set(await rr.json()); res = await doSend() }
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data
}

export async function login(username, password) {
  const res = await rawRequest('/api/auth/login', {
    method: 'POST', body: { username, password }, auth: false,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  store.set(data)
  return api('/api/auth/me')
}

export async function logout() {
  try { await api('/api/auth/logout', { method: 'POST', body: { refresh: store.refresh } }) } catch { /* best effort */ }
  store.clear()
}
