# Changelog

All notable changes to the Sales Memory Agent are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Visual brief**: deal health + stage stepper, open items as a due-date timeline, stakeholder map
  (blocker → champion), objection → response flow, the call plan as a clickable 6-step flow, memory-mix bar.
  New structured fields: `deal_stage`, `deal_health`, `health_reason`, `stakeholders[].stance`,
  `open_items[]` = {text, owner, due, status, sources}, `call_plan` = {opening … close}.
- **Hover help** on every control (what "Get my brief" vs "Ask as follow-up" do, each prompt chip's exact text, …).
- Explicit **"Happened on"** date + time field; the preview shows an editable date, highlighted when it is today.

### Fixed
- **Briefs ignored the newest interaction.** Recall ranks by relevance, not date, so `CALL-04` (questionnaire
  received, support bundled instead of a discount) never reached the model and the brief repeated the old state.
  Every brief now reads the 3 newest interactions' summaries first, and the rules say a promise is not a delivery.
- **Wrong citations on merged facts.** Hindsight observations have no document of their own; they were listed without
  an id and the model borrowed a nearby one (`CRM-04` for a `WA-02` fact). Recall now requests
  `include_source_facts` and cites the documents behind each observation.
- **"10% discount agreed" when memory said "support plan instead of a discount".** Caused by the low reasoning effort
  introduced for rate limits; briefs now use medium effort (extraction and profile stay low).
- **Rate-limit errors.** An upload, the automatic profile refresh and a brief in one minute exhausted the 8k/min
  budget on all three models. (How Groq counts `max_tokens` and hidden reasoning against it is not in its docs.) Now: server waits for Groq's `retry-after`
  (≤ 25 s) and retries once; tighter `max_tokens`; the profile refreshes only on request; 413 (request too large) has
  its own message instead of being reported as a rate limit.
- **Briefs failed on production with "request too large" (413)** while the same brief worked locally: production's
  Groq key has a lower per-minute limit. Measured locally that Groq sizes a request by its prompt (a 6,529-token
  prompt with `max_tokens=3000` was accepted under an 8,000 limit), so the brief now reads Groq's
  `Limit X, Requested Y`, cuts the memory context by the overshoot and retries once. The newest interactions are
  trimmed last and from the old end, so the latest call survives. The error message now shows both numbers.
- **A pasted WhatsApp chat was saved as a note** (dated "now", one document). The paste arrived indented and
  hard-wrapped, and the WhatsApp line pattern was anchored at column 0, so only 1 of 11 lines matched. Lines are now
  stripped before matching, wrapped lines rejoin with a space, and two dated message lines are enough to detect a
  chat. Acme's misfiled `NOTE-01` was re-stored as `WA-2026-09-22/23/24`.
- **Call script was all "Opening".** Replaced by `call_plan` with one field per step, so the order is guaranteed by
  the strict schema.
- **Interaction saved with the wrong date** (29 Sep instead of the 18th entered). The backend keeps a sent date
  correctly (verified locally and on production); the old combined date-time field was the likely cause. Replaced,
  and `CALL-04` in Acme's memory re-saved with 18 Sep.
- **Times shown 5.5 h off in India**: MongoDB returned naive datetimes; the client is now `tz_aware`.
- Profile listed the same stakeholder repeatedly and repeated each item as its own detail: de-duplicated.
- Open items could cite company lessons: now customer sources only.
- Timeline and "newest" sorting compared dates as strings across UTC offsets: now compared as instants.
- Malformed token or user id returned 500 (now 401 / 404); a missing source returned 502 (now 404); ids sent back
  from the browser are validated (an `INS-…` id is rejected); audio de-duplication used file size instead of a hash.

### Known issues
- After a document is replaced, Hindsight's merged observations are rebuilt in the background; for a short while
  recall can return observations dated from the old version.

## 2026-09-28 — v2: multi-customer memory agent

### Added
- **Two memories.** One Hindsight bank per customer (`cust-<id>`) plus a shared `company` playbook bank. Every
  interaction goes through one Groq extraction that splits customer facts (→ customer bank, with the source text)
  from generalised lessons (→ company bank). Lessons naming the customer or its people are withheld.
- **Briefs from both banks**: prompt → recall customer bank (3 angles) + company bank (same industry, then all) →
  one Groq call → cited `Report`. Evidence gate drops unsourced claims.
- **Learning loop**: an interaction linked to an earlier brief yields `what_worked` / `what_failed` lessons marked
  `confirmed_outcome`.
- **Inputs**: pasted text, call MP3 (Groq Whisper + LLM speaker labels, editable in the preview), recording URL,
  `.eml`, WhatsApp export (Android + iOS formats, per-day documents, de-duplicated, appended), CRM `.csv`,
  PDF / DOCX / XLSX / PPTX (markitdown). Preview → confirm → remember.
- **Layered prompt**: org main prompt (MongoDB, editable by admins on the Settings page) + locked evidence rules +
  prompt pieces the executive picks (call type, focus) + their question.
- **Login and permissions**: MongoDB `users` / `customers`, bcrypt + JWT, server-side check that the customer is
  assigned to the user, bank id looked up server-side.
- **Structured output**: every LLM call returns a Pydantic model via Groq strict structured outputs
  (`NativeOutput(strict=True)`); qwen fallback needs a profile override to enable it.
- `backend/contracts.py`, `memory_agent/` package (contracts A1–A6), `api_v2.py` (16 endpoints),
  `seed_demo.py` (3 logins, 3 customers, 20 interactions), `test_memory_agent.py` (offline).
- Frontend rebuilt: login, customer list + create, customer page (timeline, add to memory, ask with prompt pieces,
  report, profile), company playbook, settings. TS types generated from OpenAPI (`npm run gen:api`).

### Changed
- `vercel.json` `maxDuration` 120 → 300 (Hobby maximum). Company-bank retains are queued (`retain_async`); ingest of
  one item ≈ 15 s.

### Removed
- Single-deal code: `agent.py`, `sales_agent.py`, `sample_connector.py`, `seed.py`, `test_agent.py` and the old
  `/api/deal`, `/api/chat`, `/api/prep`, … routes. The old `sales-memory` Hindsight bank is no longer used.

### Fixed
- The frontend/backend drift in call prep (below) is gone: the frontend's types are generated from the API schema.

### Known issues
- Report accuracy: in testing the LLM once called a requested delivery slot "confirmed" and once listed an
  already-delivered cost comparison as open. The evidence gate checks citations, not whether a cited fact is
  paraphrased correctly. (Partly addressed in Unreleased: newest interactions first, promise ≠ delivery.)
- Profile can list the same stakeholder more than once. (Fixed in Unreleased.)
- The UI was built and type-checked but not clicked through in a browser in this session (the browser automation
  could not reach localhost); every endpoint it calls was tested over HTTP.

## Planning (2026-09-28)

### Added
- `CHANGELOG.md` and a `docs/` folder for planning and design notes.
- `docs/resources/hindsight.md`: what Hindsight is, how this repo uses it, and the official doc/repo links.
- `docs/architecture/call-memory-pipeline.md`: proposed input → processing → memory → output design (audio or
  transcript upload, Groq Whisper + LLM extraction, per-customer and company Hindsight banks, pre-call brief).
  Extended to all channels: WhatsApp chat export, `.eml` email, CRM CSV, call recording URL (MCube); speaker
  separation options; smart drop zone with preview/confirm and de-duplication; polling instead of websockets;
  webhook path to production connectors.
- `docs/architecture/hindsight-memory-shape.md`: bank per customer + `company` bank, one document per
  conversation, what lives at bank vs document level, retain fields, inject API parameters, tags / entity labels /
  observation scopes, and the $50 credit cost check, with Hindsight FAQ and best-practice sources.
- `docs/architecture/auth-and-customer-directory.md`: MongoDB `users` (sales execs, permissions) and `customers`
  (customer id → Hindsight bank id); login → customer list → prompt → agent report → call flow; server-side
  permission and bank lookup rules.
- `docs/architecture/contracts.md`: 6 agent contracts (backend → agent) and 16 API contracts (frontend → backend),
  shared Pydantic types, error mapping, Vercel 120 s limit and job options, mapping from today's endpoints.

- `docs/architecture/decisions.md`: decided (push = deploy, Groq, Pydantic + Groq strict structured outputs,
  MongoDB directory, bank-per-customer, contracts, input channels) and still-open questions.
- MongoDB connection settings (`MONGODB_URI`, `MONGODB_DB`) added to the root `.env` (gitignored).

### Found
- Frontend/backend drift in call prep: `frontend/src/api.ts` `CallPrep` expects `why_it_matters`,
  `how_to_win_them` and `objections[].raised_by`, which `backend/sales_agent.py` `gate_prep` does not return.
  Not fixed yet; the contracts doc proposes generating TS types from the OpenAPI schema.

## 2026-09-28 — Sales Memory Agent baseline

### Changed
- Hindsight is the only source of truth: the deal record, every conversation and every outcome are Hindsight
  documents; the API keeps no store of its own. Conversations can be added from the UI. (`6946978`)
- Pivoted from "Machine Never Miss" to the Sales Memory Agent: one Acme deal built from the Maven Analytics CRM
  dataset plus generated email, call and WhatsApp conversations, retained into Hindsight; profile and chat via
  `reflect` with an evidence gate on citations. (`97d8bb2`)

### Earlier (Machine Never Miss prototype, superseded)
- Agent learns from its own mistakes and writes pattern playbooks. (`e39e628`)
- Frontend moved to React + Vite + TypeScript + Tailwind. (`0303d51`)
- Near-miss memory agent MVP on Hindsight. (`0f61cf7`)
