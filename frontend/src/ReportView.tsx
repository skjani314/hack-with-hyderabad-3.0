import { useState, type ReactNode } from 'react'
import type { PromptPiece, RequestOut } from './api'
import { MemoryTrace, SourceChips } from './ui'

const h = 'mb-1.5 mt-4 text-xs font-semibold uppercase tracking-wider text-slate-400'

function Section({ title, show, children }: { title: string; show: boolean; children: ReactNode }) {
  return show ? <><h3 className={h}>{title}</h3>{children}</> : null
}

export default function ReportView({ request, pieces, onSource }: { request: RequestOut; pieces: PromptPiece[]; onSource: (id: string) => void }) {
  const r = request.report
  const [copied, setCopied] = useState(false)
  const label = (id: string) => pieces.find(p => p.id === id)?.label ?? id

  async function copy() {
    try { await navigator.clipboard.writeText(r.follow_up_email); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { /* clipboard blocked: the text is still selectable */ }
  }

  return (
    <div className="mt-4 border-t border-slate-200 pt-4 text-sm leading-snug dark:border-slate-800">
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
        <span className="font-medium">“{request.prompt}”</span>
        {(r.pieces ?? []).map(p => <span key={p} className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{label(p)}</span>)}
      </div>
      <p className="rounded-lg bg-indigo-50 p-3 text-indigo-950 dark:bg-indigo-950/40 dark:text-indigo-100">{r.answer}</p>
      {r.summary && <p className="mt-2 text-slate-600 dark:text-slate-300">{r.summary}</p>}
      <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">{r.memory_used?.customer_facts ?? 0} customer facts</span>
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300">{r.memory_used?.company_lessons ?? 0} playbook lessons</span>
      </div>

      <Section title="Open items" show={r.open_items.length > 0}>
        <ul className="space-y-1.5">{r.open_items.map((x, k) => <li key={k} className="rounded-md border-l-2 border-amber-400 pl-2">{x.text} <SourceChips ids={x.sources} onSource={onSource} /></li>)}</ul>
      </Section>
      <Section title="Risks" show={r.risks.length > 0}>
        <ul className="space-y-1.5">{r.risks.map((x, k) => <li key={k} className="rounded-md border-l-2 border-rose-400 pl-2">{x.text} <SourceChips ids={x.sources} onSource={onSource} /></li>)}</ul>
      </Section>
      <Section title="What to ask" show={r.what_to_ask.length > 0}>
        <ul className="list-disc space-y-1 pl-5">{r.what_to_ask.map((x, k) => <li key={k}>{x.text} <SourceChips ids={x.sources} onSource={onSource} /></li>)}</ul>
      </Section>
      <Section title="How to win each stakeholder" show={r.stakeholders.length > 0}>
        <ul className="space-y-1.5">{r.stakeholders.map((s, k) => (
          <li key={k}><b>{s.name}</b>{s.role && <span className="text-slate-500"> ({s.role})</span>}: cares about {s.cares_about}.
            <span className="text-emerald-700 dark:text-emerald-400"> → {s.how_to_win}</span> <SourceChips ids={s.sources} onSource={onSource} /></li>
        ))}</ul>
      </Section>
      <Section title="Objection handling" show={r.objections.length > 0}>
        <ul className="space-y-2">{r.objections.map((o, k) => (
          <li key={k}>
            <div><b>“{o.objection}”</b>{o.raised_by && <span className="text-slate-500"> ({o.raised_by})</span>}{' '}
              <span className={`rounded px-1.5 text-[11px] font-medium ${o.status === 'resolved' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{o.status}</span>{' '}
              <SourceChips ids={o.sources} onSource={onSource} /></div>
            <div className="mt-0.5 rounded-md bg-emerald-50 px-2 py-1 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">→ {o.response}</div>
          </li>
        ))}</ul>
      </Section>
      <Section title="From the company playbook" show={r.playbook_tips.length > 0}>
        <ul className="space-y-1.5">{r.playbook_tips.map((x, k) => <li key={k} className="rounded-md bg-amber-50/60 px-2 py-1 dark:bg-amber-950/20">{x.text} <SourceChips ids={x.sources} onSource={onSource} /></li>)}</ul>
      </Section>
      <Section title="Call script" show={r.call_script.length > 0}>
        <ol className="space-y-1.5">{r.call_script.map((l, k) => (
          <li key={k} className="flex gap-2"><span className="w-20 shrink-0 text-xs font-semibold uppercase text-violet-600 dark:text-violet-400">{l.stage}</span>
            <span>“{l.say}” <SourceChips ids={l.sources} onSource={onSource} /></span></li>
        ))}</ol>
      </Section>
      <Section title="Next steps" show={r.next_steps.length > 0}>
        <ul className="list-disc space-y-0.5 pl-5">{r.next_steps.map((n, k) => <li key={k}>{n}</li>)}</ul>
      </Section>
      {r.follow_up_email && <>
        <div className="mt-4 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Follow-up email · draft, review before sending</h3>
          <button type="button" className="text-xs text-indigo-600 hover:underline" onClick={copy}>{copied ? 'Copied ✓' : 'Copy'}</button>
        </div>
        <p className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-2 text-xs dark:bg-slate-800/60">{r.follow_up_email}</p>
      </>}
      <MemoryTrace steps={r.trace} />
      {r.dropped > 0 && <p className="mt-1 text-[11px] text-slate-400">{r.dropped} unsourced item{r.dropped > 1 ? 's' : ''} removed by the evidence gate.</p>}
    </div>
  )
}
