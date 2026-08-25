import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

// Install the app shell so CarTrends can be added to a phone's home screen and
// opens instantly. Only in a production build -- a service worker in dev
// fights Vite's hot reload.
//
// Update flow: every deploy stamps a new version into sw.js. When the browser
// finds it, we DON'T silently swap — we raise `sw-update-available` and the
// App shows an "Update" button. Tapping it tells the waiting worker to take
// over, then reloads once, and the user is on the latest version.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', async () => {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js')

      const announce = (worker) => {
        if (worker && navigator.serviceWorker.controller) {
          // stash it too: the toast lives inside the logged-in shell, which
          // may mount AFTER this event fires (e.g. user is on the login page)
          window.__swWaiting = worker
          window.dispatchEvent(new CustomEvent('sw-update-available', { detail: worker }))
        }
      }
      // a version was already waiting when the app opened
      announce(reg.waiting)
      // a version arrives while the app is open
      reg.addEventListener('updatefound', () => {
        const fresh = reg.installing
        fresh?.addEventListener('statechange', () => {
          if (fresh.state === 'installed') announce(reg.waiting || fresh)
        })
      })
      // long-open apps: look for a new deploy every 30 minutes
      setInterval(() => reg.update().catch(() => {}), 30 * 60 * 1000)

      // once the new worker takes control, load the new code exactly once
      let reloaded = false
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (reloaded) return
        reloaded = true
        window.location.reload()
      })
    } catch { /* offline first paint etc. — never block the app */ }
  })
}
