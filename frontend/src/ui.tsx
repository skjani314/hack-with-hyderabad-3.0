import type { ReactNode } from 'react'
import type { Channel, TraceStep } from './api'

export const card = 'rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900/60'
export const input = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900'
const btn = 'rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-wait disabled:opacity-50'
export const primary = `${btn} bg-indigo-600 text-white shadow-sm hover:bg-indigo-500`
export const ghost = `${btn} border border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800`
export const pill = (on: boolean) => `rounded-full px-3 py-1 text-xs font-medium transition ${on
  ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'}`

export const CHANNEL: Record<Channel, { label: string; cls: string; icon: string }> = {
  crm: { label: 'CRM', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300', icon: '▦' },
  email: { label: 'Email', cls: 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300', icon: '✉' },
  call: { label: 'Call', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300', icon: '☎' },
  whatsapp: { label: 'WhatsApp', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300', icon: '◉' },
  outcome: { label: 'Outcome', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300', icon: '★' },
  note: { label: 'Note', cls: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300', icon: '✎' },
  document: { label: 'File', cls: 'bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300', icon: '▤' },
}

export function ChannelTag({ channel }: { channel: string }) {
  const c = CHANNEL[channel as Channel] ?? CHANNEL.note
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${c.cls}`}>{c.icon} {c.label}</span>
}

export function Panel({ title, action, children, className = '' }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`${card} min-w-0 p-5 ${className}`}>
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

/** Source ids as clickable chips. INS-… are company playbook lessons, everything else is a customer document. */
export function SourceChips({ ids, onSource }: { ids: string[]; onSource: (id: string) => void }) {
  if (!ids.length) return null
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {ids.map(id => (
        <button key={id} type="button" onClick={() => onSource(id)} title={id.startsWith('INS-') ? 'Company playbook lesson' : 'Customer source'}
          className={`rounded px-1.5 py-0.5 font-mono text-[11px] transition ${id.startsWith('INS-')
            ? 'bg-amber-50 text-amber-700 hover:bg-amber-100 dark:bg-amber-950/50 dark:text-amber-300'
            : 'bg-slate-100 text-slate-600 hover:bg-indigo-100 hover:text-indigo-700 dark:bg-slate-800 dark:text-slate-300'}`}>
          {id}
        </button>
      ))}
    </span>
  )
}

const STEP_LABEL: Record<string, string> = {
  list_sources: 'Listed conversations', recall: 'Recalled from Hindsight', retain: 'Stored in Hindsight',
  extract: 'Extracted with Groq', transcribe: 'Transcribed audio', label_speakers: 'Labelled speakers',
  write_report: 'Wrote the report',
}

export function MemoryTrace({ steps }: { steps: TraceStep[] }) {
  if (!steps.length) return null
  return (
    <details className="mt-3 text-[11px] text-slate-500">
      <summary className="cursor-pointer select-none font-medium text-violet-600 dark:text-violet-400">
        Agent memory work · {steps.length} steps
      </summary>
      <ol className="mt-1 space-y-0.5 border-l-2 border-violet-200 pl-2 dark:border-violet-900">
        {steps.map((s, k) => (
          <li key={k}><b>{STEP_LABEL[s.step] ?? s.step}</b>{s.detail && <>: <i>{s.detail}</i></>}{s.result && <span className="text-slate-400"> → {s.result}</span>}</li>
        ))}
      </ol>
    </details>
  )
}

/** Hover (or keyboard focus) help: says what a control does before it is clicked. */
export function Tip({ text, children, wide = false, below = false, className = '' }: { text: string; children: ReactNode; wide?: boolean; below?: boolean; className?: string }) {
  return (
    <span className={`group/tip relative inline-flex ${className}`}>
      {children}
      <span role="tooltip"
        className={`pointer-events-none absolute left-1/2 z-40 -translate-x-1/2 rounded-lg bg-slate-900 px-2.5 py-1.5 text-left text-xs font-normal normal-case leading-snug tracking-normal text-white opacity-0 shadow-lg transition-opacity delay-300 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100 dark:bg-slate-100 dark:text-slate-900 ${wide ? 'w-72' : 'w-56'} ${below ? 'top-full mt-2' : 'bottom-full mb-2'}`}>
        {text}
      </span>
    </span>
  )
}

export function ErrorText({ error }: { error: string }) {
  return error ? <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p> : null
}

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))
