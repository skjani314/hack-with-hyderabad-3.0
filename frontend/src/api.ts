import type { components } from './api-types'

/** Types are generated from the backend's OpenAPI schema (npm run gen:api), never written by hand. */
type S = components['schemas']
export type User = S['UserOut']
export type Customer = S['CustomerOut']
export type CustomerDetail = S['CustomerDetail']
export type SourceRow = S['SourceRow']
export type Interaction = S['Interaction']
export type Participant = S['Participant']
export type Preview = S['InteractionPreview']
export type Job = S['JobOut']
export type IngestResult = S['IngestResult']
export type Report = S['Report']
export type RequestOut = S['RequestOut']
export type RequestRow = S['RequestRow']
export type Profile = S['Profile']
export type ProfileItem = S['ProfileItem']
export type Insight = S['Insight']
export type TraceStep = S['TraceStep']
export type PromptPiece = S['PromptPiece']
export type OrgSettings = S['OrgSettings']
export type Channel = Interaction['channel']

const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  constructor(message: string, status: number, code: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

let token = ''
try { token = localStorage.getItem('token') ?? '' } catch { /* storage blocked */ }

export function setToken(t: string) {
  token = t
  try { if (t) localStorage.setItem('token', t); else localStorage.removeItem('token') } catch { /* storage blocked */ }
}
export const hasToken = () => !!token

let onUnauthorized = () => {}
export const whenUnauthorized = (fn: () => void) => { onUnauthorized = fn }

async function call<T>(path: string, init: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (init.json !== undefined) headers['Content-Type'] = 'application/json'
  let r: Response
  try {
    r = await fetch(BASE + path, {
      method: init.method ?? (init.json !== undefined || init.form ? 'POST' : 'GET'), headers,
      body: init.form ?? (init.json !== undefined ? JSON.stringify(init.json) : undefined),
    })
  } catch {
    throw new ApiError('Cannot reach the server. Check your connection.', 0, 'network')
  }
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    if (r.status === 401 && token) { setToken(''); onUnauthorized() }
    const message = body.message ?? (Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join('; ')
      : body.detail) ?? (r.status === 413 ? 'File too large. For long calls use the recording URL.' : `Server error ${r.status}`)
    throw new ApiError(message, r.status, body.error ?? 'error')
  }
  return body as T
}

export const login = (email: string, password: string) =>
  call<S['LoginOut']>('/api/auth/login', { json: { email, password } })
export const me = () => call<User>('/api/auth/me')

export const listCustomers = () => call<Customer[]>('/api/customers')
export const createCustomer = (id: string, name: string, industry: string) =>
  call<Customer>('/api/customers', { json: { id, name, industry } })
export const getCustomer = (id: string) => call<CustomerDetail>(`/api/customers/${encodeURIComponent(id)}`)
export const sourceText = (id: string, doc: string) =>
  call<S['SourceText']>(`/api/customers/${encodeURIComponent(id)}/sources/${encodeURIComponent(doc)}`)

export interface PreviewInput {
  text?: string; file?: File; recordingUrl?: string; channel?: Channel | ''; title?: string
  occurredAt?: string; participants?: Participant[]
}
export function previewInteraction(id: string, p: PreviewInput) {
  const f = new FormData()
  if (p.file) f.append('file', p.file)
  if (p.text) f.append('text', p.text)
  if (p.recordingUrl) f.append('recording_url', p.recordingUrl)
  if (p.channel) f.append('channel', p.channel)
  if (p.title) f.append('title', p.title)
  if (p.occurredAt) f.append('occurred_at', p.occurredAt)
  if (p.participants?.length) f.append('participants', JSON.stringify(p.participants))
  return call<Preview>(`/api/customers/${encodeURIComponent(id)}/interactions/preview`, { form: f })
}
export const ingest = (id: string, interactions: Interaction[], requestId?: string | null) =>
  call<Job>(`/api/customers/${encodeURIComponent(id)}/interactions`, { json: { interactions, request_id: requestId ?? null } })

export const ask = (id: string, prompt: string, pieces: string[], parent?: string | null) =>
  call<RequestOut>(`/api/customers/${encodeURIComponent(id)}/requests`, { json: { prompt, pieces, parent_request_id: parent ?? null } })
export const listPromptPieces = () => call<PromptPiece[]>('/api/prompt-pieces')
export const getSettings = () => call<OrgSettings>('/api/settings')
export const saveSettings = (main_prompt: string) => call<OrgSettings>('/api/settings', { json: { main_prompt } })
export const listRequests = (id: string) => call<RequestRow[]>(`/api/customers/${encodeURIComponent(id)}/requests`)
export const getRequest = (id: string, rid: string) =>
  call<RequestOut>(`/api/customers/${encodeURIComponent(id)}/requests/${encodeURIComponent(rid)}`)
export const getProfile = (id: string) => call<Profile>(`/api/customers/${encodeURIComponent(id)}/profile`)
export const listInsights = (industry?: string) =>
  call<Insight[]>(`/api/company/insights${industry ? `?industry=${encodeURIComponent(industry)}` : ''}`)
