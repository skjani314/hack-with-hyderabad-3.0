# Memory shape in Hindsight

Status: **proposed** (2026-09-28). How our data is laid out in Hindsight: banks, documents, what goes in each
retain call, and how facts, entities and links are kept. Companion to
[`call-memory-pipeline.md`](./call-memory-pipeline.md).

**Decision in one line: one bank per customer, one document per conversation (each call, email, CRM update or
file; one per WhatsApp chat per day), plus one shared `company` bank. Never one growing document per customer.**

## 1. The shape

We never write SQL or tables. We send text; Hindsight stores it and builds the knowledge itself (on Postgres +
pgvector underneath, which we don't touch).

```
Hindsight Cloud account (HINDSIGHT_API_KEY)
├── bank: company                     ← generalised lessons across all customers
│   ├── doc INS-CALL-07-acme          ← insights extracted from one interaction
│   └── ...
├── bank: cust-acme                   ← one bank per customer, fully isolated
│   ├── doc CRM-01                    ← one document per interaction
│   ├── doc CALL-07                   ← full transcript, speaker-labelled
│   ├── doc EM-12                     ← one email (or thread)
│   ├── doc WA-2026-09-12             ← one WhatsApp chat, one day, appended during the day
│   ├── doc FILE-proposal-v2          ← a PDF / XLSX / DOCX, converted to text
│   │
│   │   built by Hindsight, bank-wide:
│   ├── memories (facts)              ← each fact remembers which document it came from
│   ├── entities                      ← Michael, Priya, Nexbyte … one per real person/org
│   ├── links (knowledge graph)       ← same entity, close in time, similar meaning, cause
│   └── observations                  ← auto-merged conclusions ("Priya was blocking, now approved")
└── bank: cust-globex
    └── ...
```

## 2. What lives at which level

| Thing | Level | Built by | Notes |
|---|---|---|---|
| Bank | Account | Us (auto-created on first write) | Reading a missing bank returns `404`: our "is this customer registered?" check. |
| Document | Bank | Us (`document_id`) | Holds the original text and which facts came from it. Retaining the same id again **replaces** it. |
| Facts (memory units) | **Bank** | Hindsight (LLM at retain) | Each fact carries its `document_id`, date and metadata. Searchable bank-wide. |
| Entities | **Bank** | Hindsight | "Michael" in any document of the bank resolves to one entity (fuzzy name matching + co-occurrence). |
| Links | **Bank** | Hindsight | Entity, time, meaning and cause links between facts. |
| Observations | **Bank**, grouped by tag scope | Hindsight (background consolidation) | Merged conclusions that track change over time. |

**Consequence:** the knowledge graph is bank-wide, so whether we use one document or many barely changes the
facts, entities, links or observations. What documents decide is **provenance** (which source a fact cites),
**dates** (each retain item has one timestamp) and **fix granularity** (what a `replace` re-processes).
`recall` and `reflect` always search the whole bank, narrowed by tags, never by document.

## 3. Why one bank per customer, one document per conversation

From Hindsight's own guidance:

- **FAQ:** *"Per-user memory banks (recommended for most use cases) … Easiest setup and strongest data isolation."*
  Limitation: *"Cannot perform cross-user analysis"*, which is why we add a separate `company` bank.
- **Best practices:** *"One bank per user is the most common pattern for multi-user applications."* Documents
  are keyed per conversation: `document_id = f"session-{session_id}"`; a new random id every call is flagged as
  the anti-pattern (duplicates).
- **Sales research guide:** *"For sales, the best default is usually one bank per account."* and *"One bank per
  account is almost always cleaner than one giant bank for the whole pipeline."*

Why not one growing document per customer (`update_mode: "append"` every time):

| | One doc per conversation | One doc per customer |
|---|---|---|
| Citations | "[EM-02]" → the exact email | Every fact cites the same doc; the evidence gate loses its value |
| Dates | Each interaction has its own timestamp | One document, many dates; per-append dates not documented |
| Fix one bad transcript | Replace that one doc | Replace re-processes the customer's whole history |
| Per-item metadata (channel, participants, URL) | Kept per doc | Last append's metadata wins |
| Cost | ~same per item | ~same per item (extraction still runs on each new part) |

`append` **is** the right tool for content that grows: one WhatsApp chat per day, where new messages are
appended to `WA-<date>` (the docs give "a chat transcript where you receive new messages" as the use case).

## 4. Document ids

| Source | `document_id` | Update mode |
|---|---|---|
| CRM record / update | `CRM-01`, `CRM-02` … | replace |
| Call | `CALL-07` | replace (re-upload fixes it) |
| Email | `EM-12` (or `EM-<Message-ID hash>`) | replace |
| WhatsApp | `WA-2026-09-12` (per chat per day) | **append** new messages during the day |
| File (PDF, XLSX, DOCX, MD) | `FILE-<slug>` | replace (new version of the file) |
| Call outcome | `OUT-03` | replace |
| Company insight batch | `INS-<source doc id>-<customer>` in bank `company` | replace |

Short, readable ids on purpose: the agent cites them and the salesperson clicks them.

## 5. What each retain call carries

Hindsight `retain` item (verified against the docs):

| Field | Required | We send |
|---|---|---|
| `content` | **yes** (only required field) | Rendered text: header line (`[CALL-07] CALL on 2026-09-12 with …`) + speaker-labelled body |
| `document_id` | no, but always set by us | Per §4 |
| `update_mode` | no | `replace`; `append` for WhatsApp days |
| `timestamp` | no (defaults to now) | When the interaction happened, not when we uploaded it; resolves "last Monday" in the text |
| `context` | no | Specific label, e.g. `"sales discovery call with Acme finance and IT"`; the docs call this *"one of the highest-leverage things you can do to improve memory quality"* |
| `metadata` | no | `channel`, `title`, `participants`, `source_ref` (file name / recording URL), `customer_id`. Returned with every recalled fact; **not filterable** |
| `tags` | no | `channel:call`, `role:finance` … (**filterable** in recall/reflect) |
| `entities` | no | Known participant names, so they are always linked |

Files: Hindsight also has `retain_files` (PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, images with OCR, audio with
transcription, HTML, TXT, MD, CSV, JSON, YAML; asynchronous, returns operation ids). **We don't use it for
customer data**: if Hindsight ingests the file directly, our LLM never sees it, so the customer/company split and
our Pydantic extraction are skipped. Instead we convert files to text ourselves with **markitdown** (the same
open-source converter Hindsight uses by default) and send the text through the normal pipeline.

## 6. Our inject API

`POST /api/customers/{customer_id}/interactions` (multipart form):

| Parameter | Required | Meaning |
|---|---|---|
| `customer_id` (path) | yes | Target bank `cust-<id>` |
| **one of** `text` / `file` / `recording_url` | yes | Pasted text; any supported file (audio, `.eml`, WhatsApp `.txt`, `.csv`, PDF, XLSX, DOCX, MD); an MCube recording link |
| `channel` | no | `call` / `email` / `whatsapp` / `crm` / `note` / `document`; detected from the file when omitted |
| `title` | no | Shown in the timeline |
| `occurred_at` | no | Defaults to now; becomes the retain `timestamp` |
| `participants` | no | Name, side (`ours` / `customer`), role; becomes `entities` + metadata |
| `document_id` | no | Generated per §4 when omitted |
| `mode` | no | `replace` / `append` |

Returns a `job_id`; processing (convert → transcribe → extract → retain to both banks) runs in the background and
the UI polls, as described in the pipeline doc.

## 7. Settings we customise

| Setting | Where | What it controls | Our use |
|---|---|---|---|
| Banks | per customer + `company` | Hard isolation | §1 |
| `tags` | retain item | Visibility in recall/reflect | Customer bank: `channel:*`. Company bank: `industry:*`, `role:*`, `kind:*` so a brief pulls only relevant lessons |
| `entity_labels` | bank config | Controlled vocabulary extracted at retain as exact-match entities (never fuzzy-merged); can also write tags | `objection:price`, `objection:security`, `stage:negotiation`, `role:finance` → "all price objections" becomes an exact query, especially in `company` |
| `observation_scopes` | retain item | Which tag groups observations are built for (`combined` default, per-tag, or `shared`) | Company bank: per `industry` / `role` so conclusions form per segment |
| Consolidation strategies | bank config | Per-scope instructions for observations | Company bank: *"Record only generalised trends. Never name a specific company or person."* (the docs show this exact pattern) |
| Retain custom instructions / mission | bank config | What the extraction LLM looks for | Sales-specific instructions (the repo already sets `retain_custom_instructions`) |
| `enable_observations` | bank config | Consolidation on/off | On |

## 8. Cost check (Hindsight Cloud, $50 promo credit)

Prices (vectorize.io/pricing): retain $10 / 1M tokens, recall $0.75 / 1M, reflect $0.05 / call, storage
$0.25 / 1M tokens / month (first 30 days free). **No per-bank charge.**

| Item | Billed tokens (est.) | Cost |
|---|---|---|
| Short email / WhatsApp day / CRM note | ~2.4k (measured on our data, per README) | ~$0.024 |
| 30-min call transcript | ~18k (estimate: ~3× the text) | ~$0.18 |
| Company insights from one interaction | ~2.4k | ~$0.024 |
| One brief / chat (≈8 recalls over two banks) | ~32k recall | ~$0.03 |

One demo customer (3 calls + 12 short items + insights) ≈ **$1.20–1.55**; three customers ≈ **$5** per full
import. Five full re-imports during development + 300 questions ≈ **$35–40**: fits, but tight.

Keep it well under by developing against a **local self-hosted Hindsight** (Docker, our Groq key) and using Cloud
for the demo, re-retaining single documents by id instead of wiping banks, and keeping extracted facts in
metadata instead of a separate facts document. The tighter limit is Groq's free tier (~8k tokens per minute per
model, per the comment in `backend/sales_agent.py`), not the $50.

## Open

- Does Hindsight Cloud cap banks per account? Not checked.
- Do appended pieces keep their own timestamps? Not documented; test before relying on `append` for dates.
- Real cost of one long call transcript: retain one and read the usage in the Cloud console.

## Sources

- FAQ (per-user banks vs single bank with tags): https://hindsight.vectorize.io/faq
- Best practices (bank per user, `document_id` per session, tags, metadata not filterable, context):
  https://hindsight.vectorize.io/best-practices
- Per-user memory recipe: https://hindsight.vectorize.io/cookbook/recipes/per-user-memory
- Sales research guide (one bank per account):
  https://hindsight.vectorize.io/guides/2026/06/02/guide-hermes-sales-research-memory-with-hindsight
- Single vs multi bank: https://hindsight.vectorize.io/guides/2026/04/16/comparison-single-bank-vs-multi-bank-hindsight
- Full docs (retain parameters, `update_mode`, `retain_files` formats, entities, links, observation scopes,
  consolidation strategies, markitdown parser): https://hindsight.vectorize.io/llms-full.txt
- Pricing: https://vectorize.io/pricing
