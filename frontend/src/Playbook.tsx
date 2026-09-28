import { useEffect, useMemo, useState } from 'react'
import { listInsights, type Insight } from './api'
import { ErrorText, Panel, errMsg, pill } from './ui'

/** What the company has learned across all customers: generalised lessons, never customer names. */
export default function Playbook() {
  const [items, setItems] = useState<Insight[] | null>(null)
  const [error, setError] = useState('')
  const [industry, setIndustry] = useState('')
  const [kind, setKind] = useState('')

  useEffect(() => { listInsights().then(setItems).catch(e => setError(errMsg(e))) }, [])
  const industries = useMemo(() => [...new Set((items ?? []).map(i => i.industry).filter(Boolean) as string[])].sort(), [items])
  const kinds = useMemo(() => [...new Set((items ?? []).map(i => i.kind))].sort(), [items])
  const shown = (items ?? []).filter(i => (!industry || i.industry === industry) && (!kind || i.kind === kind))

  return (
    <Panel title={`Company playbook${items ? ` · ${items.length} lessons` : ''}`}>
      <p className="mb-3 text-sm text-slate-500">Lessons the agent extracted from every customer interaction, generalised so they can be reused with any customer.
        Every brief pulls the lessons that match the customer's industry.</p>
      <ErrorText error={error} />
      <div className="mb-3 flex flex-wrap gap-1.5">
        <button className={pill(!industry)} onClick={() => setIndustry('')}>All industries</button>
        {industries.map(i => <button key={i} className={pill(industry === i)} onClick={() => setIndustry(i)}>{i}</button>)}
      </div>
      <div className="mb-4 flex flex-wrap gap-1.5">
        <button className={pill(!kind)} onClick={() => setKind('')}>All kinds</button>
        {kinds.map(k => <button key={k} className={pill(kind === k)} onClick={() => setKind(k)}>{k.replace(/_/g, ' ')}</button>)}
      </div>
      {!items ? <p className="text-sm text-slate-400">Loading…</p> : !shown.length ? <p className="text-sm text-slate-400">No lessons yet.</p> : (
        <ul className="grid gap-3 md:grid-cols-2">
          {shown.map(i => (
            <li key={i.id} className="rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-800">
              <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">{i.kind.replace(/_/g, ' ')}</span>
                {i.industry && <span className="text-slate-500">{i.industry}</span>}
                {i.role && <span className="text-slate-500">· {i.role}</span>}
                {i.evidence === 'confirmed_outcome' && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">confirmed by outcome</span>}
                <span className="ml-auto font-mono text-slate-400">{i.id}</span>
              </div>
              {i.text}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
