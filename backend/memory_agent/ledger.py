"""The deal ledger: each customer's current state, kept up to date as interactions arrive.

Recall returns history as scattered facts, so a brief that works out the current state from them each time can let an
old promise ("I will send the questionnaire") outweigh the one line that closed it. The ledger is the summary page on
top of the pile: on every upload a strict Groq call reads the CURRENT ledger plus the NEW interactions and returns
the updated ledger — items closed, added, reworded, people's stances moved — each line citing the messages behind
it. Briefs read it first. Docs: docs/architecture/deal-ledger.md
"""
import re
from datetime import datetime, timezone

from contracts import CustomerContext, Ledger, LedgerItem, LedgerPerson, LedgerUpdate, TraceStep

from . import llm

INSTRUCTIONS = """You maintain the deal ledger for {customer}: the CURRENT state of the deal, not its history.
Our company's people (side "ours"): {team}, plus anyone the messages show working for us (for example our
salesperson's manager or colleagues: "I spoke with my manager, Summer"). Everyone else is on the customer's side.

You get the CURRENT LEDGER and NEW INTERACTIONS (each with its id and date, oldest first). Return the whole ledger
after applying them:
- Keep every existing item's id. Change its status or wording only when a new interaction shows the change.
- A promise is not a delivery: "I will send X" keeps X open until a message says it was sent, received or approved.
  Mark done/resolved only on that evidence, and add that interaction's id to the item's sources.
- When a request is replaced by something else (e.g. a discount replaced by bundled support), mark the old item
  dropped or resolved and add the new arrangement.
- Add new commitments with owner and due date (YYYY-MM-DD), new objections, requirements, risks and decisions.
- People: one entry per person, stance from their LATEST position. Our own people are side "ours". Stances:
  blocker = said no, or is actively stopping the deal; skeptic = has an unresolved objection; neutral = waiting on
  something before deciding ("I can approve once the docs arrive"); supporter = positive about the deal;
  champion = actively pushing for it inside their company.
- Only facts from the interactions. Never invent names, dates, numbers or approvals.
- Before answering, go through EVERY open item one by one and ask: does any new interaction show it happened,
  was accepted, was delivered or no longer applies? Evidence is often indirect — "your 3-year comparison shows…"
  means the comparison was delivered; "the support bundle works for finance" resolves the price objection;
  "delivery date is fine for procurement" confirms the delivery slot. Close those items and cite the interaction.
- Merge duplicates: two items about the same deliverable become one.
Keep text short: one sentence per item."""

# New-interaction text per call. Small on purpose: with six messages in one call the model skimmed and missed
# closings; one or two per call is slower on a rebuild but each message gets read.
MAX_BATCH_TOKENS = 1200


def _norm(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def is_ours(name: str, team: list[str]) -> bool:
    """Full name or first name matches one of our people."""
    n = _norm(name)
    first = n.split(" ")[0] if n else ""
    for t in team:
        tn = _norm(t)
        if n and (n == tn or first == tn.split(" ")[0]):
            return True
    return False


def render(ledger: Ledger | None) -> str:
    if not ledger or not (ledger.items or ledger.people):
        return "(empty: nothing recorded yet)"
    lines = [f"Stage: {ledger.stage}. {ledger.summary}".strip()]
    for i in ledger.items:
        extra = " · ".join(x for x in (f"owner {i.owner}" if i.owner else "", f"due {i.due}" if i.due else "") if x)
        lines.append(f"{i.id} [{i.kind}] {i.status}{' · ' + extra if extra else ''} · {i.text} "
                     f"({', '.join(i.sources)})")
    for p in ledger.people:
        lines.append(f"PERSON {p.name} ({p.role or 'role unknown'}) · {p.side} · {p.stance} · {p.position} "
                     f"({', '.join(p.sources)})")
    return "\n".join(lines)


def _next_id(existing: set[str]) -> str:
    nums = [int(m.group(1)) for i in existing if (m := re.fullmatch(r"L-(\d+)", i or ""))]
    return f"L-{max(nums, default=0) + 1:02d}"


def merge(old: Ledger | None, upd: LedgerUpdate, known: set[str], team: list[str]) -> Ledger:
    """Apply the LLM's ledger to the stored one. Code, not the prompt, guarantees: ids stay stable, an item the model
    forgot is kept unchanged (never silently deleted), sources exist in memory, our people are never customers."""
    canon = {k.upper(): k for k in known}
    gate = lambda ids: [canon[u] for i in ids if (u := i.strip("[] ").upper()) in canon]  # noqa: E731
    before = {i.id: i for i in (old.items if old else [])}
    items, seen = [], set()
    for it in upd.items:
        it.sources = list(dict.fromkeys(gate(it.sources)))
        prev = before.get(it.id or "")
        if prev is None:
            if not it.sources:
                continue  # a new item with no real source is not recorded
            it.id = _next_id(set(before) | {i.id for i in items})
        elif not it.sources:
            it.sources = prev.sources  # updated wording, no new evidence: keep the evidence it had
        if it.id in seen:
            continue
        seen.add(it.id)
        items.append(it)
    items += [i for iid, i in before.items() if iid not in seen]  # forgotten by the model: kept as they were
    _close_duplicates(items)
    old_people = {_norm(p.name): p for p in (old.people if old else [])}
    people, seen_p = [], set()
    for p in upd.people:
        key = _norm(p.name)
        if not key or key in seen_p:
            continue
        p.sources = list(dict.fromkeys(gate(p.sources))) or (old_people[key].sources if key in old_people else [])
        if is_ours(p.name, team):
            p.side = "ours"
        seen_p.add(key)
        people.append(p)
    people += [p for k, p in old_people.items() if k not in seen_p]
    return Ledger(summary=upd.summary, stage=upd.stage, items=items, people=people,
                  based_on=(old.based_on if old else []), updated_at=datetime.now(timezone.utc))


STOP = {"the", "a", "an", "to", "and", "of", "for", "with", "by", "on", "in", "send", "provide", "deliver", "complete",
        "completed", "return", "acme", "kami", "priya", "michael", "sam", "dana"}


def _words(text: str) -> set[str]:
    # crude stem (first 6 letters) so "completed"/"complete" and "questionnaire"/"questionnaires" match
    return {w[:6] for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def _close_duplicates(items: list[LedgerItem]) -> None:
    """An open item that says the same thing as a finished one is the same deliverable recorded twice (the model
    was told to merge duplicates and did not always): close it with the finished item's evidence."""
    finished = [i for i in items if i.status in ("done", "resolved")]
    for it in items:
        if it.status not in ("open", "overdue", "at_risk"):
            continue
        w = _words(it.text)
        for f in finished:
            fw = _words(f.text)
            if w and fw and len(w & fw) / len(w | fw) >= 0.5:
                it.status, it.sources = f.status, list(dict.fromkeys(it.sources + f.sources))
                break


def _batches(interactions: list[tuple[str, str, str]]) -> list[list[tuple[str, str, str]]]:
    out, cur, used = [], [], 0
    for doc_id, date, text in interactions:
        text = text[: MAX_BATCH_TOKENS * 4]
        t = llm.approx_tokens(text)
        if cur and used + t > MAX_BATCH_TOKENS:
            out.append(cur)
            cur, used = [], 0
        cur.append((doc_id, date, text))
        used += t
    if cur:
        out.append(cur)
    return out


async def update(ctx: CustomerContext, ledger: Ledger | None, interactions: list[tuple[str, str, str]],
                 known: set[str]) -> tuple[Ledger, list[TraceStep]]:
    """Fold interactions (doc_id, iso date, text), oldest first, into the ledger. Returns (ledger, trace)."""
    team = list(dict.fromkeys([ctx.exec_name, *ctx.our_team]))
    instructions = INSTRUCTIONS.format(customer=ctx.name, team=", ".join(team) or ctx.exec_name)
    trace = []
    for batch in _batches(interactions):
        new = "\n\n".join(f"--- {d} ({date[:10]})\n{text}" for d, date, text in batch)
        prompt = f"CURRENT LEDGER:\n{render(ledger)}\n\nNEW INTERACTIONS (oldest first):\n{new}"
        upd = await llm.structured(LedgerUpdate, instructions, prompt, max_tokens=6000, effort="medium")
        ledger = merge(ledger, upd, known, team)
        ledger.based_on = list(dict.fromkeys(ledger.based_on + [d for d, _, _ in batch]))
        trace.append(TraceStep(step="ledger", detail=", ".join(d for d, _, _ in batch),
                               result=f"{len(ledger.open_items())} open of {len(ledger.items)} items"))
    return ledger or Ledger(), trace
