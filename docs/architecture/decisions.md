# Decisions

Short log of what is decided, newest first. Details live in the linked docs.

## Decided (2026-09-28)

| # | Decision | Why / detail |
|---|---|---|
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

**To verify in code:** that Pydantic AI's Groq model (`pydantic-ai-slim[groq]==2.51.0`) sends
`response_format: json_schema` with `strict: true` when asked for native output. Not checked yet.

## Still to decide

| # | Question | Options / proposal |
|---|---|---|
| Q4 | Vercel env vars | Add `MONGODB_URI`, `MONGODB_DB`, `JWT_SECRET` (copy from the root `.env`) to the Vercel backend project before the first push that uses them. |
| Q5 | Atlas network access | Vercel has no fixed IPs; the Atlas access list must allow them (usually `0.0.0.0/0` for a hackathon). Connection from the dev machine works; from Vercel not checked. |
| Q7 | Demo logins | Two sales execs with different customers, to show the permission rule. Passwords set via a seed script, not committed. |

Resolved: Q1 → D1, Q2 → D8, Q3 → D9, Q6 → D10, Q8 → D11.
