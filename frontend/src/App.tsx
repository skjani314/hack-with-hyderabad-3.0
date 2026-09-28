import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  addSource, ask, getDeal, getProfile, importSample, prepareCall, recordOutcome, resetMemory, sourceText,
  type CallPrep, type Channel, type DealResponse, type Profile, type Source, type TraceStep,
} from './api'

const STEP_LABEL: Record<string, string> = {
  list_sources: 'Listed conversations', recall: 'Recalled from Hindsight', recall_memory: 'Agent searched memory',
  read_source: 'Agent read message', save_note: 'Agent saved note',
}

/** What the agent did with memory for one answer: shown so judges and users can see memory at work. */
function MemoryTrace({ steps }: { steps: TraceStep[] }) {
  if (!steps.length) return null
  return (
    <details className="mt-2 text-[11px] text-slate-500">
      <summary className="cursor-pointer select-none font-medium text-violet-600 dark:text-violet-400">
        🧠 Agent memory work · {steps.length} steps
      </summary>
      <ol className="mt-1 space-y-0.5 border-l-2 border-violet-200 pl-2 dark:border-violet-900">
        {steps.map((s, k) => (
          <li key={k}>
            <b>{STEP_LABEL[s.step] ?? s.step}</b>{s.detail && <>: <i>"{s.detail}"</i></>}{s.result && <span className="text-slate-400"> → {s.result}</span>}
          </li>
        ))}
      </ol>
    </details>
  )
}

const CHANNEL: Record<Channel, { label: string; cls: string; icon: string }> = {
  crm: { label: 'CRM', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300', icon: '▦' },
  email: { label: 'Email', cls: 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300', icon: '✉' },
  call: { label: 'Call', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300', icon: '☎' },
  whatsapp: { label: 'WhatsApp', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300', icon: '◉' },
  outcome: { label: 'Outcome', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300', icon: '★' },
  note: { label: 'Note', cls: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300', icon: '✎' },
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

  const refresh = useCallback(() => getDeal().then(d => { setDeal(d); setError('') }).catch(e => setError(e.message)), [])
  useEffect(() => { refresh() }, [refresh])

  const afterMemoryChange = async () => { await refresh(); setProfileVersion(v => v + 1) }

  async function reset() {
    if (!confirm('Wipe the Hindsight memory bank? The before/after demo can then be run again.')) return
    try { await resetMemory(); await afterMemoryChange() } catch (e) { setError((e as Error).message) }
  }

  const info = deal?.deal
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Sales Memory Agent</div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Remembers the customer so you don't have to</h1>
          <p className="mt-1 text-sm text-slate-500">
            {info ? `${info.customer} · ${info.product} · ${info.value} · stage ${info.stage} · ${info.salesperson}`
              : 'No deal in memory yet. Import the sample CRM data to start.'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {deal && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white dark:bg-white dark:text-slate-900">
              {deal.memory_count} documents in Hindsight
            </span>
          )}
          <button className={ghost} onClick={reset}>Reset memory</button>
        </div>
      </header>

      {error && <p className="mb-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p>}
      {!deal ? <p className="text-sm text-slate-500">{error ? '' : 'Loading memory…'}</p> : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-5">
            <Sources deal={deal} focus={focus} setFocus={setFocus} onChange={afterMemoryChange} />
            {info && <AddSource onSaved={afterMemoryChange} />}
          </div>
          <div className="flex min-w-0 flex-col gap-5">
            <Chat memoryCount={deal.memory_count} ready={!!info} onSource={setFocus} />
            {info && <OutcomeForm onSaved={afterMemoryChange} />}
          </div>
          <div className="flex min-w-0 flex-col gap-5">
            {info && <CallPrepPanel onSource={setFocus} />}
            <DealProfile version={profileVersion} empty={deal.memory_count === 0} onSource={setFocus} />
          </div>
        </div>
      )}
      {info && <p className="mt-6 text-xs text-slate-400">{info.sources}</p>}
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

  async function load(mode: 'next' | 'all') {
    setBusy(mode); setError('')
    try { await importSample(mode); await onChange() } catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }

  return (
    <Panel title="Memory: deal sources" action={deal.sample_remaining > 0 && (
      <div className="flex gap-2">
        <button className={ghost} disabled={!!busy} onClick={() => load('next')}>{busy === 'next' ? 'Importing…' : '+ Next'}</button>
        <button className={primary} disabled={!!busy} onClick={() => load('all')}>{busy === 'all' ? 'Importing…' : 'Import all'}</button>
      </div>
    )}>
      <p className="mb-3 text-xs text-slate-500">
        Everything below is read from the Hindsight memory bank.
        {deal.sample_remaining > 0 && ` Sample CRM connector: ${deal.sample_remaining} messages not imported yet. Import one at a time and ask the same question to watch the agent learn.`}
      </p>
      {error && <p className="mb-2 text-sm text-rose-600">{error}</p>}
      {!deal.sources.length ? (
        <p className="rounded-xl border-2 border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-800">
          Memory is empty. Use <b>+ Next</b> or <b>Import all</b> to bring in the sample CRM, email, call and WhatsApp history.
        </p>
      ) : (
        <ol className="relative space-y-2 border-l border-slate-200 pl-4 dark:border-slate-800">
          {deal.sources.map(s => <SourceItem key={s.id} s={s} open={focus === s.id} toggle={() => setFocus(focus === s.id ? null : s.id)} />)}
        </ol>
      )}
    </Panel>
  )
}

function SourceItem({ s, open, toggle }: { s: Source; open: boolean; toggle: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const c = CHANNEL[s.channel] ?? CHANNEL.note
  useEffect(() => {
    if (!open || text !== null) return
    let live = true
    sourceText(s.id).then(r => { if (live) setText(r.text) }).catch(e => { if (live) setText(`Could not load: ${e.message}`) })
    return () => { live = false }
  }, [open, text, s.id])

  return (
    <li ref={el => { if (open) el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }}
      className={`relative rounded-lg p-2 transition ${open ? 'bg-indigo-50 ring-1 ring-indigo-300 dark:bg-indigo-950/40 dark:ring-indigo-800' : ''}`}>
      <span className="absolute -left-[21px] top-3 size-2.5 rounded-full bg-indigo-500" />
      <button type="button" onClick={toggle} className="w-full text-left">
        <div className="flex items-center gap-2 text-xs">
          <span className={`rounded px-1.5 py-0.5 font-medium ${c.cls}`}>{c.icon} {c.label}</span>
          <span className="font-mono text-slate-500">{s.id}</span>
          <span className="ml-auto text-slate-400">{s.date.slice(0, 10)}</span>
        </div>
        <div className="mt-1 text-sm font-medium">{s.title}</div>
        {s.memories != null && <div className="text-xs text-slate-400">{s.memories} facts extracted by Hindsight</div>}
      </button>
      {open && (
        <div className="mt-2 whitespace-pre-wrap rounded-md bg-white p-2 text-xs leading-relaxed text-slate-600 dark:bg-slate-950 dark:text-slate-300">
          {text ?? 'Loading from Hindsight…'}
        </div>
      )}
    </li>
  )
}

function AddSource({ onSaved }: { onSaved: () => Promise<void> }) {
  const [channel, setChannel] = useState<Channel>('email')
  const [title, setTitle] = useState('')
  const [people, setPeople] = useState('')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg('')
    try {
      const r = await addSource(channel, title, content, people)
      setMsg(`Stored in Hindsight as ${r.remembered}. Ask again to see it used.`)
      setTitle(''); setPeople(''); setContent(''); await onSaved()
    } catch (err) { setMsg((err as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Panel title="Add a conversation">
      <form className="space-y-2" onSubmit={save}>
        <div className="flex flex-wrap gap-1.5">
          {(['email', 'call', 'whatsapp', 'crm', 'note'] as Channel[]).map(ch => (
            <button key={ch} type="button" onClick={() => setChannel(ch)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${channel === ch ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
              {CHANNEL[ch].icon} {CHANNEL[ch].label}
            </button>
          ))}
        </div>
        <input className={input} required minLength={2} placeholder="Title, e.g. Priya: questionnaire approved" value={title} onChange={e => setTitle(e.target.value)} />
        <input className={input} placeholder="From / participants (optional)" value={people} onChange={e => setPeople(e.target.value)} />
        <textarea className={`${input} min-h-24`} required minLength={5} placeholder="Paste the email, call notes or WhatsApp message…"
          value={content} onChange={e => setContent(e.target.value)} />
        <button className={`${primary} w-full`} disabled={busy}>{busy ? 'Storing in Hindsight…' : 'Remember this conversation'}</button>
        {msg && <p className="text-sm text-slate-500">{msg}</p>}
      </form>
    </Panel>
  )
}

interface Msg { q: string; answer?: string; sources?: string[]; trace?: TraceStep[]; memory?: number; usedMemory: boolean; error?: string }

function Chat({ memoryCount, ready, onSource }: { memoryCount: number; ready: boolean; onSource: (id: string) => void }) {
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
      setMsgs(m => m.map((x, k) => k === m.length - 1 ? { ...x, answer: r.answer, sources: r.sources, trace: r.trace, memory: r.memory_count } : x))
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
            {ready ? `Ask about the deal. With ${memoryCount} documents in memory the agent answers from what the customer actually said.`
              : 'Import the deal first, then ask about it.'}
          </p>
        )}
        {msgs.map((m, k) => (
          <div key={k} className="space-y-2">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white">{m.q}</div>
            <div className="max-w-[95%] rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2 text-sm leading-relaxed dark:bg-slate-800">
              {m.error ? <span className="text-rose-600">{m.error}</span>
                : m.answer === undefined ? <span className="animate-pulse text-slate-400">{m.usedMemory ? 'Agent is recalling deal memory and thinking…' : 'Thinking without memory…'}</span>
                  : <>
                    <p className="whitespace-pre-wrap">{m.answer}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                      <span className={`rounded-full px-2 py-0.5 font-medium ${m.usedMemory ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'}`}>
                        {m.usedMemory ? `from ${m.memory} documents` : 'memory off'}
                      </span>
                      {!!m.sources?.length && <>sources <SourceChips ids={m.sources} onSource={onSource} /></>}
                    </div>
                    <MemoryTrace steps={m.trace ?? []} />
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

function CallPrepPanel({ onSource }: { onSource: (id: string) => void }) {
  const [goal, setGoal] = useState('')
  const [prep, setPrep] = useState<CallPrep | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  async function run(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try { setPrep(await prepareCall(goal)) } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function copyEmail() {
    if (!prep) return
    try { await navigator.clipboard.writeText(prep.follow_up_email); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { /* clipboard blocked: the text is still selectable */ }
  }

  const h = 'mb-1.5 mt-4 text-xs font-semibold uppercase tracking-wider text-slate-400'
  return (
    <Panel title="Call prep">
      <form className="flex gap-2" onSubmit={run}>
        <input className={input} placeholder="Goal for the call (optional), e.g. get the PO signed" value={goal} onChange={e => setGoal(e.target.value)} />
        <button className={`${primary} whitespace-nowrap`} disabled={busy}>{busy ? 'Preparing…' : 'Prepare my call'}</button>
      </form>
      {busy && <p className="mt-3 animate-pulse text-sm text-violet-600">Agent is recalling 4 angles from Hindsight and writing your plan…</p>}
      {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
      {prep && !busy && (
        <div className="text-sm leading-snug">
          <p className="mt-4 rounded-lg bg-indigo-50 p-3 font-medium text-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-200">{prep.summary}</p>

          {prep.risks.length > 0 && <>
            <h3 className={h}>Risks</h3>
            <ul className="space-y-1.5">{prep.risks.map((r, k) => (
              <li key={k} className="rounded-md border-l-2 border-rose-400 pl-2"><b>{r.text}</b> <span className="text-slate-500">{r.why_it_matters}</span> <SourceChips ids={r.sources} onSource={onSource} /></li>
            ))}</ul>
          </>}

          <h3 className={h}>Key insights</h3>
          <ul className="space-y-1.5">{prep.insights.map((r, k) => (
            <li key={k}><b>{r.text}</b> <span className="text-slate-500">{r.why_it_matters}</span> <SourceChips ids={r.sources} onSource={onSource} /></li>
          ))}</ul>

          <h3 className={h}>Stakeholder plays</h3>
          <ul className="space-y-1.5">{prep.stakeholders.map((s, k) => (
            <li key={k}><b>{s.name}</b> <span className="text-slate-500">({s.role}, cares about {s.cares_about})</span>: {s.how_to_win_them} <SourceChips ids={s.sources} onSource={onSource} /></li>
          ))}</ul>

          <h3 className={h}>Objection handling</h3>
          <ul className="space-y-2">{prep.objections.map((o, k) => (
            <li key={k}>
              <div><b>"{o.objection}"</b> <span className="text-slate-500">({o.raised_by})</span> <SourceChips ids={o.sources} onSource={onSource} /></div>
              <div className="mt-0.5 rounded-md bg-emerald-50 px-2 py-1 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">→ {o.response}</div>
            </li>
          ))}</ul>

          <h3 className={h}>Call script</h3>
          <ol className="space-y-1.5">{prep.call_script.map((l, k) => (
            <li key={k} className="flex gap-2">
              <span className="w-20 shrink-0 text-xs font-semibold uppercase text-violet-600 dark:text-violet-400">{l.stage}</span>
              <span>"{l.say}" <SourceChips ids={l.sources} onSource={onSource} /></span>
            </li>
          ))}</ol>

          <h3 className={h}>Next steps</h3>
          <ul className="list-disc space-y-0.5 pl-5">{prep.next_steps.map((n, k) => <li key={k}>{n}</li>)}</ul>

          <div className="mt-4 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Follow-up email · draft, review before sending</h3>
            <button type="button" className="text-xs text-indigo-600 hover:underline" onClick={copyEmail}>{copied ? 'Copied ✓' : 'Copy'}</button>
          </div>
          <p className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-2 text-xs dark:bg-slate-800/60">{prep.follow_up_email}</p>

          <MemoryTrace steps={prep.trace} />
          {prep.dropped > 0 && <p className="mt-1 text-[11px] text-slate-400">{prep.dropped} unsourced item{prep.dropped > 1 ? 's' : ''} removed by the evidence gate.</p>}
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
