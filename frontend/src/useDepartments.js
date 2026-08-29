/* One place every department dropdown reads from. Admin manages the list in
   Settings, so adding a department no longer needs a code change. Falls back
   to the original eight if the call fails, so forms never render empty. */
import { useEffect, useState } from 'react'
import { api } from './api'

const FALLBACK = [
  ['sales', 'Sales'], ['purchase', 'Purchase'], ['accounts', 'Accounts'],
  ['support', 'IT Team'], ['development', 'Developer Team'],
  ['warehouse', 'Warehouse'], ['hr', 'Human Resources'], ['management', 'Management'],
]

let cache = null

export function useDepartments() {
  const [rows, setRows] = useState(cache || FALLBACK)
  useEffect(() => {
    if (cache) return
    api('/api/departments/')
      .then(d => {
        cache = d.map(x => [x.code, x.name])
        setRows(cache)
      })
      .catch(() => {})
  }, [])
  return rows
}

export function clearDepartmentCache() { cache = null }
