import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { createCustomer, hasToken, listCustomers, login, me, setToken, whenUnauthorized, type Customer, type User } from './api'
import CustomerPage from './CustomerPage'
import Playbook from './Playbook'
import Settings from './Settings'
import { ErrorText, Panel, Tip, errMsg, ghost, input, primary } from './ui'

/** Hash routes keep reloads and the back button working without a router library. */
function useRoute() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const on = () => setHash(window.location.hash)
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const parts = hash.replace(/^#\/?/, '').split('/')
  return { page: parts[0] || 'customers', id: parts[1] ? decodeURIComponent(parts[1]) : '' }
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(hasToken())
  const route = useRoute()

  useEffect(() => {
    whenUnauthorized(() => setUser(null))
    if (!hasToken()) return
    me().then(setUser).catch(() => setToken('')).finally(() => setChecking(false))
  }, [])

  if (checking) return <p className="p-8 text-sm text-slate-500">Loading…</p>
  if (!user) return <Login onLogin={setUser} />

  const logout = () => { setToken(''); setUser(null) }
  return (
    <div className="mx-auto max-w-[1500px] px-4 py-5">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <a href="#/customers" className="group">
          <div className="text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Sales Memory Agent</div>
          <div className="text-lg font-bold tracking-tight">Remembers the customer so you don't have to</div>
        </a>
        <nav className="flex items-center gap-2 text-sm">
          <a href="#/customers" className={route.page === 'customers' ? 'font-semibold' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}>Customers</a>
          <span className="text-slate-300">·</span>
          <Tip below text="Lessons the agent learned across all customers, with names removed. Every brief draws on them."><a href="#/playbook" className={route.page === 'playbook' ? 'font-semibold' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}>Company playbook</a></Tip>
          <span className="text-slate-300">·</span>
          <Tip below text="The organisation's main prompt for every brief. Admins can edit it."><a href="#/settings" className={route.page === 'settings' ? 'font-semibold' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}>Settings</a></Tip>
          <span className="ml-3 rounded-full bg-slate-100 px-3 py-1 text-xs dark:bg-slate-800">{user.name} · {user.role === 'admin' ? 'admin' : 'sales exec'}</span>
          <Tip below text="Sign out on this device."><button className={ghost} onClick={logout}>Log out</button></Tip>
        </nav>
      </header>
      {route.page === 'customer' && route.id ? <CustomerPage id={route.id} />
        : route.page === 'playbook' ? <Playbook />
          : route.page === 'settings' ? <Settings user={user} />
          : <Customers />}
    </div>
  )
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try { const r = await login(email, password); setToken(r.token); onLogin(r.user) }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm px-4">
      <div className="mb-6 text-center">
        <div className="text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Sales Memory Agent</div>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Sign in</h1>
      </div>
      <Panel title="Sales executive login">
        <form className="space-y-3" onSubmit={submit}>
          <input className={input} type="email" required autoComplete="username" placeholder="you@company.com" value={email} onChange={e => setEmail(e.target.value)} />
          <input className={input} type="password" required autoComplete="current-password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} />
          <button className={`${primary} w-full`} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          <ErrorText error={error} />
        </form>
      </Panel>
    </div>
  )
}

function Customers() {
  const [items, setItems] = useState<Customer[] | null>(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ id: '', name: '', industry: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => listCustomers().then(setItems).catch(e => setError(errMsg(e))), [])
  useEffect(() => { load() }, [load])

  async function create(e: FormEvent) {
    e.preventDefault()
    const id = form.id.trim().toLowerCase()
    if (!confirm(`Create customer "${form.name}" (${id})? A new memory bank will be created for them.`)) return
    setBusy(true); setError('')
    try { await createCustomer(id, form.name.trim(), form.industry.trim()); window.location.hash = `#/customer/${id}` }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Panel title="Your customers">
        <ErrorText error={error} />
        {!items ? <p className="text-sm text-slate-400">Loading…</p> : !items.length ? (
          <p className="rounded-xl border-2 border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-800">
            No customers assigned to you yet. Create one on the right.
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {items.map(c => (
              <li key={c.id}>
                <a href={`#/customer/${encodeURIComponent(c.id)}`}
                  className="block rounded-xl border border-slate-200 p-4 transition hover:border-indigo-400 hover:shadow-sm dark:border-slate-800">
                  <div className="font-semibold">{c.name}</div>
                  <div className="mt-1 text-xs text-slate-500">{c.industry} · <span className="font-mono">{c.bank_id}</span>
                    {c.status !== 'active' && <span className="ml-1 text-amber-600">({c.status})</span>}</div>
                </a>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="New customer">
        <form className="space-y-2" onSubmit={create}>
          <input className={input} required placeholder="Company name, e.g. Globex Systems" value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value, id: f.id || '' }))} />
          <input className={input} required pattern="[a-z0-9][a-z0-9-]*" minLength={2} maxLength={40} placeholder="Customer id, e.g. globex"
            value={form.id} onChange={e => setForm(f => ({ ...f, id: e.target.value.toLowerCase() }))} />
          <input className={input} required placeholder="Industry, e.g. logistics" value={form.industry} onChange={e => setForm(f => ({ ...f, industry: e.target.value }))} />
          <Tip className="w-full" text="Adds the customer, assigns them to you and creates their own Hindsight memory bank. You'll be asked to confirm." wide><button className={`${primary} w-full`} disabled={busy}>{busy ? 'Creating memory bank…' : 'Create customer'}</button></Tip>
          <p className="text-xs text-slate-400">Each customer gets their own Hindsight memory bank. The first brief uses the company playbook.</p>
        </form>
      </Panel>
    </div>
  )
}
