"""The multi-customer API (docs/architecture/contracts.md §5).

The backend owns login, permissions, MongoDB and HTTP. Everything about memory and the LLM goes through the agent
package (`memory_agent`), which only ever receives an already-authorised CustomerContext.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

import memory_agent as agent
from memory_agent.prompts import DEFAULT_ORG_PROMPT, LOCKED_RULES, PIECES
from auth import can_see, check_password, current_user, customer_context, issue_token, require_admin, user_out
from contracts import (
    AssignIn, CustomerContext, CustomerDetail, CustomerIn, CustomerOut, IngestIn, Insight, InsightFilters,
    InteractionPreview, JobOut, Ledger, LoginIn, LoginOut, OrgSettings, OrgSettingsIn, Participant, Profile, PromptPiece,
    RawInput, Report, RequestIn,
    RequestOut,
    RequestRow, SourceText, UserOut,
)
from db import database

router = APIRouter(prefix="/api")
Ctx = Annotated[CustomerContext, Depends(customer_context)]
User = Annotated[dict, Depends(current_user)]
MAX_UPLOAD = 4 * 1024 * 1024  # Vercel rejects request bodies over 4.5 MB; longer calls use a recording URL


def now() -> datetime:
    return datetime.now(timezone.utc)


def customer_out(c: dict) -> CustomerOut:
    return CustomerOut(id=c["_id"], name=c["name"], industry=c["industry"], bank_id=c["bank_id"],
                       status=c.get("status", "active"), owner_user_id=c.get("owner_user_id"),
                       created_at=c.get("created_at"))


# ---------- auth ----------

@router.post("/auth/login", response_model=LoginOut)
async def login(body: LoginIn):
    u = await database().users.find_one({"email": body.email.strip().lower(), "active": True})
    if not u or not check_password(body.password, u.get("password_hash", "")):
        raise HTTPException(401, {"error": "bad_credentials", "message": "Wrong email or password"})
    return LoginOut(token=issue_token(str(u["_id"])), user=user_out(u))


@router.get("/auth/me", response_model=UserOut)
async def me(user: User):
    return user_out(user)


# ---------- customers ----------

@router.get("/customers", response_model=list[CustomerOut])
async def customers(user: User):
    q = {} if user.get("role") == "admin" else {"_id": {"$in": user.get("customer_ids", [])}}
    return [customer_out(c) async for c in database().customers.find(q).sort("name", 1)]


@router.post("/customers", response_model=CustomerOut)
async def create_customer(body: CustomerIn, user: User):
    db = database()
    existing = await db.customers.find_one({"_id": body.id})
    if existing and existing.get("status") == "active":
        raise HTTPException(409, {"error": "exists", "message": f"Customer '{body.id}' already exists"})
    doc = {"_id": body.id, "name": body.name, "industry": body.industry.strip().lower(),
           "bank_id": f"cust-{body.id}", "owner_user_id": str(user["_id"]), "status": "creating",
           "created_at": now()}
    # two stores: Mongo first as "creating", then the bank, then "active" (a failed bank step can be retried)
    await db.customers.replace_one({"_id": body.id}, doc, upsert=True)
    await db.users.update_one({"_id": user["_id"]}, {"$addToSet": {"customer_ids": body.id}})
    ctx = CustomerContext(customer_id=body.id, bank_id=doc["bank_id"], name=body.name, industry=doc["industry"],
                          exec_name=user["name"])
    await agent.create_customer_memory(ctx)
    await db.customers.update_one({"_id": body.id}, {"$set": {"status": "active"}})
    doc["status"] = "active"
    return customer_out(doc)


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
async def customer(ctx: Ctx):
    c = await database().customers.find_one({"_id": ctx.customer_id})
    return CustomerDetail(customer=customer_out(c), interactions=await agent.list_sources(ctx))


@router.get("/customers/{customer_id}/sources/{document_id}", response_model=SourceText)
async def source(document_id: str, ctx: Ctx):
    return SourceText(document_id=document_id, text=await agent.source_text(ctx, document_id))


# ---------- interactions ----------

@router.post("/customers/{customer_id}/interactions/preview", response_model=InteractionPreview)
async def preview(ctx: Ctx, text: str | None = Form(None), file: UploadFile | None = File(None),
                  recording_url: str | None = Form(None), channel: str | None = Form(None),
                  title: str | None = Form(None), occurred_at: str | None = Form(None),
                  participants: str | None = Form(None)):
    """Parse / transcribe an upload into Interactions for the salesperson to check. Writes nothing to memory."""
    data = await file.read() if file else None
    if data is not None and len(data) > MAX_UPLOAD:
        raise HTTPException(413, {"error": "too_large",
                                  "message": "Files over 4 MB can't be uploaded here. For a long call, paste the "
                                             "recording URL instead."})
    try:
        people = [Participant(**p) for p in json.loads(participants)] if participants else []
        raw = RawInput(kind="file" if file else "recording_url" if recording_url else "text", text=text,
                       file_name=file.filename if file else None, file_bytes=data, recording_url=recording_url,
                       channel=channel or None, title=title or None,
                       occurred_at=datetime.fromisoformat(occurred_at) if occurred_at else None,
                       participants=people)
    except (ValueError, ValidationError, TypeError) as e:
        raise HTTPException(422, {"error": "invalid_input", "message": str(e)[:300]})
    if raw.kind == "text" and not (text or "").strip():
        raise HTTPException(422, {"error": "invalid_input", "message": "Paste text, upload a file or give a URL"})
    return await agent.prepare_interaction(ctx, raw)


@router.post("/customers/{customer_id}/interactions", response_model=JobOut)
async def ingest(body: IngestIn, ctx: Ctx, user: User):
    """Extract + remember in both banks. Runs inside this request (Vercel functions stop when they respond);
    the job record keeps the result so the UI can re-read it."""
    db = database()
    prior = None
    if body.request_id:
        r = await db.requests.find_one({"_id": body.request_id, "customer_id": ctx.customer_id})
        prior = Report(**r["report"]) if r else None
    job_id = uuid.uuid4().hex[:12]
    await db.jobs.insert_one({"_id": job_id, "customer_id": ctx.customer_id, "user_id": str(user["_id"]),
                              "status": "running", "stage": "extracting", "created_at": now()})
    try:
        result = await agent.ingest_interaction(ctx, body.interactions, prior, await load_ledger(ctx.customer_id))
    except Exception as e:
        await db.jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "stage": "failed",
                                                            "error": getattr(e, "message", str(e))[:300]}})
        raise
    if result.ledger:
        await save_ledger(ctx.customer_id, result.ledger)
    await db.jobs.update_one({"_id": job_id}, {"$set": {"status": "done", "stage": "done",
                                                        "result": result.model_dump(mode="json")}})
    await db.customers.update_one({"_id": ctx.customer_id}, {"$unset": {"profile_cache": ""}})
    return JobOut(job_id=job_id, status="done", stage="done", result=result)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def job(job_id: str, user: User):
    j = await database().jobs.find_one({"_id": job_id})
    if not j or not can_see(user, j["customer_id"]):
        raise HTTPException(404, {"error": "not_found", "message": "No such job"})
    return JobOut(job_id=j["_id"], status=j["status"], stage=j["stage"], result=j.get("result"),
                  error=j.get("error"))


# ---------- requests (prompt → report) ----------

@router.get("/prompt-pieces", response_model=list[PromptPiece])
async def prompt_pieces(user: User):
    """The injectable prompt pieces the executive can add to a request (memory_agent/prompts.py)."""
    return [PromptPiece(**p.model_dump()) for p in PIECES]


@router.post("/customers/{customer_id}/requests", response_model=RequestOut)
async def create_request(body: RequestIn, ctx: Ctx, user: User):
    db = database()
    history: list[str] = []
    if body.parent_request_id:
        parent = await db.requests.find_one({"_id": body.parent_request_id, "customer_id": ctx.customer_id})
        if parent:
            history = [f"Salesperson: {parent['prompt']}", f"Assistant: {parent['report'].get('answer', '')}"]
    org = await db.settings.find_one({"_id": "org"}) or {}
    report = await agent.generate_report(ctx, body.prompt, history, body.pieces, org.get("main_prompt"),
                                         await load_ledger(ctx.customer_id))
    rid = uuid.uuid4().hex[:12]
    created = now()
    await db.requests.insert_one({"_id": rid, "customer_id": ctx.customer_id, "user_id": str(user["_id"]),
                                  "prompt": body.prompt, "pieces": report.pieces,
                                  "parent_request_id": body.parent_request_id,
                                  "report": report.model_dump(mode="json"), "created_at": created})
    return RequestOut(request_id=rid, customer_id=ctx.customer_id, prompt=body.prompt, created_at=created,
                      report=report)


@router.get("/customers/{customer_id}/requests", response_model=list[RequestRow])
async def list_requests(ctx: Ctx):
    cur = database().requests.find({"customer_id": ctx.customer_id}).sort("created_at", -1).limit(50)
    return [RequestRow(request_id=r["_id"], prompt=r["prompt"], created_at=r["created_at"],
                       summary=r["report"].get("summary", "")) async for r in cur]


@router.get("/customers/{customer_id}/requests/{request_id}", response_model=RequestOut)
async def get_request(request_id: str, ctx: Ctx):
    r = await database().requests.find_one({"_id": request_id, "customer_id": ctx.customer_id})
    if not r:
        raise HTTPException(404, {"error": "not_found", "message": "No such request"})
    return RequestOut(request_id=r["_id"], customer_id=r["customer_id"], prompt=r["prompt"],
                      created_at=r["created_at"], report=Report(**r["report"]))


# ---------- deal ledger ----------

async def load_ledger(customer_id: str) -> Ledger | None:
    doc = await database().ledgers.find_one({"_id": customer_id})
    return Ledger(**doc["ledger"]) if doc else None


async def save_ledger(customer_id: str, ledger: Ledger) -> None:
    await database().ledgers.replace_one({"_id": customer_id}, {"_id": customer_id,
                                                                "ledger": ledger.model_dump(mode="json")}, upsert=True)


@router.get("/customers/{customer_id}/ledger", response_model=Ledger)
async def get_ledger(ctx: Ctx):
    """The customer's current state: open and closed items and where each person stands."""
    return await load_ledger(ctx.customer_id) or Ledger()


@router.post("/customers/{customer_id}/ledger/rebuild", response_model=Ledger)
async def rebuild_ledger(ctx: Ctx):
    """Rebuild from every stored interaction in date order (existing customers, or after fixing old data)."""
    ledger = await agent.rebuild_ledger(ctx)
    await save_ledger(ctx.customer_id, ledger)
    return ledger


# ---------- profile + company insights ----------

@router.get("/customers/{customer_id}/profile", response_model=Profile)
async def profile(ctx: Ctx):
    """Cached on the customer record; any new interaction clears the cache."""
    db = database()
    c = await db.customers.find_one({"_id": ctx.customer_id}, {"profile_cache": 1})
    if c and c.get("profile_cache"):
        return Profile(**c["profile_cache"])
    p = await agent.get_profile(ctx)
    await db.customers.update_one({"_id": ctx.customer_id}, {"$set": {"profile_cache": p.model_dump(mode="json")}})
    return p


@router.get("/company/insights", response_model=list[Insight])
async def company_insights(user: User, industry: str | None = None, role: str | None = None,
                           kind: str | None = None):
    return await agent.list_company_insights(InsightFilters(industry=industry, role=role, kind=kind))


# ---------- organisation settings (the editable main prompt) ----------

def settings_out(doc: dict | None) -> OrgSettings:
    doc = doc or {}
    prompt = doc.get("main_prompt") or DEFAULT_ORG_PROMPT
    return OrgSettings(main_prompt=prompt, default_prompt=DEFAULT_ORG_PROMPT, is_default=prompt == DEFAULT_ORG_PROMPT,
                       locked_rules=LOCKED_RULES, placeholders=["{exec_name}", "{customer}", "{industry}"],
                       updated_by=doc.get("updated_by"), updated_at=doc.get("updated_at"))


@router.get("/settings", response_model=OrgSettings)
async def get_settings(user: User):
    return settings_out(await database().settings.find_one({"_id": "org"}))


@router.post("/settings", response_model=OrgSettings)
async def save_settings(body: OrgSettingsIn, admin: dict = Depends(require_admin)):
    """Admins edit the org's main prompt. Saving the default text again is the same as a reset."""
    doc = {"_id": "org", "main_prompt": body.main_prompt.strip(), "updated_by": admin["name"], "updated_at": now()}
    await database().settings.replace_one({"_id": "org"}, doc, upsert=True)
    return settings_out(doc)


# ---------- admin ----------

@router.post("/users/{user_id}/customers", response_model=UserOut)
async def assign(user_id: str, body: AssignIn, admin: dict = Depends(require_admin)):
    from bson import ObjectId
    if not ObjectId.is_valid(user_id):
        raise HTTPException(404, {"error": "not_found", "message": "No such user"})
    db = database()
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"customer_ids": body.customer_ids}})
    u = await db.users.find_one({"_id": ObjectId(user_id)})
    if not u:
        raise HTTPException(404, {"error": "not_found", "message": "No such user"})
    return user_out(u)
