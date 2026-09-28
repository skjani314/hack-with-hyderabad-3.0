# Contracts: API ↔ backend ↔ agent

Status: **built** (2026-09-28), with the deviations listed in §9. The agreed shapes between the frontend, the backend API and the agent. If code
and this doc disagree, one of them is a bug. Companion to [`call-memory-pipeline.md`](./call-memory-pipeline.md),
[`hindsight-memory-shape.md`](./hindsight-memory-shape.md) and
[`auth-and-customer-directory.md`](./auth-and-customer-directory.md).

## 1. Layers and who owns what

```
Frontend (React)
   │  REST + JSON, session token          ← API contracts (§5): 16 endpoints
   ▼
Backend API (FastAPI)  ── MongoDB (users, customers, requests, jobs)
   │  Python function calls, Pydantic in/out   ← Agent contracts (§4): 6 functions
   ▼
Agent (Python package)
   ├── Hindsight (customer banks + company bank)
   ├── Groq LLM (extraction, reports)
   └── Speech-to-text (calls)
```

| Layer | Owns | Never does |
|---|---|---|
| **Backend API** | Login, permissions, MongoDB, HTTP, jobs, turning errors into status codes | Call Hindsight, Groq or STT directly |
| **Agent** | Parsing, transcription, extraction, memory reads/writes, reports, the evidence gate | Know about users, tokens, MongoDB or HTTP |

The seam between them is **`CustomerContext`**: the backend authenticates, checks permission, looks up the
customer in MongoDB and hands the agent an already-authorised context. The agent trusts it and never sees a
login.

## 2. Shared types

One Python module (`backend/contracts.py`) defines every type below as a Pydantic model. The frontend's
TypeScript types are **generated** from FastAPI's OpenAPI schema (e.g. `openapi-typescript`), not hand-written.

Why generated: today they already drift. `frontend/src/api.ts` declares `CallPrep.insights[].why_it_matters`,
`stakeholders[].how_to_win_them` and `objections[].raised_by`, but `backend/sales_agent.py` `gate_prep` returns
`insights` / `stakeholders` as `{text, sources}` and `objections` as `{objection, response, sources}` with no
`raised_by`. The UI reads fields the API never sends. A generated client makes that a type error at build time.

```python
class CustomerContext(BaseModel):     # built by the backend, trusted by the agent
    customer_id: str                  # "acme"
    bank_id: str                      # "cust-acme"  (from MongoDB, never from the browser)
    name: str                         # "Acme Manufacturing"
    industry: str                     # "manufacturing", feeds company-bank tag filters
    exec_name: str                    # the logged-in sales exec, for "I am X selling to Y"

class Participant(BaseModel):
    name: str
    side: Literal["ours", "customer"]
    role: str = ""                    # "Finance Controller"

class Turn(BaseModel):
    speaker: str
    side: Literal["ours", "customer", "unknown"]
    text: str
    at: datetime | None = None
    speaker_inferred: bool = False    # true when the LLM guessed the speaker

class Interaction(BaseModel):         # every input is normalised to this
    document_id: str                  # "CALL-07", "EM-12", "WA-2026-09-12", "FILE-proposal-v2"
    channel: Literal["call", "email", "whatsapp", "crm", "note", "document", "outcome"]
    occurred_at: datetime
    title: str
    participants: list[Participant] = []
    turns: list[Turn] = []            # calls and chats
    text: str                         # rendered text that gets retained
    source_ref: str = ""              # file name, recording URL, Message-ID
    fingerprints: list[str] = []      # de-duplication (WhatsApp messages, emails)
    mode: Literal["replace", "append"] = "replace"
    request_id: str | None = None     # the report this call followed, for the learning loop

class Sourced(BaseModel):
    text: str
    sources: list[str]                # ["CALL-03", "EM-02"] or ["INS-…"] for company lessons; never empty

class TraceStep(BaseModel):           # what the agent did, shown in the UI
    step: str                         # "recall", "read_source", "retain", "extract"
    detail: str
    result: str = ""
```

## 3. Rules every contract follows

1. **Every claim cites a source**, and the evidence gate drops any claim whose sources are not in memory.
   Responses report `dropped: int`.
2. **Every agent response carries `trace: list[TraceStep]`** so the UI can show what memory was used.
3. **Company-bank content never names a customer or person.** Enforced at write time (A3), checked again at read
   time (A4).
4. **Agent errors are typed**, never raw exceptions (§6).
5. **Every response model has `schema_version`** (starts at `1`); bump it when a field changes meaning.
6. **Every LLM output is a Pydantic model generated with Groq strict structured outputs** (see
   [`decisions.md`](./decisions.md) D3): `extra="forbid"`, no defaults, optional = nullable. Defaults shown in
   the sketches below (`= []`, `= ""`) are for our own internal types; the schemas sent to the LLM drop them.

## 4. Agent contracts (backend → agent): 6

| # | Function | When | Memory ops | LLM | Time |
|---|---|---|---|---|---|
| A1 | `create_customer_memory` | New customer | create bank + config | – | < 1 s |
| A2 | `prepare_interaction` | Upload / paste, before confirm | none (read-only dedupe check) | STT; LLM only to guess speakers | 2–40 s |
| A3 | `ingest_interaction` | Exec confirms the preview | retain → customer bank; retain → company bank | Extraction (1 call) | 5–30 s |
| A4 | `generate_report` | Exec submits a prompt | recall customer bank + recall company bank | Report (1 call, ≤ 2 tool rounds) | 5–20 s |
| A5 | `get_profile` | Customer page load | recall customer bank | Profile (1 call), cached until memory changes | 5–10 s |
| A6 | `list_company_insights` | "What we've learned" page | recall / list company bank | – | < 2 s |

### A1 `create_customer_memory(ctx) -> MemoryCreated`

```python
class MemoryCreated(BaseModel):
    bank_id: str
    created: bool                     # false if it already existed (idempotent)
```

Creates `ctx.bank_id` with the sales extraction instructions, `entity_labels` and observation settings. Safe to
retry: the backend calls it again when a customer is stuck in `status: "creating"`.

### A2 `prepare_interaction(ctx, input) -> InteractionPreview`

```python
class RawInput(BaseModel):
    kind: Literal["text", "file", "recording_url"]
    text: str | None = None
    file_name: str | None = None
    file_bytes: bytes | None = None
    recording_url: str | None = None
    channel: str | None = None        # user override; detected when None
    title: str | None = None
    occurred_at: datetime | None = None
    participants: list[Participant] = []

class InteractionPreview(BaseModel):
    schema_version: int = 1
    interactions: list[Interaction]   # a WhatsApp export can yield several (one per day)
    detected_channel: str
    new_fingerprints: int             # messages not yet in memory
    duplicate_fingerprints: int
    unknown_names: list[str]          # names the exec should map to a person / side
    warnings: list[str]               # "speakers inferred by LLM", "file converted with markitdown"
    trace: list[TraceStep]
```

**Writes nothing to memory.** The UI shows the preview; the exec fixes speaker labels and names; the edited
`Interaction`s come back in A3.

### A3 `ingest_interaction(ctx, interactions) -> IngestResult`

```python
class IngestResult(BaseModel):
    schema_version: int = 1
    remembered: list[str]             # document ids written to the customer bank
    company_insights: list[str]       # insight ids written to the company bank
    rejected_insights: int            # dropped because they named the customer or a person
    summary: str
    next_steps: list[str]
    extraction_ok: bool               # false → source text was retained, extraction must be re-run
    trace: list[TraceStep]
```

Steps: extraction (Pydantic `Extraction`, see pipeline doc §2b) → retain source text to the customer bank →
retain generalised insights to `company`. If `request_id` is set and the channel is `call`/`outcome`, the agent
also compares the report's advice with what happened and writes `what_worked` / `what_failed` insights.
**The source text is always retained, even when extraction fails.**

### A4 `generate_report(ctx, prompt, history=None) -> Report`

```python
class Stakeholder(Sourced):  name: str; role: str; cares_about: str; how_to_win: str
class Objection(Sourced):    objection: str; raised_by: str; status: Literal["open", "resolved"]; response: str
class ScriptLine(BaseModel): stage: str; say: str; sources: list[str]

class Report(BaseModel):
    schema_version: int = 1
    summary: str                      # where the deal stands
    answer: str                       # direct answer to the exec's prompt
    what_to_ask: list[Sourced]
    open_items: list[Sourced]         # overdue commitments, unresolved objections
    stakeholders: list[Stakeholder]
    objections: list[Objection]
    risks: list[Sourced]
    playbook_tips: list[Sourced]      # from the company bank
    call_script: list[ScriptLine]
    next_steps: list[str]
    follow_up_email: str
    memory_used: dict[str, int]       # {"customer_facts": 18, "company_insights": 4}
    dropped: int
    trace: list[TraceStep]
```

One contract for both "prepare my call" and a free question: `answer` is always filled; the structured sections
may be empty for a narrow question. `history` holds earlier turns of the same request for follow-ups. Replaces
today's `/api/chat` + `/api/prep` pair.

New customer (empty bank): the report is built from the company bank only and says so in `summary`.

### A5 `get_profile(ctx) -> Profile`

Same shape as today's profile (pain points, objections, stakeholders, competitors, commitments, pricing, plus
**requirements**, which the spec asks for and the current schema lacks), every item `Sourced`. The backend caches
it keyed by the bank's document list and invalidates after A3.

### A6 `list_company_insights(filters) -> list[Insight]`

```python
class InsightFilters(BaseModel):
    industry: str | None = None
    role: str | None = None
    kind: str | None = None

class Insight(BaseModel):
    id: str
    kind: str                         # objection_handling | what_worked | what_failed | competitor_intel | …
    text: str
    applies_to: dict[str, str]
    evidence: Literal["observed_once", "confirmed_outcome"]
    seen_count: int                   # how many interactions support it
```

## 5. API contracts (frontend → backend): 16

All JSON, all behind `Authorization: Bearer <token>` except login. **Customer routes also check the customer is
in the user's `customer_ids`** (admin: all).

| # | Method | Path | Request | Response | Agent |
|---|---|---|---|---|---|
| 1 | `POST` | `/api/auth/login` | `{email, password}` | `{token, user}` | – |
| 2 | `GET` | `/api/auth/me` | – | `{user}` | – |
| 3 | `GET` | `/api/customers` | – | `[{id, name, industry, status, last_interaction_at}]` | – |
| 4 | `POST` | `/api/customers` | `{id, name, industry}` | `{customer}` | A1 |
| 5 | `GET` | `/api/customers/{id}` | – | `{customer, interactions: [{document_id, channel, title, occurred_at}]}` | – (Hindsight doc list via agent helper) |
| 6 | `GET` | `/api/customers/{id}/sources/{doc_id}` | – | `{document_id, text}` | – (agent helper) |
| 7 | `POST` | `/api/customers/{id}/interactions/preview` | multipart: `text` \| `file` \| `recording_url`, `channel?`, `title?`, `occurred_at?`, `participants?` | `InteractionPreview` | A2 |
| 8 | `POST` | `/api/customers/{id}/interactions` | `{interactions: Interaction[], request_id?}` | `{job_id}` | A3 (as a job) |
| 9 | `GET` | `/api/jobs/{job_id}` | – | `{status, stage, result?: IngestResult, error?}` | – |
| 10 | `POST` | `/api/customers/{id}/requests` | `{prompt, parent_request_id?}` | `{request_id, report: Report}` | A4 |
| 11 | `GET` | `/api/customers/{id}/requests` | – | `[{request_id, prompt, created_at, summary}]` | – |
| 12 | `GET` | `/api/customers/{id}/requests/{request_id}` | – | `{request_id, prompt, report}` | – |
| 13 | `GET` | `/api/customers/{id}/profile` | – | `Profile` | A5 |
| 14 | `GET` | `/api/company/insights` | `?industry=&role=&kind=` | `Insight[]` | A6 |
| 15 | `POST` | `/api/users/{user_id}/customers` | `{customer_ids}` (admin) | `{user}` | – |
| 16 | `GET` | `/` | – | `{ok, service, version}` | – |

Job `stage` values: `received → transcribing → extracting → remembering → done` (or `failed`).

Requests (10–12) are stored in a MongoDB `requests` collection (`request_id`, `customer_id`, `user_id`, `prompt`,
`report`, `created_at`) so an exec can reopen a brief, and so A3 can compare a later call with the advice given.

## 6. Errors

The agent raises typed errors; the backend maps them. Every error body is `{error: code, message}`.

| Agent error | HTTP | Meaning / UI message |
|---|---|---|
| (backend) not logged in / bad token | 401 | Log in again |
| (backend) customer not in user's list | 403 | Not your customer |
| (backend) unknown customer id | 404 | Offer "Create customer X?" |
| `InvalidInput` | 422 | Unsupported file, empty text, bad recording URL |
| `DuplicateContent` | 409 | Everything in this upload is already in memory |
| `LLMRateLimited` | 429 | Groq limit; retry in a minute |
| `TranscriptionFailed` | 502 | STT failed; paste a transcript instead |
| `MemoryUnavailable` | 502 | Hindsight error |
| `ExtractionFailed` | 200 + `extraction_ok: false` | Not an error for the user: source is remembered, extraction retried later |
| missing server config | 503 | `GROQ_API_KEY` / `HINDSIGHT_API_KEY` / `MONGODB_URI` not set |

## 7. Long-running work on Vercel

`backend/vercel.json` gives each request up to **120 s** (`maxDuration: 120`), and a serverless function cannot
keep working after it has responded. So "return `job_id`, keep processing in the background" does not work as-is
on Vercel. Options:

1. **(MVP) Synchronous inside 120 s.** Endpoint 8 does the work and returns the finished job in one response. A
   20-minute call (STT a few seconds on Groq + one extraction + two retains) should fit; the UI shows a stage
   spinner. Endpoint 9 still exists and returns the stored result.
2. **Split the work across requests.** 7 transcribes, 8 extracts and retains: each step fits its own 120 s.
3. **Move the backend to an always-on host** (Render, Railway, Fly) with a real background worker, if calls get
   long.

## 8. How today's code maps to this

| Today | Becomes |
|---|---|
| `/api/deal`, `/api/sources/{id}` | 5, 6 (per customer) |
| `/api/sources`, `/api/import`, `/api/outcome` | 7 + 8 (every input, including outcomes, goes through preview → ingest) |
| `/api/chat`, `/api/prep` | 10 (one `Report` contract) |
| `/api/profile` | 13 |
| `/api/memory` (DELETE) | removed from the public API; a dev script resets a bank |
| `agent.py` + `sales_agent.py` | the agent package behind A1–A6 |

## Open

- Streaming the report (Server-Sent Events) so the exec sees it build, or return it whole? MVP: whole.
- Does A4 keep the tool loop (`recall_memory`, `read_source`) or prefetch only? Today's code does both, capped by
  Groq's free-tier token rate.
- Where does A3's comparison find "the advice given"? Proposed: the backend passes the stored `Report` of
  `request_id` into A3.

## 9. As built (differences from the proposal above)

- **Endpoints added:** `GET /api/prompt-pieces` (the injectable prompt pieces) and `GET/POST /api/settings` (the
  org's editable main prompt; `POST` is admin-only). `RequestIn` has `pieces: list[str]`; `Report` has `pieces`.
- **Endpoints removed:** every old single-deal route. `DELETE` is no longer used; resets are done by
  `seed_demo.py --reset`.
- **Settings are saved with `POST`,** not `PUT`, to keep the CORS method list to `GET`/`POST`.
- **Jobs run synchronously** inside the request (§7 option 1). The job record still stores the result.
- **Company-bank retains are queued** (`retain_async`) so the salesperson doesn't wait for the playbook write.
- **Insight ids** are `INS-<8 hex>` derived from (customer, document, index), so re-ingesting a document replaces
  its lessons. The evidence gate matches ids case-insensitively and returns the stored spelling.
- **Agent A2 input** is `RawInput` (`contracts.py`); a single pasted WhatsApp message (not an export) is stored as
  plain text.
- `openapi.json` is exported from the app and `frontend/src/api-types.ts` is generated from it (`npm run gen:api`).

### Changes after the first release

- `Report`: `call_script: list[ScriptLine]` → `call_plan: CallPlan` (one `ScriptStep` per step: opening, recap,
  discovery, value, objections, close); `open_items: list[OpenItem]` (text, owner, due, status, sources; customer
  sources only); new `deal_stage`, `deal_health`, `health_reason`, `stakeholders[].stance`; `memory_used.latest`.
- Briefs read the summaries of the 3 newest interactions before recall results; recall uses
  `include_source_facts` so observations cite their real documents.
- New agent errors: `NotFound` (404), `LLMRequestTooLarge` (413). `LLMRateLimited` (429) is raised only after one
  server-side wait of up to 25 s for Groq's `retry-after`.
- `Interaction.document_id` is validated: `^(CALL|EM|WA|CRM|NOTE|FILE|OUT)-[A-Za-z0-9-]{1,60}$`.

### Deal ledger (2026-09-29)

- New types: `Ledger`, `LedgerItem`, `LedgerPerson`, `LedgerUpdate` (LLM output, Groq-strict). `CustomerContext.our_team`
  (all users' names). `IngestResult.ledger` (the ledger after the upload). `ObjectionPlay.ledger_id`.
- Agent: `ingest_interaction(ctx, interactions, prior_report, current_ledger)` also updates the ledger;
  `rebuild_ledger(ctx)`; `generate_report(..., current_ledger)` reads it first and sets open items, objection status,
  stances and stage from it.
- API: `GET /api/customers/{id}/ledger`, `POST /api/customers/{id}/ledger/rebuild`. The backend loads and stores the
  ledger (MongoDB `ledgers`); the agent never touches MongoDB.
- Design: [`deal-ledger.md`](./deal-ledger.md).

### Focus (2026-09-29)

`ReportDraft.focus` — which section answers the request (status · email · objection · stakeholders · call_prep ·
questions · risks · playbook). The model chooses; `core._focus` overrides it for unambiguous wording. The UI renders
that section first and the rest under "More details". Saved reports are read through `api_v2.stored_report`, which
fills defaults for fields added later.
