# Decisions

Short log of what is decided, newest first. Details live in the linked docs.

## Decided (2026-09-28)

| # | Decision | Why / detail |
|---|---|---|
| D20 | **Groq key rotation**: `GROQ_API_KEYS` (comma-separated). Every model is tried on every key, best model first (gpt-oss-120b on keys 1…n, then the smaller models); speech-to-text rotates too. | The free tier's **daily** cap (200,000 tokens per model per key) was hit in testing; per-minute checks had not shown it. |
| D19 | **Hindsight observations off for customer banks, on for the company bank.** | Observations had no source of their own and went stale after replacement; the ledger replaces them. [`deal-ledger.md`](./deal-ledger.md) |
| D18 | **Deal ledger** per customer (MongoDB `ledgers`): the current state, updated by one strict Groq call per upload, read first by every brief. Open items, objection status, stances and stage are set in code from it. | Briefs re-derived state from scattered facts and kept finished items open. [`deal-ledger.md`](./deal-ledger.md) |
| D17 | **Old single-deal code removed** (`agent.py`, `sales_agent.py`, old routes) once the v2 UI replaced it: two agents side by side is how drift starts. | CHANGELOG v2 |
| D16 | **Uploads ≤ 4 MB; long calls by recording URL.** Vercel caps request bodies at 4.5 MB; Groq's transcription API accepts `url=` and fetches the audio itself. Functions run up to 300 s (Hobby max). | Vercel functions limits doc; Groq SDK `transcriptions.create(url=…)` |
| D15 | **The org's main prompt lives in MongoDB (`settings/org`) and admins edit it on the Settings page.** The evidence rules are a separate locked block in code, because the evidence gate depends on them. Placeholders `{exec_name}`, `{customer}`, `{industry}`. | `memory_agent/prompts.py`, `POST /api/settings` |
| D14 | **Layered report prompt**: org main prompt + locked rules + prompt pieces the executive picks (one call type, any focus areas; catalog in `prompts.py`) + the executive's own question. | `memory_agent/prompts.py`, `GET /api/prompt-pieces` |
| D13 | **Every input is split, every output uses both banks.** Each new interaction goes through one structured extraction: customer-specific facts (and the source text) → the customer's bank; generalised, name-free lessons → `company`. Every report/answer recalls **both** banks, with the recall queries shaped by the exec's prompt and the company recall filtered by the customer's industry and stakeholder roles. | The core of the product. [`call-memory-pipeline.md`](./call-memory-pipeline.md) §2b, §4 |
| D12 | **Auth tokens:** JWT signed with `JWT_SECRET` (random 64-char string, generated into the root `.env`). The same value goes into the Vercel backend env. Rotating it logs everyone out. | [`auth-and-customer-directory.md`](./auth-and-customer-directory.md) |
| D11 | **We (this team) build the whole repo**; no parallel edit conflicts to plan for. | |
| D10 | **Groq free tier** is enough for the hackathon. Keep calls lean: prefetch recall, one structured LLM call per request. | |
| D9 | **Seed data:** Acme plus two more customers in other industries, so the company bank shows cross-customer lessons. | |
| D8 | **Calls arrive as MP3 recordings or as transcripts.** MP3 → Groq Whisper (`whisper-large-v3-turbo`, timestamped segments). Whisper has no speaker labels, so **the LLM assigns speakers** (ours vs customer, which person) from the segments and the participant list, as a strict Pydantic output; labels are marked inferred and editable in the preview. | No dual-channel audio available. |
| D1 | **Single branch: `main`. Push to `main` deploys** (CI/CD to Vercel). | Every push is live, so push only working, tested steps; keep the running demo working while rebuilding. |
| D2 | **LLM: Groq**, `openai/gpt-oss-120b` with fallbacks `qwen/qwen3.8-27b`, `openai/gpt-oss-20b`, via Pydantic AI (already in `backend/sales_agent.py`). | Brief recommends Groq; one key for LLM and speech-to-text. |
| D3 | **Structured input and output everywhere: Pydantic models, not free text.** Every LLM call that produces data uses Groq **strict structured outputs** (`strict: true`, constrained decoding), which guarantees the JSON matches the schema. All three models above support strict mode. | Replaces today's workaround of flat string lists (`CallPrep`), which existed because models renamed nested fields in best-effort mode. See rules below. |
| D4 | **MongoDB** (Atlas) for the directory: `users`, `customers`, `requests`, `jobs`. Database `devnathon-codewarriors-2026-zondabadh`. Connection in `MONGODB_URI` / `MONGODB_DB` in the root `.env` (gitignored), never in code or docs. | [`auth-and-customer-directory.md`](./auth-and-customer-directory.md) |
| D5 | **Hindsight: one bank per customer + one `company` bank; one document per interaction.** | [`hindsight-memory-shape.md`](./hindsight-memory-shape.md) |
| D6 | **Contracts:** 6 agent functions, 16 API endpoints, shared Pydantic types, TS types generated from OpenAPI. | [`contracts.md`](./contracts.md) |
| D7 | **Input channels:** call (audio / recording URL / transcript), email (`.eml` / paste), WhatsApp (export `.txt` / paste), CRM (CSV / note), documents (PDF, XLSX, DOCX, MD via markitdown). Manual upload for the POC. | [`call-memory-pipeline.md`](./call-memory-pipeline.md) |

### Rules for D3 (Groq strict mode)

From Groq's structured-outputs docs:

- Every property must be in `required`, and every object must set `additionalProperties: false`.
  → Pydantic models use `model_config = ConfigDict(extra="forbid")` and **no default values**.
- Optional fields are expressed as nullable (`str | None`), still required.
- Nested objects, arrays, enums (`Literal[...]`) and `anyOf` are supported.
- **Streaming and tool use are not supported together with structured outputs.** So a call that must return a
  schema does its memory reads **before** the LLM call (prefetch recall), not through tools during it. Tool
  loops, if kept, return text and are followed by a structured call.

**Verified** (2026-09-28, live request captured): `Agent(..., output_type=NativeOutput(Model, strict=True))` on
`pydantic-ai-slim[groq]==2.51.0` sends `response_format: {type: json_schema, strict: true}` and no tools, for
`openai/gpt-oss-120b` and `openai/gpt-oss-20b`. For `qwen/qwen3.8-27b` pydantic-ai's profile refuses native output,
so `memory_agent/llm.py` sets `supports_json_schema_output: True` on its profile; then it works too.
Groq free-tier limits on this key: 8,000 tokens/minute and 1,000 requests/day per model.

## Still to decide

| # | Question | Options / proposal |
|---|---|---|
| Q4 | Vercel env vars | Add `MONGODB_URI`, `MONGODB_DB`, `JWT_SECRET` (copy from the root `.env`) to the Vercel backend project before the first push that uses them. |
| Q5 | Atlas network access | Vercel has no fixed IPs; the Atlas access list must allow them (usually `0.0.0.0/0` for a hackathon). Connection from the dev machine works; from Vercel not checked. |
| Q7 | Demo logins | Two sales execs with different customers, to show the permission rule. Passwords set via a seed script, not committed. |

Resolved: Q1 → D1, Q2 → D8, Q3 → D9, Q6 → D10, Q8 → D11.
