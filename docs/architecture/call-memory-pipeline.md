# Interaction memory pipeline: architecture

Status: **proposed** (2026-09-28). Replaces the single-deal, single-bank design currently in `backend/`.

## The idea in one breath

A salesperson picks a customer, gets a pre-call brief built from **that customer's memory** plus **what the
company has learned across all customers**, talks to the customer (call, email, WhatsApp), adds what happened, and
the system turns it into text, extracts what matters, and writes back to both memories. Every interaction makes
the next brief better, for this customer and for everyone else.

```
            ┌──────────── BEFORE THE CALL ────────────┐
customer_id ─► known? ──no──► "Create customer X?" ──► new customer bank
                 │yes                                  (brief = company playbook only)
                 ▼
        recall(customer bank)  +  recall(company bank)
                 └──────────► LLM ──► pre-call brief (Pydantic schema)
                                         │
                          salesperson calls / emails / messages
                                         │
            ┌──────────── AFTER ─────────────────────┐
call audio / recording URL ─► speech-to-text + speaker labels ─┐
call transcript (paste, MCube) ────────────────────────────────┤
WhatsApp chat export (.txt) ─► parser ─────────────────────────┤
email (.eml or paste) ─► parser ───────────────────────────────┼─► normalised Interaction(s)
CRM export (.csv) or note ─► parser ───────────────────────────┘          │
                                                                 preview + confirm (UI)
                                                                          │
                                                        LLM extraction (Pydantic schema)
                                                                          │
                        ┌─────────────────────────────────────────────────┼──────────────────┐
                        ▼                                                 ▼                  ▼
             retain source text + customer facts          retain generalised       summary + next
             → customer bank                              insights → company bank  steps to UI
```

## 1. Input

Everything becomes one shape before processing:

```python
class Interaction(BaseModel):
    customer_id: str
    channel: Literal["call", "email", "whatsapp", "crm", "note"]
    occurred_at: datetime
    title: str
    participants: list[Participant]       # name, side: "ours" | "customer", role (optional)
    turns: list[Turn]                     # speaker, side, text, timestamp (calls and chats)
    text: str                             # full rendered text, what gets retained
    source_ref: str                       # file name, recording URL, message id
    fingerprint: str                      # hash for de-duplication (§1.3)
```

### 1.1 How each channel gets in (POC: manual, no live connectors)

For the POC we inject data by hand, per customer. "By hand" should still mean **the real artefact the salesperson
already has**, not retyping. Each channel has a better-than-paste option:

| Channel | Best manual input | What we get for free | Fallback |
|---|---|---|---|
| **Call** | Audio upload **or** recording URL (MCube gives one, with timestamps) | Timestamps; speakers if dual-channel (§2a) | Paste transcript |
| **WhatsApp** | **"Export chat" `.txt`** (WhatsApp → chat → ⋮ → More → Export chat → Without media) | Exact sender and timestamp per message, whole history in one file | Paste messages |
| **Email** | **`.eml` file** (Gmail: ⋮ → *Download message*; Outlook: drag the mail out) | From, To, Cc, Date, Subject, body, thread headers; parsed by Python's standard `email` module | Paste the thread |
| **CRM** | **CSV export** (HubSpot / Salesforce / sheet), columns mapped once | Structured deal fields: stage, value, owner, close date | Typed note |
| **Note** | Free text | – | – |

Why this is better than a paste box: exports carry **who said it and when**, which is exactly what sales memory
needs, and they are the real data format a production connector would receive.

⚠️ WhatsApp export line format differs by phone and locale (Android `12/09/2026, 21:16 - Name: text` vs iOS
`[12/09/26, 9:16:05 PM] Name: text`). The parser must handle both; test it on a real export from our own team
group before relying on it. Not yet verified.

### 1.2 One smart drop zone

The per-customer **Add to memory** panel has one drop zone plus a paste box:

- **Detect by file:** audio → call; `.eml` → email; `.csv` → CRM; `.txt` matching the WhatsApp line pattern →
  WhatsApp; other `.txt` → transcript or note.
- **Detect pasted text:** WhatsApp line pattern, email headers (`From:`/`Subject:`), `Speaker:` transcript lines;
  otherwise ask the user to pick the channel.
- **Recording URL field** for calls.
- The user can always override the detected channel.

### 1.3 Preview, then confirm (never retain blind)

After parsing, the UI shows what will be remembered **before** anything is sent to Hindsight:

- parsed messages or transcript turns with sender, side (ours / customer) and time;
- for calls: speaker labels are **editable** (click a label to reassign it);
- for WhatsApp exports: which messages are **new** vs already in memory;
- a map of names to people ("Uday → customer, CFO") the first time a name is seen for this customer, remembered
  afterwards.

Then **Remember**. This catches wrong speaker labels and parse errors cheaply, and makes a good demo moment.

**De-duplication:** a WhatsApp export always contains the whole chat, so re-uploading it next week would store
everything twice. Each message gets a fingerprint (hash of channel + sender + timestamp + text); only unseen
fingerprints are retained. Emails use the `Message-ID` header. Calls use the recording URL or file hash.

**Grouping:** WhatsApp messages are retained **one document per day per chat** (`WA-2026-09-12`), not one per
message: fewer retain calls, and each document has enough context for extraction. Re-uploading the same day
upserts that document (Hindsight replaces on the same `document_id`).

## 2. Processing

### 2a. Calls: speech-to-text with speaker separation

Speaker separation means every line is labelled with **who** said it (our salesperson vs the customer, and which
customer person). It matters because "who raised the objection" is the core sales fact.

**Speech-to-text:** Groq Whisper, since the brief already recommends Groq.

| | `whisper-large-v3-turbo` (default) | `whisper-large-v3` |
|---|---|---|
| Price | $0.04 / hour | $0.111 / hour |
| File limit | 25 MB free tier, 100 MB dev tier | same |
| Formats | flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm | same |
| Timestamps | segment or word level (`verbose_json`) | same |
| Speaker labels | **No** | **No** |

**Getting speakers, best option first:**

1. **Dual-channel recording.** Call platforms often record each side on its own stereo channel. Split channels
   (ffmpeg), transcribe each, merge by timestamp: exact "ours vs customer" labels at no extra cost. **Check whether
   MCube recordings are dual-channel** (not verified).
2. **Diarizing speech-to-text** (e.g. AssemblyAI, Deepgram) labels Speaker A / B / C; we map letters to people in
   the preview. Needed when several customer people are on one call. Pricing and free tiers not checked.
3. **LLM-assigned speakers** from Whisper's timestamped segments plus the participant list. Cheapest; good enough
   for a demo; always shown as editable in the preview.

Files over 25 MB: convert to mono 16 kHz mp3 first (keep stereo if using option 1).

### 2b. LLM extraction (one call, structured output)

The rendered interaction text goes to the LLM with a **Pydantic schema**, validated on our side:

```python
class Extraction(BaseModel):
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
insight containing a known customer or stakeholder name, so one customer's data never reaches another's brief.

**LLM:** Groq `openai/gpt-oss-120b` (brief's recommendation). On a schema validation error, retry once with the
error message, then fall back to retaining the source text only (it is still remembered; extraction can be re-run
later). Never lose the source because extraction failed.

## 3. Memory (Hindsight)

Hindsight supports this directly: its docs describe *one bank per user* plus *a shared bank*, with the client
querying both and merging.

| Bank | id | Holds | Written when |
|---|---|---|---|
| Customer bank (one per customer) | `cust-<customer_id>` | Source texts (transcripts, emails, chats, CRM), customer facts, outcomes | Customer created; every interaction |
| Company bank (one) | `company` | Generalised insights, what worked/failed, competitor intel | Every interaction (insights only) |

Hindsight structure, for reference: account (API key) → banks → inside each bank: documents (our text), memories
(facts it extracts), entities, relationships, directives. Writing to a missing bank creates it; reading a missing
bank returns `404`, which doubles as our "is this customer registered?" check.

**Per interaction, into the customer bank:**

- the **full source text** (`document_id` = interaction id, e.g. `CALL-07`, `EM-12`, `WA-2026-09-12`). Store the
  source, not only our summary: Hindsight runs its own extraction on it, and citations point back to it.
- the extracted customer facts as a second document (`<id>-facts`), so the UI can show structured fields without
  asking the LLM again.

**Into the company bank:** each insight, tagged from `applies_to` (`industry:manufacturing`, `role:finance`,
`kind:objection_handling`) so recall pulls only lessons relevant to the customer at hand.

**Why not one bank with tags (current repo)?** Separate banks give hard isolation between customers (a tag mistake
can't leak data), "new customer = new bank", per-customer delete, and match Hindsight's documented pattern. Cost:
the brief queries two banks and merges, which we do anyway (§4).

## 4. Output: the pre-call brief

1. `recall` on `cust-<id>`: this customer's history.
2. `recall` on `company`, filtered by tags matching this customer (industry, stakeholder roles, open objection
   kinds).
3. Our LLM combines both into a **Pydantic-validated brief**:

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

Every item cites its source (`CALL-03`, `EM-12`, or a company insight id). The existing **evidence gate** keeps
working: anything citing a source not in memory is dropped.

**Why `recall` + our own LLM, not `reflect`:** `reflect` works on **one bank per call** and we need two. It also
gives us control of prompt, schema and model.

**New customer:** the customer bank is empty, so the brief comes from the company bank only ("first call with a
manufacturing CFO: here is what has worked"). A useful answer, not an empty screen.

## 5. The learning loop (what the judges score)

1. **Per customer:** every interaction is retained, so the fifth brief knows everything from the first four.
2. **Across customers:** after a call, extraction compares **what the brief recommended** with **what actually
   happened** and writes `what_worked` / `what_failed` insights to the company bank (`evidence:
   confirmed_outcome`). The next brief for *any* customer in the same situation uses them.

Demo story: customer A's CFO accepts a 3-year cost comparison → the company bank learns "lead with 3-year cost
for finance" → customer B's first brief already suggests it.

## 6. No websockets needed

Everything above is plain request/response. For slow work:

- **Call processing** (download → speech-to-text → extraction → two retains, tens of seconds) runs as a background
  job. The upload returns a `job_id` at once; the UI **polls** `GET /api/jobs/{id}` every 2 seconds and shows the
  stage: `received → transcribing → labelling speakers → extracting → remembering → done`. Polling is enough at
  hackathon scale and survives Vercel's serverless model better than a held-open socket.
- If a progress stream is wanted later, **Server-Sent Events** (one-way, plain HTTP) is simpler than websockets.

## 7. From manual to automatic (production, not the POC)

The live connectors are **webhooks**: plain HTTP POSTs that the provider sends to us, not websockets. Each one
produces the same `Interaction` as the manual path, so nothing downstream changes.

| Channel | Production source | How it reaches us |
|---|---|---|
| Call | MCube (recording URL + timestamps per call) | Webhook on call end, or a scheduled pull |
| WhatsApp | WhatsApp Business Cloud API | Webhook per incoming message |
| Email | Gmail / Outlook API, or an inbound-mail address (forward or BCC `acme@memory.ourapp`) | Push notification or inbound-mail webhook |
| CRM | HubSpot / Salesforce | Webhook on deal update, or a nightly sync |

The **BCC address** is the cheapest real-world step up: a salesperson adds one address to Cc/Bcc and the email
is remembered, with no integration work on their side.

For the pitch: *"The POC takes real exports by hand; in production the same pipeline is fed by webhooks from
MCube, WhatsApp Business, Gmail and the CRM."*

## 8. Users and logins

- **Salesperson (logs in):** authenticates with the app; later, which customers they can see.
- **Customer (the account):** identified by `customer_id`; has a bank; never logs in.

MVP: one shared login (the existing `DEMO_KEY`) and a customer picker.

## 9. API sketch

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/customers` | List customers (from bank list) |
| `POST` | `/api/customers` | Create customer + bank (confirmed in UI) |
| `GET` | `/api/customers/{id}/brief` | Pre-call brief (§4) |
| `POST` | `/api/customers/{id}/parse` | File / paste / recording URL → parsed `Interaction` preview (no memory write) |
| `POST` | `/api/customers/{id}/interactions` | Confirmed preview → extraction → retain; returns `job_id` |
| `GET` | `/api/jobs/{job_id}` | Job stage and result (polled) |
| `GET` | `/api/customers/{id}/interactions` | Timeline with summaries |
| `GET` | `/api/company/insights` | What the company has learned |

## 10. Open questions

- Keep the existing Acme sample data as a seeded customer? (Recommended: yes, as one of 2–3 seeded customers so
  the cross-customer learning demo has something to learn from.)
- Are MCube recordings dual-channel? Decides the speaker-separation option.
- Diarizing STT (AssemblyAI / Deepgram) vs LLM-assigned speakers for the demo.
- Does Hindsight Cloud limit banks per account? **Not checked.** If so, fall back to one bank with
  `customer:<id>` tags.
- Where do audio files live after transcription? MVP: not stored, transcript only.

## Sources

- Groq speech-to-text docs (models, limits, formats, no diarization, timestamps, pricing):
  https://console.groq.com/docs/speech-to-text
- Hindsight `llms.txt` and full docs (per-user + shared bank pattern, `document_id` upsert, reflect per bank,
  bank auto-create and `404` on read): https://hindsight.vectorize.io/llms.txt
- Hindsight notes and links: [`../resources/hindsight.md`](../resources/hindsight.md)
- Team discussion 2026-09-28: inputs must include email, WhatsApp and CRM, not only calls; call data comes from
  MCube with timestamps and a recording URL; speakers must be separated; POC data is injected manually.
- Project spec: `sample_Sales_Memory_Agent_What_to_Build.pdf`; hackathon brief linked in the resources note.
