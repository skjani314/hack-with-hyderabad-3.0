import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  ask, getDeal, getProfile, recordOutcome, remember, resetMemory,
  type Channel, type DealResponse, type Interaction, type Profile,
} from './api'

const CHANNEL: Record<Channel, { label: string; cls: string; icon: string }> = {
  crm: { label: 'CRM', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300', icon: '▦' },
  email: { label: 'Email', cls: 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300', icon: '✉' },
  call: { label: 'Call', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300', icon: '☎' },
  whatsapp: { label: 'WhatsApp', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300', icon: '◉' },
  outcome: { label: 'Outcome', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300', icon: '★' },
}

const QUESTIONS = [
  'I have a call with Acme tomorrow. What should I focus on?',
  'What objections have they raised?',
  'Who are the stakeholders and what does each care about?',
  'Which competitor are they considering?',
  'What have we promised them, and is anything overdue?',
  'Draft my follow-up email.',
]

const card = 'rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900/60'
const input = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900'
const btn = 'rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-wait disabled:opacity-50'
const primary = `${btn} bg-indigo-600 text-white shadow-sm hover:bg-indigo-500`
const ghost = `${btn} border border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800`

export default function App() {
  const [deal, setDeal] = useState<DealResponse | null>(null)
  const [error, setError] = useState('')
  const [focus, setFocus] = useState<string | null>(null)
  const [profileVersion, setProfileVersion] = useState(0)

  const refresh = useCallback(() => getDeal().then(setDeal).catch(e => setError(e.message)), [])
  useEffect(() => { refresh() }, [refresh])

  const afterMemoryChange = async () => { await refresh(); setProfileVersion(v => v + 1) }

  async function reset() {
    if (!confirm('Wipe the demo memory? The before/after demo can then be run again.')) return
    try { await resetMemory(); await afterMemoryChange() } catch (e) { setError((e as Error).message) }
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Sales Memory Agent</div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Remembers the customer so you don't have to</h1>
          {deal && (
            <p className="mt-1 text-sm text-slate-500">
              {deal.deal.customer} · {deal.deal.product} · {deal.deal.value} · stage {deal.deal.stage} · {deal.deal.salesperson}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {deal && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white dark:bg-white dark:text-slate-900">
              {deal.memory_count} memories in Hindsight
            </span>
          )}
          <button className={ghost} onClick={reset}>Reset memory</button>
        </div>
      </header>

      {error && <p className="mb-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p>}
      {!deal ? <p className="text-sm text-slate-500">Loading deal…</p> : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)]">
          <Sources deal={deal} focus={focus} setFocus={setFocus} onChange={afterMemoryChange} />
          <div className="flex min-w-0 flex-col gap-5">
            <Chat memoryCount={deal.memory_count} onSource={setFocus} />
            <OutcomeForm onSaved={afterMemoryChange} />
          </div>
          <DealProfile version={profileVersion} empty={deal.memory_count === 0} onSource={setFocus} />
        </div>
      )}
      {deal && <p className="mt-6 text-xs text-slate-400">{deal.deal.sources}</p>}
    </div>
  )
}

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className={`${card} min-w-0 p-5`}>
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function SourceChips({ ids, onSource }: { ids: string[]; onSource: (id: string) => void }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ids.map(id => (
        <button key={id} type="button" onClick={() => onSource(id)}
          className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 hover:bg-indigo-100 hover:text-indigo-700 dark:bg-slate-800 dark:text-slate-300">
          {id}
        </button>
      ))}
    </span>
  )
}

function Sources({ deal, focus, setFocus, onChange }: {
  deal: DealResponse; focus: string | null; setFocus: (id: string | null) => void; onChange: () => Promise<void>
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const pending = deal.interactions.filter(i => !i.remembered)

  async function add(ids: string[], label: string) {
    setBusy(label); setError('')
    try { await remember(ids); await onChange() } catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }

  return (
    <Panel title="Deal sources" action={
      <div className="flex gap-2">
        <button className={ghost} disabled={!!busy || !pending.length} onClick={() => add([pending[0].id], 'next')}>
          {busy === 'next' ? 'Remembering…' : '+ Next'}
        </button>
        <button className={primary} disabled={!!busy || !pending.length} onClick={() => add(pending.map(p => p.id), 'all')}>
          {busy === 'all' ? 'Remembering…' : 'Remember all'}
        </button>
      </div>
    }>
      <p className="mb-3 text-xs text-slate-500">
        {deal.interactions.length - pending.length}/{deal.interactions.length} conversations in memory.
        Add them one by one and ask the same question to watch the agent learn.
      </p>
      {error && <p className="mb-2 text-sm text-rose-600">{error}</p>}
      <ol className="relative space-y-2 border-l border-slate-200 pl-4 dark:border-slate-800">
        {deal.interactions.map(i => <SourceItem key={i.id} i={i} open={focus === i.id} toggle={() => setFocus(focus === i.id ? null : i.id)} />)}
        {deal.outcomes.map(id => (
          <li key={id} className="text-xs text-rose-600">★ {id} call outcome recorded</li>
        ))}
      </ol>
    </Panel>
  )
}

function SourceItem({ i, open, toggle }: { i: Interaction; open: boolean; toggle: () => void }) {
  const c = CHANNEL[i.channel]
  return (
    <li ref={el => { if (open) el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }}
      className={`relative rounded-lg p-2 transition ${open ? 'bg-indigo-50 ring-1 ring-indigo-300 dark:bg-indigo-950/40 dark:ring-indigo-800' : ''} ${i.remembered ? '' : 'opacity-50'}`}>
      <span className={`absolute -left-[21px] top-3 size-2.5 rounded-full ${i.remembered ? 'bg-indigo-500' : 'bg-slate-300 dark:bg-slate-700'}`} />
      <button type="button" onClick={toggle} className="w-full text-left">
        <div className="flex items-center gap-2 text-xs">
          <span className={`rounded px-1.5 py-0.5 font-medium ${c.cls}`}>{c.icon} {c.label}</span>
          <span className="font-mono text-slate-500">{i.id}</span>
          <span className="ml-auto text-slate-400">{i.date.slice(0, 10)}</span>
        </div>
        <div className="mt-1 text-sm font-medium">{i.title}</div>
        {!i.remembered && <div className="text-xs text-slate-400">not in memory yet</div>}
      </button>
      {open && (
        <div className="mt-2 whitespace-pre-wrap rounded-md bg-white p-2 text-xs leading-relaxed text-slate-600 dark:bg-slate-950 dark:text-slate-300">
          {(i.from || i.participants) && <div className="mb-1 font-medium">{i.from ?? i.participants}</div>}
          {i.content}
        </div>
      )}
    </li>
  )
}

interface Msg { q: string; answer?: string; sources?: string[]; memory?: number; usedMemory: boolean; error?: string }

function Chat({ memoryCount, onSource }: { memoryCount: number; onSource: (id: string) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [q, setQ] = useState('')
  const [useMemory, setUseMemory] = useState(true)
  const [busy, setBusy] = useState(false)

  async function send(question: string, e?: FormEvent) {
    e?.preventDefault()
    if (!question.trim() || busy) return
    setBusy(true); setQ('')
    setMsgs(m => [...m, { q: question, usedMemory: useMemory }])
    try {
      const r = await ask(question, useMemory)
      setMsgs(m => m.map((x, k) => k === m.length - 1 ? { ...x, answer: r.answer, sources: r.sources, memory: r.memory_count } : x))
    } catch (err) {
      setMsgs(m => m.map((x, k) => k === m.length - 1 ? { ...x, error: (err as Error).message } : x))
    } finally { setBusy(false) }
  }

  return (
    <Panel title="Ask the agent" action={
      <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-500">
        Use memory
        <input type="checkbox" className="peer sr-only" checked={useMemory} onChange={e => setUseMemory(e.target.checked)} />
        <span className="relative h-5 w-9 rounded-full bg-slate-300 transition peer-checked:bg-indigo-600 after:absolute after:left-0.5 after:top-0.5 after:size-4 after:rounded-full after:bg-white after:transition peer-checked:after:translate-x-4 dark:bg-slate-700" />
      </label>
    }>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {QUESTIONS.map(s => (
          <button key={s} type="button" disabled={busy} onClick={() => send(s)}
            className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 transition hover:bg-indigo-100 hover:text-indigo-700 disabled:opacity-50 dark:bg-slate-800 dark:text-slate-300">
            {s}
          </button>
        ))}
      </div>
      <div className="max-h-[520px] space-y-4 overflow-y-auto pr-1">
        {!msgs.length && (
          <p className="rounded-xl border-2 border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-800">
            Ask about the deal. With {memoryCount} memories the agent answers from what the customer actually said.
          </p>
        )}
        {msgs.map((m, k) => (
          <div key={k} className="space-y-2">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white">{m.q}</div>
            <div className="max-w-[95%] rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2 text-sm leading-relaxed dark:bg-slate-800">
              {m.error ? <span className="text-rose-600">{m.error}</span>
                : m.answer === undefined ? <span className="animate-pulse text-slate-400">Recalling deal memory…</span>
                  : <>
                    <p className="whitespace-pre-wrap">{m.answer}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                      <span className={`rounded-full px-2 py-0.5 font-medium ${m.usedMemory ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'}`}>
                        {m.usedMemory ? `from ${m.memory} memories` : 'memory off'}
                      </span>
                      {!!m.sources?.length && <>sources <SourceChips ids={m.sources} onSource={onSource} /></>}
                    </div>
                  </>}
            </div>
          </div>
        ))}
      </div>
      <form className="mt-4 flex gap-2" onSubmit={e => send(q, e)}>
        <input className={input} placeholder="Ask anything about this customer…" value={q} onChange={e => setQ(e.target.value)} />
        <button className={primary} disabled={busy || !q.trim()}>Ask</button>
      </form>
    </Panel>
  )
}

const STATUS_CLS = (s: string) => /overdue|late|missed/i.test(s) ? 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300'
  : /done|resolved|complete|sent/i.test(s) ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'

function DealProfile({ version, empty, onSource }: { version: number; empty: boolean; onSource: (id: string) => void }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [dropped, setDropped] = useState(0)
  const [loaded, setLoaded] = useState<{ version: number; error: string } | null>(null)
  const busy = !empty && loaded?.version !== version  // a reload is in flight until this version lands
  const error = loaded?.version === version ? loaded.error : ''

  useEffect(() => {
    if (empty) return
    let live = true
    getProfile()
      .then(r => { if (live) { setProfile(r.profile); setDropped(r.dropped); setLoaded({ version, error: '' }) } })
      .catch(e => { if (live) setLoaded({ version, error: e.message }) })
    return () => { live = false }
  }, [version, empty])

  const shown = empty ? null : profile
  const section = (title: string, items: ReactNode[]) => items.length > 0 && (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h3>
      <ul className="space-y-1.5">{items}</ul>
    </div>
  )
  const li = (key: string, body: ReactNode, sources: string[]) => (
    <li key={key} className="text-sm leading-snug">{body} <SourceChips ids={sources} onSource={onSource} /></li>
  )

  return (
    <Panel title="What the agent extracted" action={busy && <span className="animate-pulse text-xs text-indigo-500">updating…</span>}>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {!shown ? (
        <p className="text-sm text-slate-400">{empty ? 'Memory is empty. Remember some conversations to build the deal profile.' : busy ? 'Reading memory…' : ''}</p>
      ) : (
        <div className="space-y-4">
          {section('Pain points', shown.pain_points.map((p, k) => li(`p${k}`, p.text, p.sources)))}
          {section('Stakeholders', shown.stakeholders.map((s, k) => li(`s${k}`,
            <><b>{s.name}</b> <span className="text-slate-500">({s.role})</span>: {s.cares_about}</>, s.sources)))}
          {section('Objections', shown.objections.map((o, k) => li(`o${k}`,
            <>{o.text} <span className="text-slate-500">({o.raised_by})</span>{' '}
              <span className={`rounded px-1.5 text-[11px] font-medium ${STATUS_CLS(o.status)}`}>{o.status}</span></>, o.sources)))}
          {section('Competitors', shown.competitors.map((c, k) => li(`c${k}`, <><b>{c.name}</b>: {c.notes}</>, c.sources)))}
          {section('Commitments', shown.commitments.map((c, k) => li(`m${k}`,
            <>{c.text} <span className="text-slate-500">({c.owner}, due {c.due})</span>{' '}
              <span className={`rounded px-1.5 text-[11px] font-medium ${STATUS_CLS(c.status)}`}>{c.status}</span></>, c.sources)))}
          {section('Pricing', shown.pricing.map((p, k) => li(`$${k}`, p.text, p.sources)))}
          <p className="border-t border-slate-200 pt-3 text-xs text-slate-400 dark:border-slate-800">
            Every item links to the message it came from.{dropped > 0 && ` ${dropped} unsourced claim${dropped > 1 ? 's were' : ' was'} removed.`}
          </p>
        </div>
      )}
    </Panel>
  )
}

function OutcomeForm({ onSaved }: { onSaved: () => Promise<void> }) {
  const [result, setResult] = useState('Positive')
  const [summary, setSummary] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg('')
    try {
      const r = await recordOutcome(summary, result, next)
      setMsg(`Saved as ${r.remembered}. Ask again: the next answer uses this outcome.`)
      setSummary(''); setNext(''); await onSaved()
    } catch (err) { setMsg((err as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Panel title="Record call outcome">
      <form className="space-y-2" onSubmit={save}>
        <div className="flex flex-wrap gap-1.5">
          {['Positive', 'Neutral', 'Negative', 'Won', 'Lost'].map(r => (
            <button key={r} type="button" onClick={() => setResult(r)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${result === r ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
              {r}
            </button>
          ))}
        </div>
        <textarea className={`${input} min-h-20`} required minLength={3} placeholder="What happened? e.g. Sent the security questionnaire; Priya approved. Michael agreed to 7% off with 3-year support."
          value={summary} onChange={e => setSummary(e.target.value)} />
        <input className={input} placeholder="Agreed next step (optional)" value={next} onChange={e => setNext(e.target.value)} />
        <button className={`${primary} w-full`} disabled={busy}>{busy ? 'Saving to memory…' : 'Save outcome to memory'}</button>
        {msg && <p className="text-sm text-slate-500">{msg}</p>}
      </form>
    </Panel>
  )
}
