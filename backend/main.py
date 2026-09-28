"""Sales Memory Agent API.   Local: uvicorn main:app --reload   (run from backend/)

Hindsight is the only source of truth: the deal, every conversation and every outcome are read from
the memory bank on each request. Stateless on purpose (Vercel serverless).
"""
import os
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import agent
import sales_agent
import sample_connector

app = FastAPI(title="Sales Memory Agent")
# CLIENT_URL: deployed frontend URL(s), comma-separated. Localhost is always allowed for development.
PROD_FRONTEND = "https://frontend-one-liart-v1r1f1weeq.vercel.app"  # public URL, safe default if CLIENT_URL is unset
origins = ["http://localhost:5173"] + [u.strip().rstrip("/") for u in os.getenv("CLIENT_URL", PROD_FRONTEND).split(",") if u.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "X-Demo-Key"])


def demo_key(x_demo_key: str | None = Header(None)):
    # Keeps strangers from spending Hindsight credits on the public URL. Unset DEMO_KEY = open.
    if os.getenv("DEMO_KEY") and x_demo_key != os.getenv("DEMO_KEY"):
        raise HTTPException(401, "Wrong or missing demo key")


def hs(fn, *args, **kw):
    """Run a Hindsight call and turn failures into a clear API error."""
    try:
        return fn(*args, **kw)
    except KeyError as e:
        raise HTTPException(503, f"Server missing config {e}; set HINDSIGHT_API_KEY in the backend environment")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Hindsight memory error: {str(e)[:200]}")


def current_deal():
    d = hs(agent.deal)
    if not d:
        raise HTTPException(409, "No deal in memory yet. Import the sample CRM data first.")
    return d


class NewSource(BaseModel):
    channel: Literal["email", "call", "whatsapp", "crm", "note"]
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=5, max_length=8000)
    people: str = Field("", max_length=300)


class Import(BaseModel):
    mode: Literal["next", "all"] = "next"


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
    src = hs(agent.sources)
    known = {s["id"] for s in src}
    return {"deal": hs(agent.deal) if agent.DEAL_DOC in known else None, "sources": src,
            "memory_count": len(src), "sample_remaining": len(sample_connector.pending(known))}


@app.get("/api/sources/{doc_id}")
def source(doc_id: str):
    return {"id": doc_id, "text": hs(agent.source_text, doc_id)}


@app.post("/api/sources", dependencies=[Depends(demo_key)])
def add_source(body: NewSource):
    it = hs(agent.add_source, current_deal(), body.channel, body.title, body.content, body.people)
    return {"remembered": it["id"]}


@app.post("/api/import", dependencies=[Depends(demo_key)])
def import_sample(body: Import):
    known = {s["id"] for s in hs(agent.sources)}
    ids = hs(sample_connector.import_items, known, 1 if body.mode == "next" else None)
    return {"remembered": ids}


@app.get("/api/profile", dependencies=[Depends(demo_key)])
def profile():
    known = {s["id"] for s in hs(agent.sources)}
    if not known:
        return {"profile": None, "dropped": 0}
    key = frozenset(known)
    if key not in _profile_cache:
        p, dropped = hs(agent.profile, current_deal(), known)
        _profile_cache.clear()
        _profile_cache[key] = {"profile": p, "dropped": dropped}
    return _profile_cache[key]


def llm(fn, *args, **kw):
    """Run the Groq agent; turn model/rate-limit failures into a clear message instead of a stack trace."""
    try:
        return fn(*args, **kw)
    except KeyError as e:
        raise HTTPException(503, f"Server missing config {e}; set GROQ_API_KEY and HINDSIGHT_API_KEY")
    except Exception as e:
        subs = [x for g in getattr(e, "exceptions", [e]) for x in getattr(g, "exceptions", [g])]
        if any("rate_limit" in str(x) or "413" in str(x) or "429" in str(x) or "over capacity" in str(x) for x in subs):
            raise HTTPException(429, "The LLM (Groq) is at its rate limit. Wait a minute and try again.")
        raise HTTPException(502, f"Agent error: {str(subs[0])[:200]}")


@app.post("/api/chat", dependencies=[Depends(demo_key)])
def chat(body: Chat):
    known = {s["id"] for s in hs(agent.sources)}
    dl = current_deal()
    answer, cited, trace = llm(sales_agent.ask, dl, body.question, set(known), body.use_memory)
    return {"answer": answer, "sources": cited, "trace": trace, "used_memory": body.use_memory,
            "memory_count": len(known)}


class Prep(BaseModel):
    goal: str = Field("", max_length=200)


@app.post("/api/prep", dependencies=[Depends(demo_key)])
def prep(body: Prep):
    """Call prep: insights, risks, stakeholder plays, objection handling, a call script and a follow-up email."""
    known = {s["id"] for s in hs(agent.sources)}
    return llm(sales_agent.call_prep, current_deal(), known, body.goal)


@app.post("/api/outcome", dependencies=[Depends(demo_key)])
def outcome(body: Outcome):
    content = (f"Outcome recorded by the salesperson. Result: {body.result}. What happened: {body.summary}. "
               f"Agreed next step: {body.next_step or 'none recorded'}.")
    it = hs(agent.add_source, current_deal(), "outcome", f"Call outcome: {body.result}", content)
    return {"remembered": it["id"]}


@app.delete("/api/memory", dependencies=[Depends(demo_key)])
def reset():
    """Wipe the memory bank so the before/after story can be shown again."""
    try:
        agent.client().delete_bank(bank_id=agent.BANK)
    except Exception as e:
        if not agent._not_found(e):
            raise HTTPException(502, f"Hindsight memory error: {str(e)[:200]}")
    _profile_cache.clear()
    return {"reset": True}
