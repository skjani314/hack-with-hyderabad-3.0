import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  ask, getCustomer, getProfile, getRequest, ingest, listInsights, listPromptPieces, listRequests, previewInteraction,
  sourceText, type Channel, type CustomerDetail, type IngestResult, type Insight, type Interaction, type Participant,
  type Preview, type Profile, type PromptPiece, type RequestOut, type RequestRow,
} from './api'
import LedgerPanel from './LedgerPanel'
import ReportView from './ReportView'
import { CHANNEL, ChannelTag, ErrorText, MemoryTrace, Panel, SourceChips, Tip, errMsg, ghost, input, pill, primary } from './ui'

/** yyyy-mm-dd of an ISO time in the viewer's timezone (what a date input shows). */
const localDay = (iso: string) => { const d = new Date(iso); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
/** Same local time of day, new date. */
const withDay = (iso: string, day: string) => { const d = new Date(iso); const [y, m, dd] = day.split('-').map(Number); d.setFullYear(y, m - 1, dd); return d.toISOString() }

export default function CustomerPage({ id }: { id: string }) {
  const [detail, setDetail] = useState<CustomerDetail | null>(null)
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)          // bumps when memory changes
  const [source, setSource] = useState<string | null>(null)
  const [lastRequest, setLastRequest] = useState<RequestOut | null>(null)

  const load = useCallback(() => getCustomer(id).then(d => { setDetail(d); setError('') }).catch(e => setError(errMsg(e))), [id])
  useEffect(() => { load() }, [load, version])

  if (error && !detail) return <ErrorText error={error} />
  if (!detail) return <p className="text-sm text-slate-500">Loading memory…</p>
  const c = detail.customer
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <a href="#/customers" className="text-xs text-slate-500 hover:underline">← Customers</a>
          <h1 className="text-2xl font-bold tracking-tight">{c.name}</h1>
          <p className="text-sm text-slate-500">{c.industry} · memory bank <span className="font-mono">{c.bank_id}</span> · {detail.interactions.length} interactions remembered</p>
        </div>
      </div>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Timeline rows={detail.interactions} open={source} onOpen={setSource} customerId={id} />
          <AddToMemory customerId={id} lastRequest={lastRequest} onSaved={() => setVersion(v => v + 1)} />
        </div>
        <Ask customerId={id} onSource={setSource} onReport={setLastRequest} empty={!detail.interactions.length} />
        <div className="flex min-w-0 flex-col gap-5">
          <LedgerPanel customerId={id} version={version} onSource={setSource} />
          <ProfilePanel customerId={id} version={version} empty={!detail.interactions.length} onSource={setSource} />
        </div>
      </div>
      {source && <SourceDrawer key={source} customerId={id} sourceId={source} onClose={() => setSource(null)} />}
    </div>
  )
}

// ---------- timeline ----------

function Timeline({ rows, open, onOpen, customerId }: { rows: CustomerDetail['interactions']; open: string | null; onOpen: (id: string) => void; customerId: string }) {
  return (
    <Panel title="Memory: interactions">
      {!rows.length ? (
        <p className="rounded-xl border-2 border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-800">
          Nothing remembered yet. Add a call, email, WhatsApp chat or file below.
        </p>
      ) : (
        <ol className="relative max-h-[420px] space-y-1 overflow-y-auto border-l border-slate-200 pl-4 dark:border-slate-800">
          {rows.map(s => (
            <li key={s.document_id} className={`relative rounded-lg p-2 ${open === s.document_id ? 'bg-indigo-50 ring-1 ring-indigo-300 dark:bg-indigo-950/40 dark:ring-indigo-800' : ''}`}>
              <span className="absolute -left-[21px] top-3.5 size-2.5 rounded-full bg-indigo-500" />
              <button type="button" className="w-full text-left" onClick={() => onOpen(s.document_id)} title={`Open ${s.document_id} (${customerId})`}>
                <div className="flex items-center gap-2 text-xs">
                  <ChannelTag channel={s.channel} />
                  <span className="font-mono text-slate-500">{s.document_id}</span>
                  <span className="ml-auto text-slate-400">{s.occurred_at.slice(0, 10)}</span>
                </div>
                <div className="mt-1 text-sm font-medium">{s.title}</div>
                {s.memories != null && <div className="text-xs text-slate-400">{s.memories} facts extracted by Hindsight</div>}
              </button>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}

function SourceDrawer({ customerId, sourceId, onClose }: { customerId: string; sourceId: string; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [insight, setInsight] = useState<Insight | null>(null)
  useEffect(() => {  // mounted with key={sourceId}, so each source starts from empty state
    let live = true
    if (sourceId.startsWith('INS-')) {
      listInsights().then(all => { if (live) { const i = all.find(x => x.id === sourceId); setInsight(i ?? null); if (!i) setText('Lesson not found.') } })
        .catch(e => live && setText(errMsg(e)))
    } else {
      sourceText(customerId, sourceId).then(r => live && setText(r.text)).catch(e => live && setText(errMsg(e)))
    }
    return () => { live = false }
  }, [customerId, sourceId])
  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto bg-white p-5 shadow-xl dark:bg-slate-900" onClick={e => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-mono text-sm font-semibold">{sourceId}</h2>
          <button className={ghost} onClick={onClose}>Close</button>
        </div>
        {insight ? (
          <div className="space-y-2 text-sm">
            <p className="text-xs uppercase tracking-wider text-amber-600">Company playbook lesson · {insight.kind.replace(/_/g, ' ')}</p>
            <p className="text-base">{insight.text}</p>
            <p className="text-xs text-slate-500">{insight.industry ?? 'any industry'}{insight.role ? ` · ${insight.role}` : ''} · {insight.evidence.replace(/_/g, ' ')}</p>
            <p className="text-xs text-slate-400">Learned from another customer; names are never stored in the playbook.</p>
          </div>
        ) : <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 dark:text-slate-300">{text ?? 'Loading from Hindsight…'}</pre>}
      </aside>
    </div>
  )
}

// ---------- add to memory: input → preview (editable) → remember ----------

const CHANNELS: Channel[] = ['call', 'email', 'whatsapp', 'crm', 'note', 'document', 'outcome']

function AddToMemory({ customerId, lastRequest, onSaved }: { customerId: string; lastRequest: RequestOut | null; onSaved: () => void }) {
  const [mode, setMode] = useState<'text' | 'file' | 'url'>('text')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [url, setUrl] = useState('')
  const [channel, setChannel] = useState<Channel | ''>('')
  const [title, setTitle] = useState('')
  const [day, setDay] = useState('')         // yyyy-mm-dd; empty = now
  const [time, setTime] = useState('10:00')
  const [people, setPeople] = useState<Participant[]>([])
  const [linkBrief, setLinkBrief] = useState(true)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [result, setResult] = useState<IngestResult | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function runPreview(e: FormEvent) {
    e.preventDefault()
    setBusy(mode === 'text' ? 'Reading…' : 'Transcribing / reading…'); setError(''); setResult(null)
    try {
      setPreview(await previewInteraction(customerId, {
        text: mode === 'text' ? text : undefined, file: mode === 'file' ? file ?? undefined : undefined,
        recordingUrl: mode === 'url' ? url : undefined, channel, title,
        occurredAt: day ? new Date(`${day}T${time || '10:00'}`).toISOString() : undefined, participants: people.filter(p => p.name.trim()),
      }))
    } catch (err) { setError(errMsg(err)) } finally { setBusy('') }
  }

  async function remember() {
    if (!preview) return
    setBusy('Extracting and storing in both memory banks…'); setError('')
    try {
      const job = await ingest(customerId, preview.interactions, linkBrief ? lastRequest?.request_id : null)
      setResult(job.result ?? null); setPreview(null); setText(''); setFile(null); setUrl(''); setTitle('')
      onSaved()
    } catch (err) { setError(errMsg(err)) } finally { setBusy('') }
  }

  const edit = (i: number, fn: (x: Interaction) => Interaction) =>
    setPreview(p => p && { ...p, interactions: p.interactions.map((x, k) => (k === i ? fn(x) : x)) })

  return (
    <Panel title="Add to memory">
      {!preview ? (
        <form className="space-y-2" onSubmit={runPreview}>
          <div className="flex gap-1.5">
            {([['text', 'Paste text', 'Paste a call transcript (Name: words), an email with its headers, a WhatsApp chat or notes.'],
              ['file', 'Upload file', 'Call audio (MP3), .eml email, WhatsApp "Export chat" .txt, CRM .csv, or PDF / DOCX / XLSX. Up to 4 MB.'],
              ['url', 'Recording URL', 'A link to a call recording (e.g. from MCube). Groq downloads and transcribes it, so long calls work.']] as const).map(([m, label, help]) => (
              <Tip key={m} text={help}><button type="button" className={pill(mode === m)} onClick={() => setMode(m)}>{label}</button></Tip>
            ))}
          </div>
          {mode === 'text' && <textarea className={`${input} min-h-28`} required minLength={5} value={text} onChange={e => setText(e.target.value)}
            placeholder="Paste a call transcript (Name: words), an email with its headers, a WhatsApp export, or notes…" />}
          {mode === 'file' && (
            <label className="block cursor-pointer rounded-xl border-2 border-dashed border-slate-200 p-5 text-center text-sm text-slate-500 hover:border-indigo-400 dark:border-slate-700"
              onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); setFile(e.dataTransfer.files[0] ?? null) }}>
              <input type="file" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)}
                accept=".mp3,.m4a,.wav,.ogg,.webm,.mp4,.eml,.txt,.csv,.pdf,.docx,.xlsx,.pptx,.md,.html" />
              {file ? <b>{file.name}</b> : <>Drop a file or click: call audio (MP3), .eml email, WhatsApp export .txt, CRM .csv, PDF / DOCX / XLSX</>}
              <div className="mt-1 text-xs text-slate-400">Up to 4 MB. For long call recordings use the recording URL.</div>
            </label>
          )}
          {mode === 'url' && <input className={input} type="url" required placeholder="https://… recording URL (e.g. from MCube)" value={url} onChange={e => setUrl(e.target.value)} />}
          <Tip className="w-full" text="What kind of interaction this is. Leave on automatic and it is detected from the file or text; you can still change it." wide>
            <select className={input} value={channel} onChange={e => setChannel(e.target.value as Channel | '')}>
              <option value="">Type: detect automatically</option>
              {CHANNELS.map(c => <option key={c} value={c}>{CHANNEL[c].label}</option>)}
            </select>
          </Tip>
          <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-700">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-medium text-slate-600 dark:text-slate-300">Happened on</span>
              <span className={day ? 'font-semibold text-indigo-600 dark:text-indigo-400' : 'text-amber-600'}>
                {day ? new Date(`${day}T${time || '10:00'}`).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
                  : 'now (set a date for a past call)'}
              </span>
            </div>
            <div className="flex gap-2">
              <Tip className="flex-1" text="The day the call, email or chat happened. Briefs trust the newest interaction, so a wrong date changes the advice." wide>
                <input className={input} type="date" value={day} onChange={e => setDay(e.target.value)} max={new Date().toISOString().slice(0, 10)} />
              </Tip>
              <Tip text="Time of day (optional)."><input className={`${input} w-28`} type="time" value={time} onChange={e => setTime(e.target.value)} /></Tip>
              {day && <button type="button" className="text-xs text-slate-400 hover:text-rose-600" onClick={() => setDay('')}>clear</button>}
            </div>
          </div>
          <input className={input} placeholder="Title (optional), e.g. Pricing call with finance" value={title} onChange={e => setTitle(e.target.value)} />
          <People people={people} setPeople={setPeople} />
          <Tip className="w-full" text="Reads the input (and transcribes audio) and shows what will be remembered, so you can fix speakers, names and the date. Nothing is saved yet." wide>
            <button className={`${primary} w-full`} disabled={!!busy}>{busy || 'Preview'}</button>
          </Tip>
        </form>
      ) : (
        <div className="space-y-3">
          {preview.warnings.map(w => <p key={w} className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">{w}</p>)}
          {preview.unknown_names.length > 0 && <p className="text-xs text-slate-500">New names: {preview.unknown_names.join(', ')}. Set their side below if needed.</p>}
          {preview.interactions.map((it, i) => (
            <div key={it.document_id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div className="mb-2 flex items-center gap-2 text-xs">
                <ChannelTag channel={it.channel} /><span className="font-mono">{it.document_id}</span>
                {it.mode === 'append' && <span className="text-slate-400">(adds to existing)</span>}
                <Tip className="ml-auto" text="When this happened. Check it: briefs treat the newest interaction as the current state." wide>
                  <input type="date" value={localDay(it.occurred_at)} max={localDay(new Date().toISOString())}
                    onChange={e => e.target.value && edit(i, x => ({ ...x, occurred_at: withDay(x.occurred_at, e.target.value) }))}
                    className={`rounded border px-1 ${localDay(it.occurred_at) === localDay(new Date().toISOString()) && it.channel !== 'whatsapp'
                      ? 'border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200' : 'border-slate-200 dark:border-slate-700 dark:bg-slate-900'}`} />
                </Tip>
              </div>
              {localDay(it.occurred_at) === localDay(new Date().toISOString()) && it.channel !== 'whatsapp' &&
                <p className="mb-2 text-[11px] text-amber-700 dark:text-amber-300">Dated today. If this happened earlier, change the date.</p>}
              <input className={`${input} mb-2`} value={it.title} onChange={e => edit(i, x => ({ ...x, title: e.target.value }))} />
              {it.turns?.length ? (
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {it.turns.map((t, k) => (
                    <div key={k} className="flex gap-1.5 text-xs">
                      <input className="w-24 shrink-0 rounded border border-slate-200 px-1 dark:border-slate-700 dark:bg-slate-900" value={t.speaker}
                        onChange={e => edit(i, x => ({ ...x, turns: x.turns!.map((y, j) => j === k ? { ...y, speaker: e.target.value, speaker_inferred: false } : y) }))} />
                      <select className="shrink-0 rounded border border-slate-200 dark:border-slate-700 dark:bg-slate-900" value={t.side}
                        onChange={e => edit(i, x => ({ ...x, turns: x.turns!.map((y, j) => j === k ? { ...y, side: e.target.value as typeof t.side, speaker_inferred: false } : y) }))}>
                        <option value="ours">ours</option><option value="customer">customer</option><option value="unknown">?</option>
                      </select>
                      <span className={`min-w-0 flex-1 ${t.speaker_inferred ? 'text-slate-500' : ''}`}>{t.text}</span>
                    </div>
                  ))}
                </div>
              ) : <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-sans text-xs dark:bg-slate-800/60">{it.text.slice(0, 3000)}</pre>}
            </div>
          ))}
          {lastRequest && (
            <Tip text="Links this interaction to the brief you asked for. The agent compares its advice with what actually happened and saves 'what worked' or 'what failed' to the company playbook." wide>
              <label className="flex items-center gap-2 text-xs text-slate-500">
                <input type="checkbox" checked={linkBrief} onChange={e => setLinkBrief(e.target.checked)} />
                This follows the brief "{lastRequest.prompt.slice(0, 50)}". Compare advice with what happened (the playbook learns).
              </label>
            </Tip>
          )}
          <div className="flex gap-2">
            <Tip text="Go back and change the input. Nothing has been saved."><button className={ghost} onClick={() => setPreview(null)} disabled={!!busy}>Back</button></Tip>
            <Tip className="flex-1" text="Saves it: the text goes to this customer's memory bank, and reusable lessons (with names removed) go to the company playbook." wide>
              <button className={`${primary} w-full`} onClick={remember} disabled={!!busy}>{busy || `Remember ${preview.interactions.length > 1 ? `${preview.interactions.length} items` : 'this'}`}</button>
            </Tip>
          </div>
        </div>
      )}
      <div className="mt-2"><ErrorText error={error} /></div>
      {result && (
        <div className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm dark:bg-emerald-950/40">
          <p className="font-medium text-emerald-800 dark:text-emerald-200">
            Remembered {result.remembered.join(', ')} · {result.company_insights.length} lesson{result.company_insights.length === 1 ? '' : 's'} added to the company playbook
            {result.rejected_insights > 0 && ` · ${result.rejected_insights} withheld because they named the customer`}
          </p>
          {result.summary && <p className="mt-1 text-emerald-900/80 dark:text-emerald-100/80">{result.summary}</p>}
          {!result.extraction_ok && <p className="mt-1 text-amber-700">The text was stored, but extraction failed; ask again later.</p>}
          <MemoryTrace steps={result.trace} />
        </div>
      )}
    </Panel>
  )
}

function People({ people, setPeople }: { people: Participant[]; setPeople: (p: Participant[]) => void }) {
  const set = (i: number, patch: Partial<Participant>) => setPeople(people.map((p, k) => (k === i ? { ...p, ...patch } : p)))
  return (
    <div className="space-y-1">
      {people.map((p, i) => (
        <div key={i} className="flex gap-1.5">
          <input className={input} placeholder="Name" value={p.name} onChange={e => set(i, { name: e.target.value })} />
          <input className={input} placeholder="Role" value={p.role ?? ''} onChange={e => set(i, { role: e.target.value })} />
          <select className={`${input} w-28`} value={p.side} onChange={e => set(i, { side: e.target.value as Participant['side'] })}>
            <option value="customer">customer</option><option value="ours">ours</option>
          </select>
          <button type="button" className="px-2 text-slate-400 hover:text-rose-600" onClick={() => setPeople(people.filter((_, k) => k !== i))}>×</button>
        </div>
      ))}
      <button type="button" className="text-xs text-indigo-600 hover:underline" onClick={() => setPeople([...people, { name: '', role: '', side: 'customer' }])}>
        + Add participant (helps label who said what)
      </button>
    </div>
  )
}

// ---------- ask: main prompt + chosen pieces + the executive's request ----------

const SUGGESTED = [
  'I have a call with them tomorrow. What should I focus on?',
  'What objections are still open, and how do I answer them?',
  'Who are the stakeholders and how do I win each one?',
  'Draft my follow-up email.',
]

function Ask({ customerId, onSource, onReport, empty }: { customerId: string; onSource: (id: string) => void; onReport: (r: RequestOut) => void; empty: boolean }) {
  const [pieces, setPieces] = useState<PromptPiece[]>([])
  const [picked, setPicked] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [current, setCurrent] = useState<RequestOut | null>(null)
  const [history, setHistory] = useState<RequestRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { listPromptPieces().then(setPieces).catch(() => setPieces([])) }, [])
  const loadHistory = useCallback(() => listRequests(customerId).then(setHistory).catch(() => {}), [customerId])
  useEffect(() => { loadHistory() }, [loadHistory])

  function toggle(p: PromptPiece) {
    setPicked(cur => cur.includes(p.id) ? cur.filter(x => x !== p.id)
      : p.group === 'call_type' ? [...cur.filter(x => pieces.find(y => y.id === x)?.group !== 'call_type'), p.id] : [...cur, p.id])
  }

  async function send(text: string, followUp = false, e?: FormEvent) {
    e?.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true); setError('')
    try {
      const r = await ask(customerId, text, picked, followUp ? current?.request_id : null)
      setCurrent(r); onReport(r); setPrompt(''); loadHistory()
    } catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }

  async function open(rid: string) {
    try { const r = await getRequest(customerId, rid); setCurrent(r); onReport(r) } catch (err) { setError(errMsg(err)) }
  }

  const group = (g: string) => pieces.filter(p => p.group === g)
  return (
    <Panel title="Ask the agent">
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-500">Kind of call <span className="font-normal text-slate-400">(pick one)</span></div>
        <div className="flex flex-wrap gap-1.5">{group('call_type').map(p => (
          <Tip key={p.id} text={`Adds to the prompt: ${p.text}`} wide><button type="button" className={pill(picked.includes(p.id))} onClick={() => toggle(p)}>{p.label}</button></Tip>
        ))}</div>
        <div className="text-xs font-medium text-slate-500">Focus on <span className="font-normal text-slate-400">(any)</span></div>
        <div className="flex flex-wrap gap-1.5">{group('focus').map(p => (
          <Tip key={p.id} text={`Adds to the prompt: ${p.text}`} wide><button type="button" className={pill(picked.includes(p.id))} onClick={() => toggle(p)}>{p.label}</button></Tip>
        ))}</div>
      </div>
      <form className="mt-3 space-y-2" onSubmit={e => send(prompt, false, e)}>
        <textarea className={`${input} min-h-20`} placeholder="Your question or situation, e.g. I'm calling their CFO tomorrow about the renewal. What should I ask?"
          value={prompt} onChange={e => setPrompt(e.target.value)} />
        <div className="flex flex-wrap gap-2">
          <Tip text="Starts fresh: the agent reads this customer's memory and the company playbook and answers only your question with the chips you picked." wide>
            <button className={primary} disabled={busy || !prompt.trim()}>{busy ? 'Recalling both memories and writing…' : 'Get my brief'}</button>
          </Tip>
          {current && (
            <Tip text="Continues from the brief on screen: the agent also sees your previous question and its answer, so 'that', 'those' or 'why?' make sense. Memory is still read fresh." wide>
              <button type="button" className={ghost} disabled={busy || !prompt.trim()} onClick={() => send(prompt, true)}>Ask as follow-up</button>
            </Tip>
          )}
        </div>
      </form>
      {!current && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {SUGGESTED.map(s => (
            <Tip key={s} text="Ask this now, with the chips you picked."><button type="button" disabled={busy} onClick={() => send(s)}
              className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 dark:bg-indigo-950/50 dark:text-indigo-300">{s}</button></Tip>
          ))}
        </div>
      )}
      {empty && !current && <p className="mt-3 text-xs text-slate-400">No customer memory yet: the brief will come from the company playbook only.</p>}
      <div className="mt-3"><ErrorText error={error} /></div>
      {current && <ReportView key={current.request_id} request={current} pieces={pieces} onSource={onSource} />}
      {history.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-xs font-medium text-slate-500">Earlier briefs ({history.length})</summary>
          <ul className="mt-2 space-y-1">
            {history.map(h => (
              <li key={h.request_id}>
                <button type="button" className="w-full rounded-md px-2 py-1 text-left hover:bg-slate-50 dark:hover:bg-slate-800" onClick={() => open(h.request_id)}>
                  <span className="text-xs text-slate-400">{new Date(h.created_at).toLocaleString()}</span> · {h.prompt}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  )
}

// ---------- profile ----------

/** Loads once, then only when asked: refreshing right after an upload cost an LLM call that collided with the
 *  next brief on Groq's per-minute limit. */
function ProfilePanel({ customerId, version, empty, onSource }: { customerId: string; version: number; empty: boolean; onSource: (id: string) => void }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [asked, setAsked] = useState(version)            // memory version the shown profile was requested for
  const [state, setState] = useState<{ v: number; error: string } | null>(null)
  useEffect(() => {
    if (empty) return
    let live = true
    getProfile(customerId).then(p => { if (live) { setProfile(p); setState({ v: asked, error: '' }) } })
      .catch(e => live && setState({ v: asked, error: errMsg(e) }))
    return () => { live = false }
  }, [customerId, asked, empty])
  const busy = !empty && state?.v !== asked
  const stale = !empty && !busy && version !== asked
  const sections: [keyof Profile, string][] = [['pain_points', 'Pain points'], ['goals', 'Goals'], ['stakeholders', 'Stakeholders'],
    ['objections', 'Objections'], ['competitors', 'Competitors'], ['requirements', 'Requirements'], ['commitments', 'Commitments'], ['pricing', 'Pricing']]
  return (
    <Panel title="What memory knows" action={busy ? <span className="animate-pulse text-xs text-indigo-500">updating…</span>
      : stale ? <Tip text="New interactions were remembered since this profile was built. Refresh to rebuild it (one LLM call)." below>
        <button className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-200 dark:bg-amber-950 dark:text-amber-200" onClick={() => setAsked(version)}>Memory changed · Refresh</button>
      </Tip> : null}>
      {state?.error && <ErrorText error={state.error} />}
      {empty ? <p className="text-sm text-slate-400">Nothing remembered yet.</p> : !profile ? <p className="text-sm text-slate-400">Reading memory…</p> : (
        <div className="space-y-4">
          {sections.map(([key, label]) => {
            const items = profile[key] as Profile['pain_points']
            return items.length > 0 && (
              <div key={key}>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</h3>
                <ul className="space-y-1.5">{items.map((it, k) => (
                  <li key={k} className="text-sm leading-snug">{it.text}{it.detail && <span className="text-slate-500"> ({it.detail})</span>} <SourceChips ids={it.sources} onSource={onSource} /></li>
                ))}</ul>
              </div>
            )
          })}
          <p className="border-t border-slate-200 pt-3 text-xs text-slate-400 dark:border-slate-800">
            Every item links to the message it came from.{profile.dropped > 0 && ` ${profile.dropped} unsourced item${profile.dropped > 1 ? 's were' : ' was'} removed.`}
          </p>
        </div>
      )}
    </Panel>
  )
}
