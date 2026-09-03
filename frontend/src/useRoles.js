/* One place every role dropdown reads from.
 *
 * The list used to be typed out again in Users.jsx and Notices.jsx, and which
 * roles count as "manager" was typed out a third time. Adding Housekeeping,
 * Security, Legal and HR Executive to the backend therefore left them missing
 * from every form -- the backend accepted them, the dropdown never offered
 * them. Reading the list from the API means a new role shows up everywhere the
 * moment it exists, and nowhere has to be kept in step by hand.
 *
 * The fallback is only for a failed call, so a form never renders an empty
 * dropdown; it is not a second copy to maintain.
 */
import { useEffect, useState } from 'react'
import { api } from './api'

const FALLBACK = [
  ['admin', 'Admin'], ['hr_manager', 'HR Manager'], ['sales_manager', 'Sales Manager'],
  ['purchase_manager', 'Purchase Manager'], ['accounts_manager', 'Accounts Manager'],
  ['developer_manager', 'Developer Manager'], ['it_lead', 'IT Lead'],
  ['warehouse_manager', 'Warehouse Manager'], ['sales_executive', 'Sales'],
  ['purchase', 'Purchase Team'], ['accounts', 'Accounts'], ['warehouse', 'Warehouse Team'],
  ['rider', 'Rider'], ['housekeeping', 'Housekeeping'], ['security', 'Security'],
  ['legal', 'Legal'], ['hr_executive', 'HR Executive'], ['developer', 'Developer'],
]
const FALLBACK_MANAGERS = ['admin', 'sales_manager', 'hr_manager', 'it_lead',
  'warehouse_manager', 'purchase_manager', 'accounts_manager', 'developer_manager']

let cache = null

export function useRoles() {
  const [state, setState] = useState(
    cache || { rows: FALLBACK, managerRoles: FALLBACK_MANAGERS })
  useEffect(() => {
    if (cache) return
    api('/api/roles/')
      .then(d => {
        cache = {
          rows: d.map(r => [r.value, r.label]),
          managerRoles: d.filter(r => r.is_manager).map(r => r.value),
        }
        setState(cache)
      })
      .catch(() => {})
  }, [])
  return state
}

export function clearRoleCache() { cache = null }
