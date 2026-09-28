# Machine Never Miss

AI maintenance agent that remembers machine near-misses and failures (via Hindsight) and escalates before a failure repeats.

## Data

`data/raw/ai4i2020.csv` is the [AI4I 2020 Predictive Maintenance Dataset](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset) (S. Matzka, UCI, CC BY 4.0).

`python backend/build_experiences.py` turns it into `data/experiences.json`, which is seeded into Hindsight:

- **failure**: rows the dataset labels as failed (heat dissipation, power, overstrain, tool wear, random)
- **near_miss**: rows within ~10% of a documented failure rule that did not fail
- **normal**: a sample of healthy rows

Actions, outcomes and machine IDs are not in the dataset. They are filled in from the failure mode.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/pip
cd backend
# put your key in backend/.env (HINDSIGHT_API_KEY=...)
../.venv/Scripts/python seed.py           # load 234 experiences + create 4 playbooks (~$5.5, once)
../.venv/Scripts/python seed.py --check   # recall a known dangerous reading
../.venv/Scripts/python -m uvicorn main:app --reload   # API on http://localhost:8000
../.venv/Scripts/python test_agent.py     # decision logic check, no key needed
```

Frontend (React + Vite + TypeScript + Tailwind), in a second terminal:

```bash
cd frontend
npm install
npm run dev        # open http://localhost:5173 (/api is proxied to :8000)
```

`USE_REFLECT=0` in `.env` skips Hindsight reflect ($0.05/call) while developing.

## How it decides

1. **Recall**: the reading is described in words ("small temperature gap, low spindle speed") and sent to Hindsight recall.
2. **Compare**: each recalled experience is compared to the current reading (`agent.SCALES`). Only close ones count.
3. **Decide**: most similar cases failed or nearly failed → **ESCALATE**; some → **MONITOR**; none → **NORMAL**. No memory → never invents history.
4. **Self-check**: the agent recalls its *own* graded past calls on similar readings. A past miss raises the level; repeated false alarms lower an escalation. The adjustment is shown with its reason.
5. **Explain**: Hindsight reflect writes the "why", citing case ids.
6. **Learn**: the engineer records the outcome. Two memories are retained: the outcome itself, and a self-review grading the agent's call in hindsight (caught / missed / false alarm / correct). The next similar reading uses both.
7. **Playbooks**: one Hindsight mental model per failure pattern (heat, power, overstrain, tool wear). Each rewrites itself after new memories are processed (`refresh_after_consolidation`), starting with the latest lessons and the agent's own decision record.

Live-learned outcomes are recalled with a separate tag-scoped query, so the large seeded archive never crowds out the newest lessons.

**Credits:** retain costs ~2.4k tokens (~$0.024) per memory, so seeding 234 experiences is ~$5.5. Each analysis is ~$0.05 with reflect; each recorded outcome retains 2 memories (~$0.05) and triggers one playbook refresh ($0.05).

## Deploy

**Backend (Render):** New → Blueprint → pick this repo (`render.yaml`). Set `HINDSIGHT_API_KEY` and `DEMO_KEY` (a password so strangers can't spend your credits). The free tier sleeps: open it a minute before the demo.

**Frontend (Vercel):** New Project → this repo → Root Directory `frontend` (Vite is auto-detected). `frontend/vercel.json` forwards `/api/*` to Render, so the browser only talks to Vercel and there is no CORS to configure. If your Render URL differs from `machine-never-miss.onrender.com`, change it in `vercel.json`.
