import { useState, type ReactNode } from 'react'
import type { PromptPiece, Report, RequestOut } from './api'
import { MemoryTrace, SourceChips, Tip } from './ui'

type OnSource = (id: string) => void
const h = 'mb-2 mt-5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400'

function Section({ title, help, show, children }: { title: string; help: string; show: boolean; children: ReactNode }) {
  if (!show) return null
  return (
    <>
      <h3 className={h}>{title}<Tip text={help} wide><span className="cursor-help rounded-full border border-slate-300 px-1.5 text-[10px] dark:border-slate-600">?</span></Tip></h3>
      {children}
    </>
  )
}

// ---------- deal pulse: health + stage ----------

const HEALTH = {
  on_track: { label: 'On track', cls: 'bg-emerald-500', ring: 'border-emerald-300 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/30' },
  at_risk: { label: 'At risk', cls: 'bg-amber-500', ring: 'border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30' },
  off_track: { label: 'Off track', cls: 'bg-rose-500', ring: 'border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/30' },
}
const STAGES: Report['deal_stage'][] = ['discovery', 'evaluation', 'negotiation', 'closing', 'won']

function DealPulse({ r }: { r: Report }) {
  const health = HEALTH[r.deal_health]
  const at = STAGES.indexOf(r.deal_stage)
  return (
    <div className={`rounded-xl border p-3 ${health.ring}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Tip text="The agent's read of the deal from memory: on track, at risk (something open could slip) or off track.">
          <span className="inline-flex cursor-help items-center gap-1.5 text-sm font-semibold">
            <span className={`size-2.5 rounded-full ${health.cls}`} />{health.label}
          </span>
        </Tip>
        <span className="text-sm text-slate-600 dark:text-slate-300">{r.health_reason}</span>
      </div>
      <Tip text="Where the deal stands, inferred from the latest interactions." wide>
        <ol className="mt-3 flex w-full cursor-help items-center">
          {(r.deal_stage === 'lost' ? [...STAGES.slice(0, 4), 'lost' as const] : STAGES).map((s, i) => {
            const done = r.deal_stage === 'lost' ? i < 4 : i < at
            const now = s === r.deal_stage
            return (
              <li key={s} className="flex flex-1 items-center last:flex-none">
                <div className="flex flex-col items-center gap-1">
                  <span className={`flex size-6 items-center justify-center rounded-full text-[10px] font-bold ${now
                    ? (s === 'lost' ? 'bg-rose-600 text-white' : 'bg-indigo-600 text-white ring-4 ring-indigo-200 dark:ring-indigo-900')
                    : done ? 'bg-indigo-300 text-white dark:bg-indigo-800' : 'bg-slate-200 text-slate-500 dark:bg-slate-700'}`}>{i + 1}</span>
                  <span className={`text-[10px] capitalize ${now ? 'font-semibold text-slate-900 dark:text-white' : 'text-slate-400'}`}>{s}</span>
                </div>
                {i < 4 && <span className={`mx-1 mb-4 h-0.5 flex-1 ${done ? 'bg-indigo-300 dark:bg-indigo-800' : 'bg-slate-200 dark:bg-slate-700'}`} />}
              </li>
            )
          })}
        </ol>
      </Tip>
    </div>
  )
}

function MemoryBar({ r }: { r: Report }) {
  const c = r.memory_used?.customer_facts ?? 0, l = r.memory_used?.company_lessons ?? 0
  const total = Math.max(c + l, 1)
  return (
    <Tip text="How much of each memory this brief was built from: facts about this customer (their Hindsight bank) and lessons from other customers (the company playbook bank)." wide>
      <div className="mt-3 w-full cursor-help">
        <div className="flex h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <span className="bg-indigo-500" style={{ width: `${(c / total) * 100}%` }} />
          <span className="bg-amber-400" style={{ width: `${(l / total) * 100}%` }} />
        </div>
        <div className="mt-1 flex gap-3 text-[11px] text-slate-500">
          <span><span className="mr-1 inline-block size-2 rounded-full bg-indigo-500" />{c} customer facts</span>
          <span><span className="mr-1 inline-block size-2 rounded-full bg-amber-400" />{l} playbook lessons</span>
          {!!r.memory_used?.latest && <span>· newest {r.memory_used.latest} interactions read first</span>}
        </div>
      </div>
    </Tip>
  )
}

// ---------- open items as a due-date timeline ----------

function relative(due: string | null | undefined) {
  if (!due) return ''
  const d = new Date(`${due}T12:00:00`)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.round((d.getTime() - Date.now()) / 86_400_000)
  return days === 0 ? 'today' : days > 0 ? `in ${days} day${days === 1 ? '' : 's'}` : `${-days} day${days === -1 ? '' : 's'} ago`
}

function OpenItems({ items, onSource }: { items: Report['open_items']; onSource: OnSource }) {
  const sorted = [...items].sort((a, b) => (a.due ?? '9999').localeCompare(b.due ?? '9999'))
  const dot = { open: 'bg-indigo-500', at_risk: 'bg-amber-500', overdue: 'bg-rose-500' }
  return (
    <ol className="relative space-y-3 border-l-2 border-slate-200 pl-5 dark:border-slate-700">
      {sorted.map((o, k) => (
        <li key={k} className="relative">
          <span className={`absolute -left-[27px] top-1 size-3 rounded-full ring-4 ring-white dark:ring-slate-900 ${dot[o.status]}`} />
          <div className="flex flex-wrap items-baseline gap-2 text-xs">
            <span className="font-semibold">{o.due ? new Date(`${o.due}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : 'No date'}</span>
            {o.due && <span className="text-slate-400">{relative(o.due)}</span>}
            {o.status !== 'open' && <span className={`rounded px-1.5 font-medium text-white ${dot[o.status]}`}>{o.status.replace('_', ' ')}</span>}
            {o.owner && <span className="rounded-full bg-slate-100 px-2 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{o.owner}</span>}
          </div>
          <div className="mt-0.5 text-sm">{o.text} <SourceChips ids={o.sources} onSource={onSource} /></div>
        </li>
      ))}
    </ol>
  )
}

// ---------- stakeholder map ----------

const STANCES = [
  { key: 'blocker', label: 'Blocker', cls: 'border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/30' },
  { key: 'skeptic', label: 'Skeptic', cls: 'border-orange-300 bg-orange-50 dark:border-orange-900 dark:bg-orange-950/30' },
  { key: 'neutral', label: 'Neutral', cls: 'border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/40' },
  { key: 'supporter', label: 'Supporter', cls: 'border-sky-300 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/30' },
  { key: 'champion', label: 'Champion', cls: 'border-emerald-300 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/30' },
] as const

function StakeholderMap({ people, onSource }: { people: Report['stakeholders']; onSource: OnSource }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-slate-400"><span>← against</span><span>for →</span></div>
      <div className="grid grid-cols-5 gap-1.5">
        {STANCES.map(s => (
          <div key={s.key} className={`min-h-20 rounded-lg border border-dashed p-1.5 ${s.cls}`}>
            <div className="mb-1 text-center text-[10px] font-semibold uppercase text-slate-500">{s.label}</div>
            <div className="space-y-1.5">
              {people.filter(p => p.stance === s.key).map((p, k) => (
                <Tip key={k} text={`Cares about: ${p.cares_about}. How to win: ${p.how_to_win}`} wide>
                  <div className="w-full cursor-help rounded-md bg-white p-1.5 text-xs shadow-sm dark:bg-slate-900">
                    <div className="font-semibold leading-tight">{p.name}</div>
                    {p.role && <div className="text-[10px] leading-tight text-slate-500">{p.role}</div>}
                  </div>
                </Tip>
              ))}
            </div>
          </div>
        ))}
      </div>
      <ul className="mt-3 space-y-1.5 text-sm">
        {people.map((p, k) => (
          <li key={k}><b>{p.name}</b> → <span className="text-emerald-700 dark:text-emerald-400">{p.how_to_win}</span> <SourceChips ids={p.sources} onSource={onSource} /></li>
        ))}
      </ul>
    </div>
  )
}

// ---------- objection → response flow ----------

function Objections({ items, onSource }: { items: Report['objections']; onSource: OnSource }) {
  return (
    <div className="space-y-2">
      {items.map((o, k) => (
        <div key={k} className="grid items-stretch gap-2 sm:grid-cols-[1fr_auto_1fr]">
          <div className="rounded-lg border border-slate-200 p-2 text-sm dark:border-slate-700">
            <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className={`rounded px-1.5 font-medium ${o.status === 'resolved' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'}`}>{o.status}</span>
              {o.raised_by && <span className="text-slate-500">{o.raised_by}</span>}
            </div>
            “{o.objection}” <SourceChips ids={o.sources} onSource={onSource} />
          </div>
          <div className="hidden items-center text-lg text-slate-400 sm:flex">→</div>
          <div className="rounded-lg bg-emerald-50 p-2 text-sm text-emerald-950 dark:bg-emerald-950/40 dark:text-emerald-100">{o.response}</div>
        </div>
      ))}
    </div>
  )
}

// ---------- call plan flowchart ----------

const PLAN: [keyof Report['call_plan'], string][] = [['opening', 'Open'], ['recap', 'Recap'], ['discovery', 'Discover'],
  ['value', 'Value'], ['objections', 'Objections'], ['close', 'Close']]

function CallPlan({ plan, onSource }: { plan: Report['call_plan']; onSource: OnSource }) {
  const [open, setOpen] = useState<number>(0)
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1">
        {PLAN.map(([key, label], i) => (
          <div key={key} className="flex items-center gap-1">
            <Tip text={plan[key].say}>
              <button type="button" onClick={() => setOpen(i)}
                className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${open === i ? 'bg-violet-600 text-white' : 'bg-violet-50 text-violet-700 hover:bg-violet-100 dark:bg-violet-950/50 dark:text-violet-300'}`}>
                {i + 1}. {label}
              </button>
            </Tip>
            {i < PLAN.length - 1 && <span className="text-slate-300 dark:text-slate-600">→</span>}
          </div>
        ))}
      </div>
      <div className="mt-2 rounded-lg border-l-4 border-violet-400 bg-violet-50/60 p-3 text-sm dark:bg-violet-950/20">
        <div className="mb-1 text-[11px] font-semibold uppercase text-violet-600 dark:text-violet-300">Step {open + 1} · {PLAN[open][1]}</div>
        “{plan[PLAN[open][0]].say}” <SourceChips ids={plan[PLAN[open][0]].sources} onSource={onSource} />
      </div>
    </div>
  )
}

// ---------- the report ----------

export default function ReportView({ request, pieces, onSource }: { request: RequestOut; pieces: PromptPiece[]; onSource: OnSource }) {
  const r = request.report
  const [copied, setCopied] = useState(false)
  const label = (id: string) => pieces.find(p => p.id === id)?.label ?? id

  async function copy() {
    try { await navigator.clipboard.writeText(r.follow_up_email); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { /* clipboard blocked: the text is still selectable */ }
  }

  return (
    <div className="mt-4 border-t border-slate-200 pt-4 text-sm leading-snug dark:border-slate-800">
      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
        <span className="font-medium">“{request.prompt}”</span>
        {(r.pieces ?? []).map(p => <span key={p} className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{label(p)}</span>)}
        <span className="ml-auto">{new Date(request.created_at).toLocaleString()}</span>
      </div>
      <DealPulse r={r} />
      <p className="mt-3 rounded-lg bg-indigo-50 p-3 text-indigo-950 dark:bg-indigo-950/40 dark:text-indigo-100">{r.answer}</p>
      <MemoryBar r={r} />

      <Section title="Open items" help="Everything still owed, by whom and by when, sorted by due date. Each links to the message it comes from." show={r.open_items.length > 0}>
        <OpenItems items={r.open_items} onSource={onSource} />
      </Section>
      <Section title="Stakeholder map" help="Each person placed by where they stand on the deal. Hover a name for what they care about and how to win them." show={r.stakeholders.length > 0}>
        <StakeholderMap people={r.stakeholders} onSource={onSource} />
      </Section>
      <Section title="Objections → what to say" help="Every objection raised so far, whether it is still open, and a suggested reply." show={r.objections.length > 0}>
        <Objections items={r.objections} onSource={onSource} />
      </Section>
      <Section title="Call plan" help="Your next call in six steps. Click a step (or hover it) to see what to say." show={true}>
        <CallPlan plan={r.call_plan} onSource={onSource} />
      </Section>
      <Section title="What to ask" help="Questions that move the deal forward, based on what is still unknown or open." show={r.what_to_ask.length > 0}>
        <ol className="grid gap-2 sm:grid-cols-2">{r.what_to_ask.map((x, k) => (
          <li key={k} className="flex gap-2 rounded-lg border border-slate-200 p-2 dark:border-slate-700">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[10px] font-bold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">{k + 1}</span>
            <span>{x.text} <SourceChips ids={x.sources} onSource={onSource} /></span>
          </li>
        ))}</ol>
      </Section>
      <Section title="Risks" help="What could lose or delay the deal." show={r.risks.length > 0}>
        <ul className="space-y-1.5">{r.risks.map((x, k) => <li key={k} className="rounded-md border-l-4 border-rose-400 bg-rose-50/50 px-2 py-1 dark:bg-rose-950/20">{x.text} <SourceChips ids={x.sources} onSource={onSource} /></li>)}</ul>
      </Section>
      <Section title="From the company playbook" help="Lessons learned with other customers (names removed) that apply here. Amber ids open the lesson." show={r.playbook_tips.length > 0}>
        <ul className="grid gap-2 sm:grid-cols-2">{r.playbook_tips.map((x, k) => (
          <li key={k} className="rounded-lg border border-amber-200 bg-amber-50/60 p-2 dark:border-amber-900 dark:bg-amber-950/20">💡 {x.text} <SourceChips ids={x.sources} onSource={onSource} /></li>
        ))}</ul>
      </Section>
      <Section title="Next steps" help="Concrete actions for you after reading this brief." show={r.next_steps.length > 0}>
        <ul className="space-y-1">{r.next_steps.map((n, k) => <li key={k} className="flex gap-2"><span className="text-slate-400">☐</span>{n}</li>)}</ul>
      </Section>
      {r.follow_up_email && (
        <details className="mt-5 rounded-lg border border-slate-200 dark:border-slate-700">
          <summary className="flex cursor-pointer items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Follow-up email draft
            <Tip text="Copy the draft to your clipboard. Review it before sending."><button type="button" className="text-xs normal-case text-indigo-600 hover:underline" onClick={e => { e.preventDefault(); copy() }}>{copied ? 'Copied ✓' : 'Copy'}</button></Tip>
          </summary>
          <p className="whitespace-pre-wrap px-3 pb-3 text-xs">{r.follow_up_email}</p>
        </details>
      )}
      <MemoryTrace steps={r.trace} />
      {r.dropped > 0 && <p className="mt-1 text-[11px] text-slate-400">{r.dropped} unsourced item{r.dropped > 1 ? 's' : ''} removed by the evidence gate.</p>}
    </div>
  )
}
