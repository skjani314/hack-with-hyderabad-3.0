import { useEffect, useState } from 'react'
import { getLedger, rebuildLedger, type Ledger, type LedgerItem } from './api'
import { ErrorText, Panel, SourceChips, Tip, errMsg } from './ui'

const OPEN = new Set(['open', 'at_risk', 'overdue'])
const STATUS_CLS: Record<string, string> = {
  open: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300',
  at_risk: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  overdue: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
  done: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  resolved: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  dropped: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
}
const STANCE_CLS: Record<string, string> = {
  blocker: 'text-rose-600', skeptic: 'text-orange-600', neutral: 'text-slate-500', supporter: 'text-sky-600', champion: 'text-emerald-600',
}

function Item({ it, onSource }: { it: LedgerItem; onSource: (id: string) => void }) {
  return (
    <li className="text-sm leading-snug">
      <span className={`mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${STATUS_CLS[it.status] ?? ''}`}>{it.status.replace('_', ' ')}</span>
      <span className={OPEN.has(it.status) ? '' : 'text-slate-500 line-through decoration-slate-300'}>{it.text}</span>
      <span className="text-xs text-slate-400">{[it.owner, it.due].filter(Boolean).length ? ` · ${[it.owner, it.due].filter(Boolean).join(' · ')}` : ''}</span>{' '}
      <SourceChips ids={it.sources} onSource={onSource} />
    </li>
  )
}

/** The customer's current state: kept up to date by the agent on every upload, read first by every brief. */
export default function LedgerPanel({ customerId, version, onSource }: { customerId: string; version: number; onSource: (id: string) => void }) {
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    getLedger(customerId).then(l => live && setLedger(l)).catch(e => live && setError(errMsg(e)))
    return () => { live = false }
  }, [customerId, version])

  async function rebuild() {
    setBusy(true); setError('')
    try { setLedger(await rebuildLedger(customerId)) } catch (e) { setError(errMsg(e)) } finally { setBusy(false) }
  }

  const items = ledger?.items ?? []
  const open = items.filter(i => OPEN.has(i.status) && i.kind !== 'requirement')
  const closed = items.filter(i => !OPEN.has(i.status))
  const standing = items.filter(i => OPEN.has(i.status) && i.kind === 'requirement')
  const customers = (ledger?.people ?? []).filter(p => p.side === 'customer')

  return (
    <Panel title="Deal ledger" action={
      <Tip below wide text="Rebuilds the ledger from every stored interaction, in date order. Use it if the ledger looks wrong after old data was fixed. Takes a minute (one AI call per one or two messages).">
        <button className="rounded-full bg-slate-100 px-2.5 py-1 text-xs hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-800" disabled={busy} onClick={rebuild}>{busy ? 'Rebuilding…' : 'Rebuild'}</button>
      </Tip>}>
      <p className="mb-3 text-xs text-slate-500">The current state of the deal, updated on every upload. Every brief reads this first; each line links to the message behind it.</p>
      <ErrorText error={error} />
      {!ledger ? <p className="text-sm text-slate-400">Loading…</p> : !items.length ? (
        <p className="text-sm text-slate-400">Empty. It fills in as interactions are added, or press Rebuild.</p>
      ) : (
        <div className="space-y-4">
          {ledger.summary && <p className="rounded-lg bg-slate-50 p-2 text-sm dark:bg-slate-800/60"><span className="mr-1 rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white">{ledger.stage}</span>{ledger.summary}</p>}
          <div>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">Open ({open.length})</h3>
            <ul className="space-y-1.5">{open.map(it => <Item key={it.id ?? it.text} it={it} onSource={onSource} />)}</ul>
          </div>
          {customers.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">Where people stand</h3>
              <ul className="space-y-1 text-sm">{customers.map(p => (
                <li key={p.name}><b>{p.name}</b> <span className={`text-xs font-semibold ${STANCE_CLS[p.stance] ?? ''}`}>{p.stance}</span>
                  <span className="text-slate-500"> · {p.position}</span> <SourceChips ids={p.sources.slice(-2)} onSource={onSource} /></li>
              ))}</ul>
            </div>
          )}
          {closed.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400">Done / resolved ({closed.length})</summary>
              <ul className="mt-1.5 space-y-1.5">{closed.map(it => <Item key={it.id ?? it.text} it={it} onSource={onSource} />)}</ul>
            </details>
          )}
          {standing.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400">Standing requirements ({standing.length})</summary>
              <ul className="mt-1.5 space-y-1.5">{standing.map(it => <Item key={it.id ?? it.text} it={it} onSource={onSource} />)}</ul>
            </details>
          )}
          {ledger.updated_at && <p className="text-[11px] text-slate-400">Updated {new Date(ledger.updated_at).toLocaleString()} · from {ledger.based_on?.length ?? 0} interactions</p>}
        </div>
      )}
    </Panel>
  )
}
