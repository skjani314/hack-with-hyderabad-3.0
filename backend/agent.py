"""Sales Memory Agent: conversations -> Hindsight memory -> deal profile + chat guidance -> outcomes.

Hindsight does the heavy lifting: retain extracts sales facts (bank is told what to look for),
reflect reasons over the deal memory. Our code adds the evidence gate: every claim must point
to a real source message, or it is dropped.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
BANK = os.getenv("HINDSIGHT_BANK", "sales-memory")
DEAL_FILE = Path(__file__).parent / "acme_deal.json"

RETAIN_INSTRUCTIONS = (
    "These are sales conversations (email, call transcripts, WhatsApp, CRM updates) about one B2B deal. "
    "Extract: customer pain points and goals; objections and who raised them; stakeholders with role and what "
    "each cares about; competitors and what was said about them; requirements; pricing and discount discussions; "
    "commitments with owner and due date; deadlines; call outcomes. Always keep the source id in square "
    "brackets (for example [EM-02]) and the date with each fact.")

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        section: {"type": "array", "items": {"type": "object", "properties": {
            **fields, "sources": {"type": "array", "items": {"type": "string"}}},
            "required": list(fields) + ["sources"]}}
        for section, fields in {
            "pain_points": {"text": {"type": "string"}},
            "objections": {"text": {"type": "string"}, "raised_by": {"type": "string"}, "status": {"type": "string"}},
            "stakeholders": {"name": {"type": "string"}, "role": {"type": "string"}, "cares_about": {"type": "string"}},
            "competitors": {"name": {"type": "string"}, "notes": {"type": "string"}},
            "commitments": {"text": {"type": "string"}, "owner": {"type": "string"}, "due": {"type": "string"},
                            "status": {"type": "string"}},
            "pricing": {"text": {"type": "string"}},
        }.items()
    },
    "required": ["pain_points", "objections", "stakeholders", "competitors", "commitments", "pricing"],
}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}},
    "required": ["answer", "sources"],
}

_client = None


def client():
    global _client
    if _client is None:
        from hindsight_client import Hindsight
        _client = Hindsight(base_url=os.getenv("HINDSIGHT_URL", "https://api.hindsight.vectorize.io"),
                            api_key=os.environ["HINDSIGHT_API_KEY"])
    return _client


def load_deal():
    return json.loads(DEAL_FILE.read_text(encoding="utf-8"))


def deal_tag(deal):
    return f"deal:{deal['deal']['deal_id'].lower()}"


# ---------- pure helpers (tested in test_agent.py) ----------

def item_text(deal, it):
    who = it.get("from") or it.get("participants")
    return (f"[{it['id']}] {it['channel'].upper()} on {it['date'][:10]} for deal {deal['deal']['deal_id']} "
            f"({deal['deal']['customer']}): {it['title']}." + (f" People: {who}." if who else "") +
            f"\n{it['content']}")


def to_retain_item(deal, it):
    return dict(content=item_text(deal, it), timestamp=it["date"], document_id=it["id"],
                context=f"{it['channel']} message {it['id']} in sales deal {deal['deal']['deal_id']}",
                metadata={"source_id": it["id"], "channel": it["channel"], "title": it["title"], "date": it["date"]},
                tags=[deal_tag(deal), f"channel:{it['channel']}"])


IDS = re.compile(r"\[([A-Z]+-\d+)\]")


def gate_profile(profile, known):
    """Evidence gate: keep only items citing at least one source the memory really holds."""
    out, dropped = {}, 0
    for section, items in profile.items():
        kept = []
        for item in items or []:
            srcs = sorted({s.strip("[] ") for s in item.get("sources", [])} & known)
            if srcs:
                kept.append(dict(item, sources=srcs))
            else:
                dropped += 1
        out[section] = kept
    return out, dropped


def gate_answer(answer, sources, known):
    """Remove citations to messages that are not in memory, from both the list and the text."""
    real = sorted({s.strip("[] ") for s in sources} & known)
    text = IDS.sub(lambda m: m.group(0) if m.group(1) in known else "", answer)
    cited = set(IDS.findall(text))
    return re.sub(r"\s{2,}", " ", text).strip(), sorted(set(real) | cited)


# ---------- Hindsight calls ----------

def ensure_bank():
    try:
        client().create_bank(
            bank_id=BANK, name="Sales Memory",
            mission="Remember every customer and deal conversation so salespeople get accurate, personalized guidance.",
            retain_custom_instructions=RETAIN_INSTRUCTIONS,
            reflect_mission="You are a sales assistant. Answer only from remembered deal history, cite source ids "
                            "like [EM-02], and say plainly when memory has no information.")
    except Exception:
        pass  # already exists


def ingest(deal, items):
    ensure_bank()
    client().retain_batch(bank_id=BANK, items=[to_retain_item(deal, it) for it in items])


def remembered_ids(deal):
    """Which source messages are in memory (asks Hindsight, so it survives restarts)."""
    ids, offset = set(), 0
    while True:
        try:
            page = client().list_memories(bank_id=BANK, limit=100, offset=offset)
        except Exception as e:
            if getattr(e, "status", None) == 404:
                return ids  # bank not created yet, or just reset: memory is empty
            raise
        items = page.items or []
        for m in items:
            d = m if isinstance(m, dict) else m.to_dict()
            if d.get("document_id"):
                ids.add(d["document_id"])
        if len(items) < 100:
            return ids
        offset += 100


def profile(deal, known):
    r = client().reflect(
        bank_id=BANK, budget="low", tags=[deal_tag(deal)], tags_match="any_strict", response_schema=PROFILE_SCHEMA,
        query=(f"Build the sales profile of deal {deal['deal']['deal_id']} ({deal['deal']['customer']}) from memory: "
               "pain points, objections (who raised, open or resolved), stakeholders (role, what they care about), "
               "competitors, commitments (owner, due date, done/open/overdue as of the latest message) and pricing "
               "discussions. For every item list the source ids like EM-02 it came from. Use only remembered facts."))
    return gate_profile(r.structured_output or {}, known)


def chat(deal, question, use_memory, known):
    # Memory off = same LLM, but filtered to a tag no memory has: the honest "before" of the demo.
    tags = [deal_tag(deal)] if use_memory else ["deal:none"]
    r = client().reflect(
        bank_id=BANK, budget="low", tags=tags, tags_match="any_strict", response_schema=CHAT_SCHEMA,
        query=(f"I am {deal['deal']['salesperson']} selling {deal['deal']['product']} to {deal['deal']['customer']}. "
               f"Question: {question}\nAnswer as my sales assistant in under 150 words, specific and actionable. "
               "Cite source ids like [EM-02] after each fact. If memory has nothing relevant, say so and give "
               "only generic advice. Never invent names, numbers or events."))
    out = r.structured_output or {"answer": r.text or "", "sources": []}
    return gate_answer(out.get("answer", ""), out.get("sources", []), known)


def record_outcome(deal, summary, result, next_step, n):
    it = dict(id=f"OUT-{n:02d}", channel="outcome", date=datetime.now(timezone.utc).isoformat(),
              title=f"Call outcome: {result}",
              content=f"Outcome recorded by the salesperson. Result: {result}. What happened: {summary}. "
                      f"Agreed next step: {next_step or 'none recorded'}.")
    ingest(deal, [it])
    return it
