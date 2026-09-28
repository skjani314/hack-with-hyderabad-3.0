"""Seed the demo: logins + customers in MongoDB, and every sample interaction through the real pipeline
(A2 parse → A3 extract + retain into the customer bank and the company bank).

    python seed_demo.py            # add whatever is missing (safe to re-run: duplicates are skipped)
    python seed_demo.py --reset    # delete the demo banks and Mongo collections first
    python seed_demo.py --only acme

Needs MONGODB_URI, MONGODB_DB, HINDSIGHT_API_KEY, GROQ_API_KEY and DEMO_PASSWORD (the password for every demo
login) in the root .env. Customers are seeded in file order, so later ones can use lessons learned from earlier ones.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv()

import memory_agent as agent  # noqa: E402
from auth import hash_password  # noqa: E402
from contracts import CustomerContext, Participant, RawInput  # noqa: E402
from db import database, ensure_indexes  # noqa: E402
from memory_agent import memory  # noqa: E402
from memory_agent.errors import AgentError, LLMRateLimited  # noqa: E402

DATA = Path(__file__).parent / "sample_data"


def people(spec: str, exec_name: str) -> list[Participant]:
    """'Kami Bicknell; Dana Whitfield (Engineering Manager)' → participants with sides."""
    out = []
    for part in [p.strip() for p in spec.split(";") if p.strip()]:
        name, _, role = part.partition("(")
        name = name.strip()
        out.append(Participant(name=name, role=role.rstrip(") "),
                               side="ours" if name.split()[0] == exec_name.split()[0] else "customer"))
    return out


def acme_interactions(exec_name: str) -> list[dict]:
    items = []
    for it in json.loads((DATA / "acme_import.json").read_text(encoding="utf-8"))["interactions"]:
        text = it["content"]
        if it["channel"] == "email":  # the export has headers as fields: rebuild a real email
            when = format_datetime(datetime.fromisoformat(it["date"]))
            text = f"From: {it.get('from', '')}\nTo: {it.get('to', '')}\nSubject: {it['title']}\nDate: {when}\n\n{text}"
        spec = it.get("participants") or it.get("from") or ""
        items.append(dict(channel=it["channel"], date=it["date"], title=it["title"], text=text,
                          participants=[p.model_dump() for p in people(spec, exec_name)] if spec else []))
    return items


async def with_retry(fn, *args):
    for attempt in range(8):
        try:
            return await fn(*args)
        except LLMRateLimited:
            wait = 20 + attempt * 10
            print(f"    Groq rate limit, waiting {wait}s")
            await asyncio.sleep(wait)
    raise RuntimeError("Groq stayed rate limited")


async def reset(spec: dict):
    db = database()
    async with memory.client() as hc:
        for c in spec["customers"]:
            for bank in (f"cust-{c['id']}",):
                try:
                    await hc.adelete_bank(bank_id=bank)
                    print("deleted bank", bank)
                except Exception as e:
                    if "404" not in str(e):
                        raise
        try:
            await hc.adelete_bank(bank_id=memory.COMPANY_BANK)
            print("deleted bank", memory.COMPANY_BANK)
        except Exception as e:
            if "404" not in str(e):
                raise
    for coll in ("users", "customers", "requests", "jobs"):
        await db[coll].delete_many({})
    print("cleared Mongo collections")


async def main():
    spec = json.loads((DATA / "demo_customers.json").read_text(encoding="utf-8"))
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        sys.exit("Set DEMO_PASSWORD in the root .env first")
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    if "--reset" in sys.argv:
        await reset(spec)
    db = database()
    await ensure_indexes()

    users = {}
    for u in spec["users"]:
        await db.users.update_one({"email": u["email"]}, {"$set": {
            "email": u["email"], "name": u["name"], "role": u["role"], "customer_ids": u["customer_ids"],
            "password_hash": hash_password(password), "active": True}}, upsert=True)
        users[u["email"]] = await db.users.find_one({"email": u["email"]})
        print("user", u["email"], u["role"])

    for c in spec["customers"]:
        if only and c["id"] != only:
            continue
        owner = users[c["owner"]]
        ctx = CustomerContext(customer_id=c["id"], bank_id=f"cust-{c['id']}", name=c["name"],
                              industry=c["industry"], exec_name=owner["name"])
        await db.customers.update_one({"_id": c["id"]}, {"$set": {
            "name": c["name"], "industry": c["industry"], "bank_id": ctx.bank_id,
            "owner_user_id": str(owner["_id"]), "status": "active"},
            "$setOnInsert": {"created_at": datetime.now().astimezone()}}, upsert=True)
        await agent.create_customer_memory(ctx)
        items = acme_interactions(owner["name"]) if c.get("from_file") else c["interactions"]
        print(f"\ncustomer {c['id']} ({len(items)} interactions) → bank {ctx.bank_id}")
        for it in items:
            raw = RawInput(kind="text", text=it["text"], channel=it["channel"], title=it["title"],
                           occurred_at=datetime.fromisoformat(it["date"]),
                           participants=[Participant(**p) for p in it.get("participants", [])])
            try:
                preview = await with_retry(agent.prepare_interaction, ctx, raw)
            except AgentError as e:
                print(f"  skip {it['title'][:50]}: {e.message}")
                continue
            for x in preview.interactions:  # seed dates come from the data, not from 'now'
                if it["channel"] != "whatsapp":
                    x.occurred_at = raw.occurred_at
            result = await with_retry(agent.ingest_interaction, ctx, preview.interactions)
            print(f"  {', '.join(result.remembered):28} lessons +{len(result.company_insights)}"
                  f" (rejected {result.rejected_insights}){'' if result.extraction_ok else '  EXTRACTION FAILED'}")
        await db.customers.update_one({"_id": c["id"]}, {"$unset": {"profile_cache": ""}})
    print("\ndone")


if __name__ == "__main__":
    asyncio.run(main())
