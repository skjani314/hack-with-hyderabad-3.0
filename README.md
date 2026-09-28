# Sales Memory Agent

**Remembers the customer so the salesperson doesn't have to.**

Sales conversations are scattered across CRM, email, calls and WhatsApp. This agent stores every conversation in
[Hindsight](https://hindsight.vectorize.io/) memory, extracts what matters (pain points, objections, stakeholders,
competitors, commitments, pricing), and answers the salesperson's questions from that memory, with every claim
linked to the message it came from. Record a call outcome and the next answer uses it.

## How Hindsight memory is used

**Hindsight is the only source of truth.** The deal record, every conversation and every outcome are documents in
the `sales-memory` bank; the API reads them back from Hindsight on every request and keeps no database of its own.

| Step | Hindsight operation |
|---|---|
| Remember a conversation (paste, connector import, or outcome) | `retain` with the source id, channel, date and a deal tag. The bank is configured with sales-specific extraction instructions (`retain_custom_instructions`). |
| Show what memory holds | `list_documents` / `get_document` (original text) |
| Build the deal profile | `reflect` with a JSON response schema over the deal's memories |
| Answer a question / prepare a call | the agent: `recall` prefetch + recall/read tools (below) |
| Record an outcome | `retain` as a new `OUT-xx` memory; later answers use it |

**Evidence gate (ours, not Hindsight's):** every profile item and answer citation must point to a message that is
actually in memory. Anything else is removed, and the UI says how many unsourced claims were dropped.

## The agent

A **Groq LLM** (`openai/gpt-oss-120b`, falling back to `qwen/qwen3.8-27b` and `openai/gpt-oss-20b`) built with
**[Pydantic AI](https://ai.pydantic.dev/)**, one of Hindsight's officially integrated agent frameworks.

- **Why an LLM:** Hindsight recall returns separate facts. Turning them into a prioritised plan and a natural talk
  track for each stakeholder is reasoning and writing.
- **Memory prefetch:** before the LLM runs, the relevant facts are recalled from Hindsight (and the conversation list
  is loaded), so the agent usually answers in one step. This keeps a run inside Groq's free-tier token limits.
- **Tools the agent can choose:** `recall_memory` (source-aware: every fact keeps its `[EM-02]` id), `read_source`
  (original message text), `save_note` (when the salesperson says "remember that…"). The stock Hindsight tool drops
  source ids, which the evidence gate needs, so these are built on the Hindsight client.
- **Typed outputs:** chat answers, and a **call prep** with insights, risks, stakeholder plays, objection handling,
  a call script, next steps and a follow-up email.
- **Memory trace:** every answer shows what the agent recalled and read ("🧠 Agent memory work").
- **Memory off** (demo "before"): the same LLM with no memory at all, so the answer is generic.

## Data

- **CRM:** real rows from the [Maven Analytics CRM Sales Opportunities](https://mavenanalytics.io/data-playground)
  dataset (a fictional B2B hardware company: 85 accounts, 8,800 opportunities). The deal is opportunity `S3W6Q07M`
  (Acme Corporation, GTX Plus Pro); account facts, sales agent, manager and Acme's 58 closed won/lost deals come from
  the CSVs. Dates are shifted into 2026.
- **Conversations:** emails, call transcripts and WhatsApp messages generated to fit that opportunity. All people
  are fictional.

`python backend/build_deal.py` downloads the dataset and writes the import file `backend/sample_data/acme_import.json`.
That file is read only by `sample_connector.py`, which stands in for real CRM / Gmail / WhatsApp connectors: it
**imports into Hindsight** (UI buttons *+ Next* / *Import all*, or `python seed.py`). The agent never reads it.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/pip
cd backend
cp .env.example .env            # then set HINDSIGHT_API_KEY
../.venv/Scripts/python seed.py --reset                  # optional: fresh bank + import the sample deal
../.venv/Scripts/python -m uvicorn main:app --reload     # http://localhost:8000
../.venv/Scripts/python test_agent.py                    # evidence gate checks, no key needed
```

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173, uses VITE_API_URL from .env.local
```

## Environment

| Where | File | Variable | Value |
|---|---|---|---|
| Backend, local | `backend/.env` (gitignored) | `HINDSIGHT_API_KEY` | your Hindsight Cloud key |
| | | `GROQ_API_KEY` | your Groq key |
| | | `HINDSIGHT_BANK` | `sales-memory` |
| | | `CLIENT_URL` | deployed frontend URL(s), comma-separated (CORS). Localhost is always allowed |
| | | `DEMO_KEY` | optional password so strangers can't spend credits |
| Frontend, local | `frontend/.env.local` (gitignored) | `VITE_API_URL` | `http://localhost:8000` |
| Frontend, prod | `frontend/.env.production` | `VITE_API_URL` | deployed backend URL |

## Deploy (Vercel, two projects from this repo)

1. **Backend:** New Project → this repo → Root Directory `backend` (FastAPI is detected from `main.py`).
   Set `HINDSIGHT_API_KEY`, `GROQ_API_KEY`, `HINDSIGHT_BANK` and optionally `DEMO_KEY` (`CLIENT_URL` defaults to the
   deployed frontend URL).
2. **Frontend:** New Project → this repo → Root Directory `frontend` (Vite is detected).
   Put the backend URL in `frontend/.env.production` (or set `VITE_API_URL` in Vercel).

## Demo (60 seconds)

1. Reset memory, click **+ Next** once (the CRM record) and ask *"I have a call with Acme tomorrow. What should I focus on?"* Also try it with memory off: generic.
2. Click **+ Next** a few times and ask again. The answer now knows the pain point and the account history.
3. **Remember all** and ask again. It flags the overdue security questionnaire, the finance controller's price
   pushback against Nexbyte, and the 30 September budget deadline, each with sources.
4. Paste a new email (e.g. Priya approving the questionnaire) or record the outcome (*"Sent the questionnaire; Priya approved"*) and ask again. The advice moves on.

5. Click **Prepare my call**: insights, risks, stakeholder plays, objection handling and a script, each line with
   its sources; open "🧠 Agent memory work" to show what it recalled.

**Credits:** each remembered message costs ~2.4k tokens of retain (~$0.03); a profile refresh is one reflect call
(~$0.05); agent answers use Hindsight recall (cheap) plus Groq.
