"""uvicorn main:app --reload   (run from backend/)"""
import json
import os
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import agent

HERE = Path(__file__).parent
SEED = json.loads((HERE.parent / "data" / "experiences.json").read_text())
# ponytail: in-process state; lost on restart (Hindsight keeps the memories). Add a DB if that matters.
pending, learned = {}, []

app = FastAPI(title="Machine Never Miss")
# Frontend lives on another origin in production (Vercel). Comma-separated list in ALLOWED_ORIGINS.
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Demo-Key"])


def demo_key(x_demo_key: str | None = Header(None)):
    # Keeps strangers from burning Hindsight credits on the public URL. Unset DEMO_KEY = open.
    if os.getenv("DEMO_KEY") and x_demo_key != os.getenv("DEMO_KEY"):
        raise HTTPException(401, "Wrong or missing demo key")


class Reading(BaseModel):
    machine_id: str = Field(min_length=1, max_length=20)
    variant: Literal["L", "M", "H"] = "M"
    air_temperature_k: float = Field(ge=280, le=330)
    process_temperature_k: float = Field(ge=280, le=340)
    rpm: int = Field(ge=500, le=4000)
    torque_nm: float = Field(ge=0, le=120)
    tool_wear_min: int = Field(ge=0, le=400)
    use_memory: bool = True


class Outcome(BaseModel):
    event_id: str
    action: str = Field(min_length=1, max_length=200)
    outcome: Literal["prevented_failure", "failed", "normal"]
    notes: str = Field("", max_length=500)


@app.get("/")
def health():
    return {"ok": True}


@app.post("/api/analyze", dependencies=[Depends(demo_key)])
def analyze(r: Reading):
    reading = r.model_dump(exclude={"use_memory"})
    try:
        d = agent.analyze(reading, use_memory=r.use_memory)
    except KeyError as e:
        raise HTTPException(503, f"Server missing config {e}; set it in backend/.env")
    except Exception as e:
        raise HTTPException(502, f"Hindsight memory error: {str(e)[:200]}")
    pending[d["event_id"]] = {k: d[k] for k in ("event_id", "reading", "status", "pattern")} | {"memory": r.use_memory}
    return d


@app.post("/api/outcome", dependencies=[Depends(demo_key)])
def outcome(o: Outcome):
    if o.event_id not in pending:
        raise HTTPException(404, "Unknown event_id; analyze the reading first")
    try:
        e, verdict = agent.learn(pending[o.event_id], o.action, o.outcome, o.notes)
    except Exception as ex:  # keep the event pending so the engineer can retry
        raise HTTPException(502, f"Hindsight memory error: {str(ex)[:200]}")
    del pending[o.event_id]
    learned.append(e | {"verdict": verdict})
    return {"retained": e["experience_id"], "verdict": verdict, "pattern": e["failure_mode"], "text": e["text"]}


@app.get("/api/playbooks")
def playbooks():
    try:
        return agent.get_playbooks()
    except Exception as e:
        raise HTTPException(502, f"Hindsight memory error: {str(e)[:200]}")


@app.get("/api/timeline")
def timeline():
    months = {}
    for e in SEED + learned:
        m = months.setdefault(e["timestamp"][:7], Counter())
        m[e["event_type"]] += 1
    return {"months": [{"month": k, **v} for k, v in sorted(months.items())],
            "learned": [{k: e[k] for k in ("experience_id", "timestamp", "outcome", "action_taken", "verdict")} for e in learned]}
