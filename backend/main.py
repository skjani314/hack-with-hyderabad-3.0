"""Sales Memory Agent API.   Local: uvicorn main:app --reload   (run from backend/)

Stateless on purpose (Vercel serverless): what is remembered is always read back from Hindsight.
"""
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import agent

app = FastAPI(title="Sales Memory Agent")
# CLIENT_URL: deployed frontend URL(s), comma-separated. Localhost is always allowed for development.
origins = ["http://localhost:5173"] + [u.strip().rstrip("/") for u in os.getenv("CLIENT_URL", "").split(",") if u.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "X-Demo-Key"])


def demo_key(x_demo_key: str | None = Header(None)):
    # Keeps strangers from spending Hindsight credits on the public URL. Unset DEMO_KEY = open.
    if os.getenv("DEMO_KEY") and x_demo_key != os.getenv("DEMO_KEY"):
        raise HTTPException(401, "Wrong or missing demo key")


def hindsight(fn, *args):
    """Run a Hindsight call and turn failures into a clear API error."""
    try:
        return fn(*args)
    except KeyError as e:
        raise HTTPException(503, f"Server missing config {e}; set it in backend/.env")
    except Exception as e:
        raise HTTPException(502, f"Hindsight memory error: {str(e)[:200]}")


class Ingest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=50)


class Chat(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    use_memory: bool = True


class Outcome(BaseModel):
    summary: str = Field(min_length=3, max_length=1000)
    result: str = Field(min_length=2, max_length=60)
    next_step: str = Field("", max_length=300)


_profile_cache: dict = {}  # per warm instance only; keyed by what memory holds, so never stale


@app.get("/")
def health():
    return {"ok": True, "service": "sales-memory-agent"}


@app.get("/api/deal")
def deal():
    d = agent.load_deal()
    known = hindsight(agent.remembered_ids, d)
    outcomes = sorted(i for i in known if i.startswith("OUT-"))
    return {"deal": d["deal"],
            "interactions": [dict(it, remembered=it["id"] in known) for it in d["interactions"]],
            "outcomes": outcomes, "memory_count": len(known)}


@app.post("/api/ingest", dependencies=[Depends(demo_key)])
def ingest(body: Ingest):
    d = agent.load_deal()
    by_id = {it["id"]: it for it in d["interactions"]}
    unknown = [i for i in body.ids if i not in by_id]
    if unknown:
        raise HTTPException(404, f"Unknown message ids: {', '.join(unknown)}")
    hindsight(agent.ingest, d, [by_id[i] for i in body.ids])
    return {"remembered": body.ids}


@app.get("/api/profile", dependencies=[Depends(demo_key)])
def profile():
    d = agent.load_deal()
    known = hindsight(agent.remembered_ids, d)
    if not known:
        return {"profile": None, "dropped": 0}
    key = frozenset(known)
    if key not in _profile_cache:
        p, dropped = hindsight(agent.profile, d, known)
        _profile_cache.clear()
        _profile_cache[key] = {"profile": p, "dropped": dropped}
    return _profile_cache[key]


@app.post("/api/chat", dependencies=[Depends(demo_key)])
def chat(body: Chat):
    d = agent.load_deal()
    known = hindsight(agent.remembered_ids, d) if body.use_memory else set()
    answer, sources = hindsight(agent.chat, d, body.question, body.use_memory, known)
    return {"answer": answer, "sources": sources, "used_memory": body.use_memory, "memory_count": len(known)}


@app.post("/api/outcome", dependencies=[Depends(demo_key)])
def outcome(body: Outcome):
    d = agent.load_deal()
    n = len([i for i in hindsight(agent.remembered_ids, d) if i.startswith("OUT-")]) + 1
    it = hindsight(agent.record_outcome, d, body.summary, body.result, body.next_step, n)
    return {"remembered": it["id"], "item": it}


@app.delete("/api/memory", dependencies=[Depends(demo_key)])
def reset():
    """Wipe the demo memory so the before/after story can be shown again."""
    hindsight(agent.client().delete_bank, agent.BANK)
    _profile_cache.clear()
    return {"reset": True}
