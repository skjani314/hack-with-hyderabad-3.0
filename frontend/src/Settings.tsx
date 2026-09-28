import { useEffect, useState } from 'react'
import { getSettings, saveSettings, type OrgSettings, type User } from './api'
import { ErrorText, Panel, errMsg, ghost, input, primary } from './ui'

/** The organisation's main prompt: stored in MongoDB, edited here by an admin, used by every brief. */
export default function Settings({ user }: { user: User }) {
  const [s, setS] = useState<OrgSettings | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const admin = user.role === 'admin'

  useEffect(() => { getSettings().then(r => { setS(r); setText(r.main_prompt) }).catch(e => setError(errMsg(e))) }, [])

  async function save(value: string) {
    setBusy(true); setError(''); setMsg('')
    try { const r = await saveSettings(value); setS(r); setText(r.main_prompt); setMsg('Saved. The next brief uses it.') }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }

  if (!s) return error ? <ErrorText error={error} /> : <p className="text-sm text-slate-500">Loading…</p>
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <Panel title="Main prompt for every brief">
        <p className="mb-3 text-sm text-slate-500">
          What every brief must deliver: goals, how to convince the customer, your sales approach and tone. The sales executive's
          chosen call type, focus areas and question are added after it. Placeholders: {s.placeholders.join(', ')}.
        </p>
        <textarea className={`${input} min-h-80 font-mono text-xs`} value={text} readOnly={!admin} maxLength={4000}
          onChange={e => setText(e.target.value)} />
        <div className="mt-1 text-right text-[11px] text-slate-400">{text.length} / 4000</div>
        {admin ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <button className={primary} disabled={busy || text.trim().length < 20 || text === s.main_prompt} onClick={() => save(text)}>{busy ? 'Saving…' : 'Save'}</button>
            <button className={ghost} disabled={busy || s.is_default} onClick={() => { if (confirm('Reset to the default prompt?')) save(s.default_prompt) }}>Reset to default</button>
          </div>
        ) : <p className="mt-2 text-xs text-slate-400">Only an admin can change the organisation's prompt.</p>}
        <div className="mt-2 space-y-2">
          {msg && <p className="text-sm text-emerald-600">{msg}</p>}
          <ErrorText error={error} />
          <p className="text-xs text-slate-400">{s.is_default ? 'Using the default prompt.' : `Last changed by ${s.updated_by ?? 'an admin'}${s.updated_at ? ` on ${new Date(s.updated_at).toLocaleString()}` : ''}.`}</p>
        </div>
      </Panel>
      <Panel title="Always applied (locked)">
        <p className="mb-2 text-sm text-slate-500">These rules keep every claim tied to a real source and are added after your prompt. They can't be edited, because the evidence gate depends on them.</p>
        <pre className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">{s.locked_rules}</pre>
      </Panel>
    </div>
  )
}
