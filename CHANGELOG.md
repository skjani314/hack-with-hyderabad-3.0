# Changelog

All notable changes to the Sales Memory Agent are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
  paraphrased correctly.
- Profile can list the same stakeholder more than once.
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
