"""Hindsight access: one bank per customer + one shared `company` bank.

Layout (docs/architecture/hindsight-memory-shape.md):
  cust-<id>   one document per interaction (CALL-07, EM-12, WA-2026-09-12 …), tagged channel:<c>
  company     one document per generalised insight (INS-…), tagged industry:<x>, role:<y>, kind:<k>
Hindsight builds facts, entities, links and observations bank-wide on its own.
"""
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

from contracts import SourceRow

from .errors import AgentError, ConfigMissing, MemoryUnavailable, NotFound

COMPANY_BANK = os.getenv("COMPANY_BANK", "company")

CUSTOMER_RETAIN_INSTRUCTIONS = (
    "These are sales interactions with one customer account (call transcripts, emails, WhatsApp chats, CRM notes, "
    "documents, call outcomes). Extract: pain points and goals; objections and who raised them; stakeholders with "
    "role and what each cares about; competitors and what was said about them; requirements; pricing and discount "
    "discussions; commitments with owner and due date; deadlines; decisions and call outcomes. Keep the source id in "
    "square brackets (for example [EM-02]) and the date with each fact.")

COMPANY_RETAIN_INSTRUCTIONS = (
    "These are generalised sales lessons learned across many customers: what worked, what failed, how to handle "
    "objections, buyer-role patterns, competitor intelligence, pricing patterns. Keep each lesson general. Keep the "
    "lesson id in square brackets (for example [INS-3fa2c1]).")

COMPANY_OBSERVATIONS_MISSION = (
    "Record only generalised, reusable sales patterns by industry and buyer role. Never name a specific customer "
    "company or person.")


@dataclass
class Fact:
    sources: list[str]   # document ids; an observation lists every document its source facts came from
    when: str
    text: str
    tags: list[str]

    def line(self) -> str:
        ids = "".join(f"[{s}]" for s in self.sources)
        # A fact with no traceable source is listed without an id, so it can never be cited.
        return " ".join(p for p in (ids, self.when, self.text) if p) if ids else f"- {self.text}"


def _not_found(e: BaseException) -> bool:
    return getattr(e, "status", None) == 404 or "404" in str(getattr(e, "status", ""))


@asynccontextmanager
async def client():
    """A Hindsight client for one request; its HTTP session belongs to the running event loop."""
    key = os.getenv("HINDSIGHT_API_KEY")
    if not key:
        raise ConfigMissing("HINDSIGHT_API_KEY is not set")
    from hindsight_client import Hindsight
    hc = Hindsight(base_url=os.getenv("HINDSIGHT_URL", "https://api.hindsight.vectorize.io"), api_key=key)
    try:
        yield hc
    except AgentError:
        raise  # already typed (LLM errors raised inside the block pass through unchanged)
    except Exception as e:
        raise MemoryUnavailable(f"Hindsight memory error: {str(e)[:250]}") from e
    finally:
        await hc.aclose()


async def bank_exists(hc, bank_id: str) -> bool:
    try:
        await hc.aget_bank_config(bank_id)
        return True
    except Exception as e:
        if _not_found(e):
            return False
        raise


async def ensure_bank(hc, bank_id: str) -> bool:
    """Create the bank with our configuration if missing. Returns True when it was created now."""
    if await bank_exists(hc, bank_id):
        return False
    company = bank_id == COMPANY_BANK
    await hc.acreate_bank(
        bank_id=bank_id,
        name="Company sales playbook" if company else f"Customer {bank_id}",
        mission=("Learn what works in selling across all customers." if company
                 else "Remember everything about this customer so the salesperson doesn't have to."),
        retain_custom_instructions=COMPANY_RETAIN_INSTRUCTIONS if company else CUSTOMER_RETAIN_INSTRUCTIONS,
        enable_observations=True,
        observations_mission=COMPANY_OBSERVATIONS_MISSION if company else None,
    )
    return True


async def retain(hc, bank_id: str, items: list[dict], wait: bool = True) -> None:
    """wait=False queues the work on Hindsight's side (retain_async) and returns at once."""
    if items:
        await hc.aretain_batch(bank_id=bank_id, items=items, retain_async=not wait)


async def recall(hc, bank_id: str, query: str, tags: list[str] | None = None, limit: int = 10,
                 budget: str = "mid", strict: bool = True) -> list[Fact]:
    """strict=True: only memories carrying one of `tags`. strict=False: those plus untagged memories
    (Hindsight `any` vs `any_strict`, docs: developer/api/recall)."""
    try:
        # include_source_facts: consolidated observations have no document of their own; their source facts do,
        # so we can cite the real messages behind an observation instead of letting the LLM guess an id.
        res = await hc.arecall(bank_id=bank_id, query=query, tags=tags or None,
                               tags_match="any_strict" if strict else "any", budget=budget, max_tokens=4096,
                               include_source_facts=True, max_source_facts_tokens=2048)
    except Exception as e:
        if _not_found(e):
            return []  # empty bank (new customer): nothing remembered yet
        raise
    out, seen = [], set()
    for r in res.results:
        if r.text in seen:
            continue
        seen.add(r.text)
        when = str(r.occurred_start or r.mentioned_at or "")[:10]
        if r.document_id:
            ids = [r.document_id]
        else:
            facts = [(res.source_facts or {}).get(fid) for fid in (r.source_fact_ids or [])]
            ids = sorted({f.document_id for f in facts if f is not None and f.document_id})
        out.append(Fact(ids, when, r.text, list(r.tags or [])))
    return out[:limit]


async def documents(hc, bank_id: str) -> list[dict]:
    """Every document in a bank as plain dicts (id, metadata, memory count). Empty list for a missing bank."""
    out, offset = [], 0
    while True:
        try:
            page = await hc.documents.list_documents(bank_id=bank_id, limit=100, offset=offset)
        except Exception as e:
            if _not_found(e):
                return []
            raise
        for d in page.items:
            d = d if isinstance(d, dict) else d.to_dict()
            out.append(d)
        if len(page.items) < 100:
            return out
        offset += 100


def source_row(d: dict) -> SourceRow:
    md = d.get("document_metadata") or {}
    return SourceRow(document_id=d["id"], channel=md.get("channel", "note"), title=md.get("title", d["id"]),
                     occurred_at=md.get("occurred_at", ""), people=md.get("people") or None,
                     memories=d.get("memory_unit_count"))


def fingerprints(docs: list[dict]) -> set[str]:
    """De-duplication keys stored on documents at retain time (metadata values are strings)."""
    keys = set()
    for d in docs:
        raw = (d.get("document_metadata") or {}).get("fingerprints", "")
        keys.update(k for k in raw.split(",") if k)
    return keys


async def document_text(hc, bank_id: str, document_id: str) -> str:
    try:
        d = await hc.documents.get_document(bank_id=bank_id, document_id=document_id)
    except Exception as e:
        if _not_found(e):
            raise NotFound(f"No source '{document_id}' in this customer's memory") from e
        raise
    return d.original_text or ""


def insight_from_doc(d: dict) -> dict:
    md = d.get("document_metadata") or {}
    return {"id": d["id"], "kind": md.get("kind", ""), "text": md.get("text", ""),
            "industry": md.get("industry") or None, "role": md.get("role") or None,
            "evidence": md.get("evidence", "observed_once"), "occurred_at": md.get("occurred_at", "")}


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
