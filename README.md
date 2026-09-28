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
../.venv/Scripts/python seed.py           # load 369 experiences into Hindsight (~$0.35, once)
../.venv/Scripts/python seed.py --check   # recall a known dangerous reading
../.venv/Scripts/python -m uvicorn main:app --reload   # open http://localhost:8000
../.venv/Scripts/python test_agent.py     # decision logic check, no key needed
```

`USE_REFLECT=0` in `.env` skips Hindsight reflect ($0.05/call) while developing.

## How it decides

1. **Recall**: the reading is described in words ("small temperature gap, low spindle speed") and sent to Hindsight recall.
2. **Compare**: each recalled experience is compared to the current reading (`agent.SCALES`). Only close ones count.
3. **Decide**: most similar cases failed or nearly failed → **ESCALATE**; some → **MONITOR**; none → **NORMAL**. No memory → never invents history.
4. **Explain**: Hindsight reflect writes the "why", citing case ids.
5. **Learn**: the engineer records the outcome, it is retained, and the next similar reading uses it.

## Deploy (Render, one service)

Push to GitHub → Render → New → Blueprint → pick this repo (`render.yaml`). Set `HINDSIGHT_API_KEY` and `DEMO_KEY` (a password so strangers can't spend your credits). The free tier sleeps: open the URL a minute before the demo.
