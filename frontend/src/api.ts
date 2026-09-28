export type Status = 'NORMAL' | 'MONITOR' | 'ESCALATE'
export type OutcomeKind = 'prevented_failure' | 'failed' | 'normal'

export interface Reading {
  machine_id: string
  variant: 'L' | 'M' | 'H'
  air_temperature_k: number
  process_temperature_k: number
  rpm: number
  torque_nm: number
  tool_wear_min: number
}

export interface Evidence {
  experience_id: string
  timestamp: string
  event_type: string
  failure_mode: string | null
  outcome: OutcomeKind
  action_taken: string | null
  root_cause: string | null
  distance: number
  text: string
}

export type Verdict = 'caught' | 'missed' | 'false_alarm' | 'correct'

export interface SelfCheck {
  similar_reviews: number
  caught: number
  missed: number
  false_alarms: number
  correct: number
  original_status: Status
  adjustment: string | null
}

export interface Playbook {
  pattern: string
  name: string
  content: string
  last_refreshed_at: string | null
}

export interface Decision {
  event_id: string
  status: Status
  pattern: string | null
  self_check: SelfCheck
  pattern_strength: number
  pattern_label: 'HIGH' | 'MEDIUM' | 'LOW'
  historical_matches: number
  similar_failures: number
  similar_prevented_events: number
  recurring_signals: string[]
  recommendation: string
  reason: string
  evidence: Evidence[]
}

export interface Timeline {
  months: { month: string; failure?: number; near_miss?: number; normal?: number }[]
  learned: { experience_id: string; timestamp: string; outcome: string; action_taken: string; verdict: Verdict | null }[]
}

const BASE = import.meta.env.VITE_API_URL ?? ''

function demoKey() {
  try { return localStorage.getItem('demoKey') ?? '' } catch { return '' }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', 'X-Demo-Key': demoKey() },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (r.status === 401) {
    const k = prompt('Demo key')
    try { localStorage.setItem('demoKey', k ?? '') } catch { /* storage blocked */ }
    throw new Error('Demo key needed, try again')
  }
  const j = await r.json()
  if (!r.ok) {
    throw new Error(Array.isArray(j.detail)
      ? 'Insufficient or invalid sensor data: ' + j.detail.map((d: { loc: string[] }) => d.loc.at(-1)).join(', ')
      : j.detail)
  }
  return j
}

export const analyze = (r: Reading, use_memory: boolean) => call<Decision>('/api/analyze', { ...r, use_memory })
export const recordOutcome = (event_id: string, action: string, outcome: OutcomeKind, notes: string) =>
  call<{ retained: string; verdict: Verdict | null; pattern: string | null; text: string }>('/api/outcome', { event_id, action, outcome, notes })
export const timeline = () => call<Timeline>('/api/timeline')
export const playbooks = () => call<Playbook[]>('/api/playbooks')
