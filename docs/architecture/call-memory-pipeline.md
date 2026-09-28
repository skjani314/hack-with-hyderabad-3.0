# Call memory pipeline: architecture

Status: **proposed** (2026-09-28). Replaces the single-deal, single-bank design currently in `backend/`.

## The idea in one breath

A salesperson picks a customer, gets a pre-call brief built from **that customer's memory** plus **what the
company has learned across all customers**, makes the call, uploads the recording (or a transcript), and the
system transcribes, extracts, and writes back to both memories. Every call makes the next brief better, for this
customer and for everyone else.

```
            ┌──────────── BEFORE THE CALL ────────────┐
customer_id ─► known? ──no──► create customer bank (empty brief: company playbook only)
                 │yes
                 ▼
        recall(customer bank)  +  recall(company bank)
                 └──────────► LLM ──► pre-call brief (Pydantic schema)
                                         │
                                  salesperson makes the call
                                         │
            ┌──────────── AFTER THE CALL ─────────────┐
audio file ─► speech-to-text ─┐
transcript text ──────────────┴─► transcript ─► LLM extraction (Pydantic schema)
                                                   │
                        ┌──────────────────────────┼───────────────────────────┐
                        ▼                          ▼                           ▼
             retain transcript +          retain generalised           call summary +
             customer facts               company insights             next steps to UI
             → customer bank              → company bank
```

## 1. Input

| Input | How it arrives | Notes |
|---|---|---|
| `customer_id` | Picked or typed in the UI | Looked up first. Unknown id → **"Create customer X?" confirmation**, not silent auto-create (a typo would otherwise create a phantom customer with an empty memory). |
| Call recording | File upload: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm | Transcribed server-side (§2). |
| Call transcript | Pasted text or `.txt` upload | Skips speech-to-text. |
| Call metadata | Date, participants, salesperson, optional title | Date defaults to upload time. Participants help the LLM label speakers. |

Every upload gets a `call_id` (e.g. `CALL-07`). It is the Hindsight `document_id`, so re-uploading the same call
**replaces** the old version instead of duplicating it (Hindsight upserts on `document_id`).

## 2. Processing

### 2a. Speech-to-text (audio only)

**Groq Whisper**, since the brief already recommends Groq and one key covers both STT and the LLM.

| | `whisper-large-v3-turbo` (default) | `whisper-large-v3` |
|---|---|---|
| Price | $0.04 / hour | $0.111 / hour |
| File limit | 25 MB free tier, 100 MB dev tier | same |
| Timestamps | segment or word level (`verbose_json`) | same |

⚠️ **Groq Whisper does not tell you who is speaking** (no speaker diarization). A sales transcript without
speakers loses the most important thing: *who* raised the objection. Options:

1. **(MVP)** Pass Whisper's timestamped segments plus the known participant list to the LLM and ask it to assign
   speakers. Good enough for two- or three-person calls; mark labels as inferred.
2. **(Later)** A diarizing STT (e.g. AssemblyAI, Deepgram) if speaker accuracy becomes a problem.

Files over 25 MB: compress to mono 16 kHz mp3 before upload (a one-hour call fits), or split into chunks.

### 2b. LLM extraction (one call, structured output)

The transcript goes to the LLM with a **Pydantic schema**, validated on our side. One call produces:

```python
class CallExtraction(BaseModel):
    summary: str                         # 3–5 sentences
    customer: CustomerFacts              # → customer bank
    company_insights: list[Insight]      # → company bank, generalised
    next_steps: list[NextStep]           # shown to the salesperson

class CustomerFacts(BaseModel):
    pain_points: list[Sourced]
    objections: list[Objection]          # text, raised_by, status: open|resolved
    stakeholders: list[Stakeholder]      # name, role, cares_about
    competitors: list[Competitor]
    requirements: list[Sourced]
    commitments: list[Commitment]        # text, owner, due, status
    pricing: list[Sourced]
    sentiment: Literal["positive", "neutral", "negative"]

class Insight(BaseModel):
    kind: Literal["objection_handling", "what_worked", "what_failed", "competitor_intel",
                  "persona_pattern", "pricing_pattern"]
    text: str                            # MUST NOT name the customer or its people
    applies_to: dict[str, str]           # e.g. {"industry": "manufacturing", "role": "finance"}
    evidence: Literal["observed_once", "confirmed_outcome"]
```

**The customer/company split is the LLM's job, with a hard rule:** company insights are *generalised lessons*,
never customer data. "Finance controllers push back on price; a 3-year cost comparison against cloud got
approval" is a company insight. "Michael at Acme wants 10% off" is a customer fact. A cheap post-check rejects any
insight that contains a known customer or stakeholder name, so one customer's data never leaks into another
customer's brief.

**LLM:** Groq `openai/gpt-oss-120b` (brief's recommendation). Structured output can fail. On a validation error,
retry once with the error message, then fall back to storing the raw transcript only (the call is still
remembered; extraction can be re-run). Never lose the transcript because extraction failed.

## 3. Memory (Hindsight)

**Yes, this works with Hindsight.** Its docs describe exactly this pattern: *one bank per user* plus *a shared
bank*, with the client querying both and merging results.

| Bank | id | Holds | Written when |
|---|---|---|---|
| Customer bank (one per customer) | `cust-<customer_id>` | Full transcripts, customer facts, call outcomes, CRM record | Customer created; every call upload |
| Company bank (one) | `company` | Generalised insights, what worked/failed, competitor intel, playbook | Every call upload (insights only) |

### What gets retained

Per call, into the **customer bank**:

- the **full transcript** (`document_id = call_id`). Store the source, not just our summary: Hindsight runs its
  own fact extraction on it, and it is what citations point back to. A summary alone loses details we didn't
  think to ask for.
- the extracted customer facts as a second document (`document_id = call_id + "-facts"`) so the brief can show
  structured fields without re-asking the LLM.

Per call, into the **company bank**: each insight, tagged from `applies_to` (e.g. `industry:manufacturing`,
`role:finance`, `kind:objection_handling`) so recall can pull only the lessons relevant to this customer.

### Why not one bank with tags?

The current repo uses one bank and tags per deal. That works, but separate banks give us: hard isolation between
customers (a tag mistake can't leak data), a clean "new customer = new bank", per-customer reset/delete, and it
is the pattern Hindsight documents. Cost: the brief step must query two banks and merge, which we do anyway (§4).

## 4. Output: the pre-call brief

1. `recall` on `cust-<id>` for this customer's history.
2. `recall` on `company`, filtered by tags matching this customer (industry, stakeholder roles, open objection
   kinds).
3. Our LLM (Groq) combines both into a **Pydantic-validated brief**:

```python
class Brief(BaseModel):
    situation: str                       # where the deal stands, 2–3 sentences
    open_items: list[Sourced]            # overdue commitments, unresolved objections
    stakeholders: list[Stakeholder]
    talking_points: list[Sourced]        # what to say, and why
    playbook_tips: list[Sourced]         # from the company bank
    risks: list[Sourced]
    suggested_next_step: str
```

Every item cites its source (`CALL-03`, or `company` insight ids). The existing **evidence gate** keeps working:
anything citing a source not in memory is dropped.

**Why recall + our own LLM instead of `reflect`:** `reflect` works on **one bank per call**, and we need two.
Using `recall` for both and our own LLM also gives us full control over the prompt, the schema and the model.
This settles the "reflect vs recall" question left open in `docs/resources/hindsight.md`.

**New customer:** the customer bank is empty, so the brief is built from the company bank only ("first call
with a manufacturing CFO: here is what has worked"). That is a useful answer, not an empty screen.

## 5. The learning loop (what the judges score)

The brief rewards an agent that visibly improves. Two loops:

1. **Per customer:** every call is retained, so call 5's brief knows everything from calls 1–4.
2. **Across customers:** after a call, extraction compares **what the brief recommended** with **what actually
   happened**, and writes `what_worked` / `what_failed` insights to the company bank (`evidence:
   confirmed_outcome`). The next brief for *any* customer with the same situation uses them.

Demo story: customer A's CFO accepts a 3-year cost comparison → the company bank learns "lead with 3-year cost
for finance" → customer B's first brief already suggests it.

## 6. Users and logins

Two different "users" here, kept apart:

- **Salesperson (logs in):** authenticates with the app; each API call carries their identity; later, which
  customers they can see.
- **Customer (the account):** identified by `customer_id`; has a bank; never logs in.

For the hackathon MVP: one shared login (the existing `DEMO_KEY`) and a customer picker. Per-salesperson auth is
listed but not built.

## 7. API sketch

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/customers` | List customers (from bank list) |
| `POST` | `/api/customers` | Create customer + bank (confirmed in UI) |
| `GET` | `/api/customers/{id}/brief` | Pre-call brief (§4) |
| `POST` | `/api/customers/{id}/calls` | Upload audio or transcript → STT → extract → retain (§2–3) |
| `GET` | `/api/customers/{id}/calls` | Call list with summaries |
| `GET` | `/api/company/insights` | What the company has learned |

Call upload is slow (STT + LLM + two retains, tens of seconds): run it as a background job and let the UI poll
status (`uploaded → transcribed → extracted → remembered`).

## 8. Open questions

- Keep the existing Acme sample data as a seeded customer? (Recommended: yes, as one of 2–3 seeded customers, so
  the cross-customer learning demo has something to learn from.)
- Diarization: accept LLM-assigned speakers for the demo, or pay for a diarizing STT?
- Does Hindsight Cloud limit the number of banks per account? **Not checked.** If it does, fall back to one bank
  with `customer:<id>` tags.
- Where do audio files live after transcription? MVP: not stored, transcript only.

## Sources

- Groq speech-to-text docs (models, 25/100 MB limits, formats, no diarization, timestamps, pricing):
  https://console.groq.com/docs/speech-to-text
- Hindsight `llms.txt` (per-user bank; user bank + shared bank with client-side merge; `document_id` upsert;
  reflect is per bank): https://hindsight.vectorize.io/llms.txt
- Hindsight notes and links: [`../resources/hindsight.md`](../resources/hindsight.md)
- Project spec: `sample_Sales_Memory_Agent_What_to_Build.pdf`; hackathon brief linked in the resources note.
