import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { analyze, recordOutcome, timeline, type Decision, type OutcomeKind, type Reading, type Status, type Timeline } from './api'

type Form = Record<keyof Reading, string>

const PRESETS: Record<string, Form> = {
  'Heat pattern': { machine_id: 'M-103', variant: 'M', air_temperature_k: '300.8', process_temperature_k: '309.4', rpm: '1340', torque_nm: '55', tool_wear_min: '113' },
  'Worn tool': { machine_id: 'M-102', variant: 'L', air_temperature_k: '299.0', process_temperature_k: '309.8', rpm: '1450', torque_nm: '52', tool_wear_min: '205' },
  Healthy: { machine_id: 'M-101', variant: 'M', air_temperature_k: '300.0', process_temperature_k: '311.0', rpm: '1550', torque_nm: '40', tool_wear_min: '60' },
}

const FIELDS: [keyof Reading, string, string, string][] = [
  ['air_temperature_k', 'Air temperature', 'K', '0.1'],
  ['process_temperature_k', 'Process temperature', 'K', '0.1'],
  ['rpm', 'Spindle speed', 'rpm', '1'],
  ['torque_nm', 'Torque', 'Nm', '0.1'],
  ['tool_wear_min', 'Tool wear', 'min', '1'],
]

const STATUS: Record<Status, { text: string; bg: string; dot: string; label: string }> = {
  NORMAL: { text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 ring-emerald-200 dark:bg-emerald-950/40 dark:ring-emerald-900', dot: 'bg-emerald-500', label: 'No meaningful historical risk' },
  MONITOR: { text: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 ring-amber-200 dark:bg-amber-950/40 dark:ring-amber-900', dot: 'bg-amber-500', label: 'Some similarity, weak evidence' },
  ESCALATE: { text: 'text-rose-600 dark:text-rose-400', bg: 'bg-rose-50 ring-rose-200 dark:bg-rose-950/40 dark:ring-rose-900', dot: 'bg-rose-500', label: 'Strong historical failure pattern' },
}

const input = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900'
const btn = 'rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-wait disabled:opacity-50'
const primary = `${btn} bg-indigo-600 text-white shadow-sm hover:bg-indigo-500`

export default function App() {
  const [decision, setDecision] = useState<Decision | null>(null)
  const [tl, setTl] = useState<Timeline | null>(null)
  const refresh = () => timeline().then(setTl).catch(() => {})
  useEffect(() => { refresh() }, [])

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">
            <span className="size-2 animate-pulse rounded-full bg-indigo-500" /> Near-miss memory agent
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Machine Never Miss</h1>
          <p className="mt-1 text-slate-500 dark:text-slate-400">Remembers what almost went wrong, and escalates before it happens again.</p>
        </div>
        <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white dark:bg-white dark:text-slate-900">Memory by Hindsight</span>
      </header>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2"><SensorForm onDecision={setDecision} /></div>
        <div className="lg:col-span-3"><DecisionCard d={decision} /></div>
        {decision && <div className="lg:col-span-5"><Evidence d={decision} onSaved={refresh} /></div>}
        <div className="lg:col-span-5"><MemoryTimeline t={tl} /></div>
      </div>
    </div>
  )
}

function Card({ step, title, children }: { step: number; title: string; children: ReactNode }) {
  return (
    <section className="h-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900/60">
      <h2 className="mb-5 flex items-center gap-3 text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        <span className="grid size-6 place-items-center rounded-full bg-slate-100 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">{step}</span>
        {title}
      </h2>
      {children}
    </section>
  )
}

function SensorForm({ onDecision }: { onDecision: (d: Decision) => void }) {
  const [form, setForm] = useState<Form>(PRESETS['Heat pattern'])
  const [preset, setPreset] = useState('Heat pattern')
  const [useMemory, setUseMemory] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    const num = (v: string) => (v === '' ? null : Number(v)) as number // empty -> null so the API reports it missing
    const reading: Reading = {
      machine_id: form.machine_id, variant: form.variant as Reading['variant'],
      air_temperature_k: num(form.air_temperature_k), process_temperature_k: num(form.process_temperature_k),
      rpm: num(form.rpm), torque_nm: num(form.torque_nm), tool_wear_min: num(form.tool_wear_min),
    }
    setBusy(true); setError('')
    try { onDecision(await analyze(reading, useMemory)) }
    catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Card step={1} title="Current sensor state">
      <div className="mb-5 flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
        {Object.keys(PRESETS).map(p => (
          <button key={p} type="button" onClick={() => { setForm(PRESETS[p]); setPreset(p) }}
            className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition ${preset === p ? 'bg-white shadow-sm dark:bg-slate-950' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}`}>
            {p}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <label className="col-span-2 text-xs font-medium text-slate-500">Machine
            <input className={`${input} mt-1`} value={form.machine_id} onChange={e => setForm({ ...form, machine_id: e.target.value })} required />
          </label>
          <label className="text-xs font-medium text-slate-500">Variant
            <select className={`${input} mt-1`} value={form.variant} onChange={e => setForm({ ...form, variant: e.target.value })}>
              <option>L</option><option>M</option><option>H</option>
            </select>
          </label>
        </div>
        {FIELDS.map(([k, label, unit, step]) => (
          <label key={k} className="flex items-center justify-between gap-4 text-sm">
            <span className="text-slate-600 dark:text-slate-300">{label}</span>
            <span className="relative w-36">
              <input className={`${input} pr-12 text-right tabular-nums`} type="number" step={step} value={form[k]}
                onChange={e => setForm({ ...form, [k]: e.target.value })} />
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-slate-400">{unit}</span>
            </span>
          </label>
        ))}
        <label className="flex cursor-pointer items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
          <span>Use Hindsight memory</span>
          <input type="checkbox" className="peer sr-only" checked={useMemory} onChange={e => setUseMemory(e.target.checked)} />
          <span className="relative h-5 w-9 rounded-full bg-slate-300 transition peer-checked:bg-indigo-600 peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500/40 after:absolute after:left-0.5 after:top-0.5 after:size-4 after:rounded-full after:bg-white after:transition peer-checked:after:translate-x-4 dark:bg-slate-700" />
        </label>
        <button className={`${primary} w-full py-2.5`} disabled={busy}>{busy ? 'Recalling memory…' : 'Analyze reading'}</button>
        {error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p>}
      </form>
    </Card>
  )
}

function DecisionCard({ d }: { d: Decision | null }) {
  if (!d) return (
    <Card step={2} title="Agent decision">
      <div className="grid h-64 place-items-center rounded-xl border-2 border-dashed border-slate-200 text-center text-sm text-slate-400 dark:border-slate-800">
        Pick a preset and analyze.<br />The agent compares it with remembered near-misses and failures.
      </div>
    </Card>
  )
  const s = STATUS[d.status]
  const stats: [string | number, string][] = [
    [d.historical_matches, 'similar cases'], [d.similar_failures, 'failed'], [d.similar_prevented_events, 'prevented'],
  ]
  return (
    <Card step={2} title="Agent decision">
      <div className={`rounded-xl p-5 ring-1 ${s.bg}`}>
        <div className="flex items-center gap-3">
          <span className={`size-3 rounded-full ${s.dot} ${d.status === 'ESCALATE' ? 'animate-pulse' : ''}`} />
          <span className={`text-3xl font-extrabold tracking-tight ${s.text}`}>{d.status}</span>
        </div>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{s.label}</p>
      </div>

      <div className="mt-4">
        <div className="flex justify-between text-xs font-medium text-slate-500">
          <span>Pattern strength</span><span>{d.pattern_label} · {d.pattern_strength}</span>
        </div>
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div className={`h-full rounded-full ${s.dot} transition-all duration-700`} style={{ width: `${d.pattern_strength * 100}%` }} />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        {stats.map(([n, l]) => (
          <div key={l} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/60">
            <div className="text-2xl font-bold tabular-nums">{n}</div>
            <div className="text-xs text-slate-500">{l}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-900 dark:bg-indigo-950/40">
        <div className="text-xs font-semibold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">Recommendation</div>
        <p className="mt-1 font-medium">{d.recommendation}</p>
      </div>
      <p className="mt-4 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{d.reason}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {(d.recurring_signals.length ? d.recurring_signals : ['no elevated signals']).map(sig => (
          <span key={sig} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{sig}</span>
        ))}
      </div>
    </Card>
  )
}

const OUTCOME_STYLE: Record<OutcomeKind, string> = {
  failed: 'border-l-rose-500', prevented_failure: 'border-l-emerald-500', normal: 'border-l-slate-300 dark:border-l-slate-600',
}
const OUTCOME_LABEL: Record<OutcomeKind, string> = { failed: 'Failed', prevented_failure: 'Prevented', normal: 'Normal' }

function Evidence({ d, onSaved }: { d: Decision; onSaved: () => void }) {
  const [action, setAction] = useState('')
  const [outcome, setOutcome] = useState<OutcomeKind>('prevented_failure')
  const [notes, setNotes] = useState('')
  const [msg, setMsg] = useState('')
  const [savedFor, setSavedFor] = useState('')
  const [busy, setBusy] = useState(false)

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg('')
    try {
      const r = await recordOutcome(d.event_id, action, outcome, notes)
      setMsg(`Saved as ${r.retained}. Analyze a similar reading to see the agent use it.`)
      setSavedFor(d.event_id); setAction(''); setNotes(''); onSaved()
    } catch (err) { setMsg((err as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Card step={3} title="Why? Historical evidence">
      {d.evidence.length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {d.evidence.map(e => (
            <article key={e.experience_id} className={`rounded-lg border border-l-4 border-slate-200 p-3 dark:border-slate-800 ${OUTCOME_STYLE[e.outcome]}`}>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-mono font-semibold">{e.experience_id}</span>
                <span className="text-slate-500">{e.timestamp.slice(0, 10)} · {OUTCOME_LABEL[e.outcome]} · distance {e.distance}</span>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{e.text}</p>
            </article>
          ))}
        </div>
      ) : <p className="text-sm text-slate-500">No similar historical experience. The agent is not inventing one.</p>}

      <div className="mt-6 border-t border-slate-200 pt-5 dark:border-slate-800">
        <h3 className="mb-3 text-sm font-semibold">Record what happened. The agent learns from it.</h3>
        {savedFor === d.event_id ? (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">{msg}</p>
        ) : (
          <form className="flex flex-col gap-3 md:flex-row" onSubmit={save}>
            <input className={`${input} md:flex-[2]`} placeholder="Action taken, e.g. inspected bearing, reduced load" value={action} onChange={e => setAction(e.target.value)} required />
            <select className={`${input} md:flex-1`} value={outcome} onChange={e => setOutcome(e.target.value as OutcomeKind)}>
              <option value="prevented_failure">Failure prevented</option>
              <option value="failed">Machine failed</option>
              <option value="normal">Nothing happened</option>
            </select>
            <input className={`${input} md:flex-1`} placeholder="Notes (optional)" value={notes} onChange={e => setNotes(e.target.value)} />
            <button className={`${primary} whitespace-nowrap`} disabled={busy}>{busy ? 'Saving…' : 'Save to memory'}</button>
          </form>
        )}
        {msg && savedFor !== d.event_id && <p className="mt-2 text-sm text-rose-600">{msg}</p>}
      </div>
    </Card>
  )
}

function MemoryTimeline({ t }: { t: Timeline | null }) {
  if (!t) return null
  const max = Math.max(1, ...t.months.map(m => (m.failure ?? 0) + (m.near_miss ?? 0)))
  const pct = (n = 0) => `${(n / max) * 100}%`
  const total = t.months.reduce((a, m) => a + (m.failure ?? 0) + (m.near_miss ?? 0), 0)
  return (
    <Card step={4} title="Memory evolution">
      <div className="mb-4 flex flex-wrap items-center gap-4 text-xs text-slate-500">
        <span className="text-sm font-medium text-slate-900 dark:text-white">{total + t.learned.length} risk experiences remembered</span>
        <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-sm bg-rose-500" /> failures</span>
        <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-sm bg-amber-400" /> near-misses</span>
        <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-sm bg-indigo-500" /> learned live</span>
      </div>
      <div className="flex h-40 items-end gap-2 border-b border-slate-200 dark:border-slate-800">
        {t.months.map(m => (
          <div key={m.month} title={`${m.month}: ${m.failure ?? 0} failures, ${m.near_miss ?? 0} near-misses`}
            className="flex h-full flex-1 flex-col-reverse overflow-hidden rounded-t-md">
            <div className="bg-rose-500" style={{ height: pct(m.failure) }} />
            <div className="bg-amber-400" style={{ height: pct(m.near_miss) }} />
          </div>
        ))}
        {t.learned.length > 0 && (
          <div title={`${t.learned.length} learned live`} className="flex h-full flex-1 flex-col-reverse">
            <div className="min-h-2 rounded-t-md bg-indigo-500" style={{ height: pct(t.learned.length) }} />
          </div>
        )}
      </div>
      <div className="mt-2 flex gap-2 text-center text-[11px] text-slate-400">
        {t.months.map(m => <span key={m.month} className="flex-1">{m.month.slice(5)}</span>)}
        {t.learned.length > 0 && <span className="flex-1 font-semibold text-indigo-500">live</span>}
      </div>
    </Card>
  )
}
