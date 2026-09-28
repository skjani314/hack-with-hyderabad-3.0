export type Channel = 'crm' | 'email' | 'call' | 'whatsapp' | 'outcome' | 'note'

/** A document in the Hindsight memory bank (the only source of truth). */
export interface Source {
  id: string
  channel: Channel
  date: string
  title: string
  people: string | null
  memories: number | null
}

export interface DealInfo {
  deal_id: string
  customer: string
  product: string
  industry: string
  value: string
  stage: string
  salesperson: string
  sources: string
}

export interface DealResponse {
  deal: DealInfo | null
  sources: Source[]
  memory_count: number
  sample_remaining: number
}

type Sourced<T> = T & { sources: string[] }
export interface Profile {
  pain_points: Sourced<{ text: string }>[]
  objections: Sourced<{ text: string; raised_by: string; status: string }>[]
  stakeholders: Sourced<{ name: string; role: string; cares_about: string }>[]
  competitors: Sourced<{ name: string; notes: string }>[]
  commitments: Sourced<{ text: string; owner: string; due: string; status: string }>[]
  pricing: Sourced<{ text: string }>[]
}

export interface ChatAnswer {
  answer: string
  sources: string[]
  used_memory: boolean
  memory_count: number
}

const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

function demoKey() {
  try { return localStorage.getItem('demoKey') ?? '' } catch { return '' }
}

async function call<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Demo-Key': demoKey() },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (r.status === 401) {
    const k = prompt('Demo key')
    try { localStorage.setItem('demoKey', k ?? '') } catch { /* storage blocked */ }
    throw new Error('Demo key needed, try again')
  }
  const j = await r.json().catch(() => ({ detail: `Server error ${r.status}` }))
  if (!r.ok) throw new Error(Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join('; ') : j.detail)
  return j
}

export const getDeal = () => call<DealResponse>('/api/deal')
export const sourceText = (id: string) => call<{ id: string; text: string }>(`/api/sources/${encodeURIComponent(id)}`)
export const addSource = (channel: Channel, title: string, content: string, people: string) =>
  call<{ remembered: string }>('/api/sources', 'POST', { channel, title, content, people })
export const importSample = (mode: 'next' | 'all') => call<{ remembered: string[] }>('/api/import', 'POST', { mode })
export const getProfile = () => call<{ profile: Profile | null; dropped: number }>('/api/profile')
export const ask = (question: string, use_memory: boolean) => call<ChatAnswer>('/api/chat', 'POST', { question, use_memory })
export const recordOutcome = (summary: string, result: string, next_step: string) =>
  call<{ remembered: string }>('/api/outcome', 'POST', { summary, result, next_step })
export const resetMemory = () => call<{ reset: boolean }>('/api/memory', 'DELETE')
