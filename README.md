# Sales Memory Agent

**Remembers the customer so the salesperson doesn't have to.**

Sales conversations are scattered across CRM, email, calls and WhatsApp. This agent stores every conversation in
[Hindsight](https://hindsight.vectorize.io/) memory, extracts what matters (pain points, objections, stakeholders,
competitors, commitments, pricing), and answers the salesperson's questions from that memory, with every claim
linked to the message it came from. Record a call outcome and the next answer uses it.

## How Hindsight memory is used

| Step | Hindsight operation |
|---|---|
| Remember a conversation | `retain` with the source id, channel, date and a deal tag. The bank is configured with sales-specific extraction instructions (`retain_custom_instructions`). |
| Build the deal profile | `reflect` with a JSON response schema over the deal's memories |
| Answer a question | `reflect` scoped to the deal tag, citing source ids |
| Memory off (demo "before") | the same `reflect`, scoped to a tag no memory has, so the answer is generic |
| Record an outcome | `retain` as a new `OUT-xx` memory; later answers use it |

**Evidence gate (ours, not Hindsight's):** every profile item and answer citation must point to a message that is
actually in memory. Anything else is removed, and the UI says how many unsourced claims were dropped.

## Data

- **CRM:** real rows from the [Maven Analytics CRM Sales Opportunities](https://mavenanalytics.io/data-playground)
  dataset (a fictional B2B hardware company: 85 accounts, 8,800 opportunities). The deal is opportunity `S3W6Q07M`
  (Acme Corporation, GTX Plus Pro); account facts, sales agent, manager and Acme's 58 closed won/lost deals come from
  the CSVs. Dates are shifted into 2026.
- **Conversations:** emails, call transcripts and WhatsApp messages generated to fit that opportunity. All people
  are fictional.

`python backend/build_deal.py` downloads the dataset and writes `backend/acme_deal.json`.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/pip
cd backend
cp .env.example .env            # then set HINDSIGHT_API_KEY
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
| | | `HINDSIGHT_BANK` | `sales-memory` |
| | | `CLIENT_URL` | deployed frontend URL(s), comma-separated (CORS). Localhost is always allowed |
| | | `DEMO_KEY` | optional password so strangers can't spend credits |
| Frontend, local | `frontend/.env.local` (gitignored) | `VITE_API_URL` | `http://localhost:8000` |
| Frontend, prod | `frontend/.env.production` | `VITE_API_URL` | deployed backend URL |

## Deploy (Vercel, two projects from this repo)

1. **Backend:** New Project → this repo → Root Directory `backend` (FastAPI is detected from `main.py`).
   Set `HINDSIGHT_API_KEY`, `HINDSIGHT_BANK`, `CLIENT_URL` (the frontend URL) and optionally `DEMO_KEY`.
2. **Frontend:** New Project → this repo → Root Directory `frontend` (Vite is detected).
   Put the backend URL in `frontend/.env.production` (or set `VITE_API_URL` in Vercel).

## Demo (60 seconds)

1. Reset memory. Ask *"I have a call with Acme tomorrow. What should I focus on?"* The answer is generic.
2. Click **+ Next** a few times and ask again. The answer now knows the pain point and the account history.
3. **Remember all** and ask again. It flags the overdue security questionnaire, the finance controller's price
   pushback against Nexbyte, and the 30 September budget deadline, each with sources.
4. Record the outcome (*"Sent the questionnaire; Priya approved"*) and ask again. The advice moves on.

**Credits:** each remembered message costs ~2.4k tokens of retain (~$0.03); each question or profile refresh is one
reflect call (~$0.05).
