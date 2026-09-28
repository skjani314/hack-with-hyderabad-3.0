"""The agent contracts A1–A6 (docs/architecture/contracts.md §4).

Every input is split in one structured extraction: customer-specific facts (and the source text) go to the
customer's bank, generalised name-free lessons go to the shared `company` bank. Every report reads BOTH banks,
with the recall queries shaped by the salesperson's prompt.
"""
import hashlib
import re
import time
from datetime import datetime, timezone

from contracts import (
    SCHEMA_VERSION, CustomerContext, Extraction, Insight, InsightFilters, IngestResult, Interaction,
    InteractionPreview, MemoryCreated, Participant, Profile, ProfileDraft, RawInput, Report, ReportDraft,
    SourceRow, TraceStep,
)

from . import llm, memory, parsing, prompts, stt
from .errors import InvalidInput, LLMRequestTooLarge
from .memory import COMPANY_BANK, Fact

IDS = re.compile(r"\[([A-Za-z]+-[\w-]+)\]")


# ---------- A1 ----------

async def create_customer_memory(ctx: CustomerContext) -> MemoryCreated:
    async with memory.client() as hc:
        created = await memory.ensure_bank(hc, ctx.bank_id)
        await memory.ensure_bank(hc, COMPANY_BANK)
    return MemoryCreated(bank_id=ctx.bank_id, created=created)


# ---------- helpers for the backend ----------

async def list_sources(ctx: CustomerContext) -> list[SourceRow]:
    async with memory.client() as hc:
        docs = await memory.documents(hc, ctx.bank_id)
    return sorted((memory.source_row(d) for d in docs), key=lambda s: _when(s.occurred_at))


async def source_text(ctx: CustomerContext, document_id: str) -> str:
    async with memory.client() as hc:
        return await memory.document_text(hc, ctx.bank_id, document_id)


# ---------- A2 ----------

def _apply_sides(it: Interaction, participants: list[Participant], exec_name: str) -> None:
    """Fill speaker sides from the participant list the salesperson gave (exact first-name match)."""
    side_of = {p.name.split()[0].lower(): p.side for p in participants if p.name}
    side_of.setdefault(exec_name.split()[0].lower(), "ours")
    for t in it.turns:
        key = t.speaker.split()[0].lower() if t.speaker else ""
        if t.side == "unknown" and key in side_of:
            t.side = side_of[key]
    if not it.participants:
        it.participants = participants


async def prepare_interaction(ctx: CustomerContext, raw: RawInput) -> InteractionPreview:
    trace, warnings = [], []
    async with memory.client() as hc:
        docs = await memory.documents(hc, ctx.bank_id)
    existing = {d["id"] for d in docs}
    known_fps = memory.fingerprints(docs)
    trace.append(TraceStep(step="list_sources", detail=ctx.bank_id, result=f"{len(existing)} documents"))

    text = raw.text or ""
    if raw.kind == "file" and raw.file_bytes is not None and parsing.extension(raw.file_name) not in (
            parsing.AUDIO_EXT | parsing.DOC_EXT | {".eml", ".csv"}):
        text = raw.file_bytes.decode("utf-8-sig", errors="replace")
    if raw.kind == "recording_url":
        channel = "call"
    else:
        channel = raw.channel or parsing.detect_channel(text, raw.file_name if raw.kind == "file" else None)

    new = dup = 0
    ext = parsing.extension(raw.file_name)
    if raw.kind == "recording_url" or (raw.kind == "file" and ext in parsing.AUDIO_EXT):
        segments = await stt.transcribe(raw.file_bytes, raw.file_name, raw.recording_url)
        trace.append(TraceStep(step="transcribe", detail=stt.STT_MODEL, result=f"{len(segments)} segments"))
        turns = await stt.label_speakers(segments, raw.participants, ctx.exec_name)
        trace.append(TraceStep(step="label_speakers", result=f"{len(turns)} turns"))
        warnings.append("Speakers were assigned by the AI from the audio text. Check them before saving.")
        items = [parsing.finish(Interaction(
            document_id=parsing.next_id("call", existing), channel="call",
            occurred_at=raw.occurred_at or parsing.now(), title=raw.title or "Call recording",
            participants=raw.participants, turns=turns, text="",
            source_ref=raw.recording_url or raw.file_name or "",
            fingerprints=[parsing.fingerprint("audio", raw.recording_url
                                              or hashlib.sha1(raw.file_bytes or b"").hexdigest())]))]
    elif channel == "whatsapp" and parsing.detect_channel(text) == "whatsapp":  # a chat export
        items, new, dup = parsing.parse_whatsapp(text, existing, known_fps)
        if not items:
            raise InvalidInput(f"All {dup} messages in this chat are already in memory.")
    elif channel == "email":
        items = [parsing.parse_email(raw.file_bytes if ext == ".eml" else text, existing, known_fps)]
    elif channel == "crm" and ext == ".csv":
        items = [parsing.parse_csv(raw.file_bytes or b"", raw.file_name or "export.csv", existing, raw.occurred_at)]
    elif channel == "document" and ext in parsing.DOC_EXT:
        items = [parsing.parse_document(raw.file_bytes or b"", raw.file_name or "file", existing, raw.occurred_at)]
        warnings.append("Converted to text with markitdown; tables and layout may be simplified.")
    else:
        items = [parsing.parse_text(text, channel, existing, raw.title, raw.occurred_at, raw.participants)]
        if items[0].fingerprints and items[0].fingerprints[0] in known_fps:
            raise InvalidInput("This exact text is already in memory.")

    named = [p.name for p in raw.participants] + [ctx.exec_name]
    known_people = {n.lower() for n in named} | {n.split()[0].lower() for n in named if n.split()}
    unknown: list[str] = []
    for it in items:
        if raw.title and it.channel in ("whatsapp",):
            it.title = f"{raw.title} ({it.occurred_at.date()})"
        _apply_sides(it, raw.participants, ctx.exec_name)
        for name in [t.speaker for t in it.turns] + [p.name for p in it.participants]:
            if name and name.lower() not in known_people and name.split()[0].lower() not in known_people \
                    and name not in unknown and name not in (
                    "Salesperson", "Customer", "Unknown"):
                unknown.append(name)
    if channel == "whatsapp" and dup:
        warnings.append(f"{dup} messages were already in memory and were skipped.")
    return InteractionPreview(interactions=items, detected_channel=items[0].channel, new_fingerprints=new,
                              duplicate_fingerprints=dup, unknown_names=unknown[:20], warnings=warnings,
                              trace=trace)


# ---------- A3 ----------

EXTRACT_INSTRUCTIONS = """You extract sales memory from one customer interaction.
Customer: {name} (industry: {industry}). Our salesperson: {exec_name}.

Return:
- customer: facts about THIS customer only, from THIS text only. Objections say who raised them and whether they are
  open or resolved as of this text. Commitments say who owes what by when.
- company_insights: 0-4 GENERALISED lessons another salesperson could reuse with a different customer: how an
  objection was handled, what worked or failed, buyer-role patterns, competitor intelligence, pricing patterns.
  NEVER name the customer company, any person, or any detail that identifies them. Write "a finance controller at a
  {industry} company", not a name. Set industry to "{industry}". Use evidence "confirmed_outcome" only when the text
  shows the result (accepted, rejected, approved, signed), otherwise "observed_once". Return an empty list if nothing
  reusable happened.
- next_steps: concrete actions for our salesperson.
Never invent facts that are not in the text.{advice}"""

ADVICE_BLOCK = """

Before this interaction our salesperson was advised:
{advice}
If the text shows how that advice played out, add company_insights of kind "what_worked" or "what_failed" with
evidence "confirmed_outcome"."""

GENERIC_NAME_WORDS = {"inc", "ltd", "llc", "corp", "corporation", "company", "group", "the", "and", "pvt",
                      "limited", "technologies", "solutions", "systems", "industries", "manufacturing", "global"}


def _names_to_block(ctx: CustomerContext, it: Interaction, ex: Extraction | None) -> set[str]:
    names = {ctx.name, ctx.customer_id, ctx.exec_name}
    names |= {w for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", ctx.name) if w.lower() not in GENERIC_NAME_WORDS}
    people = [p.name for p in it.participants] + [t.speaker for t in it.turns]
    if ex:
        people += [s.name for s in ex.customer.stakeholders]
    for p in people:
        if p and p not in ("Salesperson", "Customer", "Unknown"):
            names.add(p)
            names |= {w for w in p.split() if len(w) >= 3}
    names.add(ctx.exec_name.split()[0])
    return {n for n in names if n and len(n) >= 3}


def leaks(text: str, names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n in names)


def _chunks(text: str, max_tokens: int) -> list[str]:
    if llm.approx_tokens(text) <= max_tokens:
        return [text]
    out, cur = [], []
    for line in text.split("\n"):
        if cur and llm.approx_tokens("\n".join(cur + [line])) > max_tokens:
            out.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


async def _extract(ctx: CustomerContext, rendered: str, advice: str) -> Extraction:
    instructions = EXTRACT_INSTRUCTIONS.format(name=ctx.name, industry=ctx.industry, exec_name=ctx.exec_name,
                                               advice=ADVICE_BLOCK.format(advice=advice) if advice else "")
    parts = _chunks(rendered, 2500)
    results = [await llm.structured(Extraction, instructions, part, max_tokens=2500) for part in parts]
    if len(results) == 1:
        return results[0]
    merged = results[0].model_copy(deep=True)  # long call: facts from every chunk, summary joined
    for r in results[1:]:
        c, m = r.customer, merged.customer
        for field in ("pain_points", "goals", "objections", "stakeholders", "competitors", "requirements",
                      "commitments", "pricing"):
            getattr(m, field).extend(getattr(c, field))
        m.sentiment = c.sentiment
        merged.company_insights.extend(r.company_insights)
        merged.next_steps = r.next_steps or merged.next_steps
    merged.summary = " ".join(r.summary for r in results)
    return merged


def _advice_text(prior: Report | None) -> str:
    if not prior:
        return ""
    lines = [prior.answer] + [f"- {p.text}" for p in prior.playbook_tips] + [f"- {o.objection} => {o.response}"
                                                                            for o in prior.objections]
    return "\n".join(lines)[:1500]


async def ingest_interaction(ctx: CustomerContext, interactions: list[Interaction],
                             prior_report: Report | None = None) -> IngestResult:
    trace: list[TraceStep] = []
    remembered, insight_ids, rejected = [], [], 0
    summaries, next_steps, ok = [], [], True
    advice = _advice_text(prior_report)
    async with memory.client() as hc:  # both banks exist: A1 creates them with the customer
        docs = {d["id"]: d for d in await memory.documents(hc, ctx.bank_id)}
        for it in interactions:
            rendered = parsing.render(it)
            ex: Extraction | None = None
            t0 = time.perf_counter()
            try:
                ex = await _extract(ctx, rendered, advice)  # advice: whatever channel reports how it played out
                trace.append(TraceStep(step="extract", detail=it.document_id,
                                       result=f"{len(ex.company_insights)} lessons, {time.perf_counter() - t0:.1f}s"))
            except llm.LLMRateLimited:
                raise
            except Exception as e:  # never lose the source because extraction failed
                ok = False
                trace.append(TraceStep(step="extract", detail=it.document_id, result=f"failed: {str(e)[:80]}"))

            old_fps = (docs.get(it.document_id, {}).get("document_metadata") or {}).get("fingerprints", "")
            fps = sorted(set(filter(None, old_fps.split(","))) | set(it.fingerprints)) if it.mode == "append" \
                else it.fingerprints
            people = "; ".join(p.name for p in it.participants)[:300]
            t0 = time.perf_counter()
            await memory.retain(hc, ctx.bank_id, [dict(
                content=rendered, document_id=it.document_id, update_mode=it.mode,
                timestamp=it.occurred_at.isoformat(),
                context=f"{it.channel} with {ctx.name} ({ctx.industry}): {it.title}"[:200],
                metadata={"channel": it.channel, "title": it.title[:120], "occurred_at": it.occurred_at.isoformat(),
                          "people": people, "source_ref": it.source_ref[:200], "fingerprints": ",".join(fps),
                          "summary": (ex.summary if ex else "")[:1000]},  # read by briefs as the latest state
                tags=[f"channel:{it.channel}"])])
            remembered.append(it.document_id)
            trace.append(TraceStep(step="retain", detail=f"{ctx.bank_id}/{it.document_id}",
                                   result=f"{time.perf_counter() - t0:.1f}s"))

            if ex:
                summaries.append(ex.summary)
                next_steps += ex.next_steps
                blocked = _names_to_block(ctx, it, ex)
                items = []
                for i, ins in enumerate(ex.company_insights):
                    if leaks(ins.text, blocked):
                        rejected += 1
                        continue
                    iid = f"INS-{parsing.fingerprint(ctx.customer_id, it.document_id, str(i))[:8]}"
                    industry = (ins.industry or ctx.industry).lower()
                    tags = [f"industry:{industry}", f"kind:{ins.kind}", f"evidence:{ins.evidence}"]
                    if ins.role:
                        tags.append(f"role:{ins.role.lower().replace(' ', '_')}")
                    items.append(dict(
                        content=f"[{iid}] Sales lesson ({ins.kind}, {industry}"
                                + (f", {ins.role}" if ins.role else "") + f", {ins.evidence}): {ins.text}",
                        document_id=iid, timestamp=it.occurred_at.isoformat(),
                        context=f"generalised sales lesson, {industry}",
                        metadata={"kind": ins.kind, "text": ins.text[:500], "industry": industry,
                                  "role": ins.role or "", "evidence": ins.evidence,
                                  "occurred_at": it.occurred_at.isoformat()},
                        tags=tags))
                    insight_ids.append(iid)
                # queued on Hindsight's side: the salesperson doesn't wait for the playbook write
                await memory.retain(hc, COMPANY_BANK, items, wait=False)
                if items:
                    trace.append(TraceStep(step="retain", detail=COMPANY_BANK, result=f"{len(items)} lessons (queued)"))
    return IngestResult(remembered=remembered, company_insights=insight_ids, rejected_insights=rejected,
                        summary=" ".join(summaries), next_steps=next_steps[:8], extraction_ok=ok, trace=trace)


# ---------- A4 ----------

# Report instructions are layered (main prompt + chosen pieces + request): see prompts.py


def _fit(lines: list[str], budget_tokens: int) -> list[str]:
    out, used = [], 0
    for ln in lines:
        t = llm.approx_tokens(ln)
        if used + t > budget_tokens:
            break
        out.append(ln)
        used += t
    return out


def _when(iso: str) -> datetime:
    """Sort key for stored ISO dates. They carry different UTC offsets (-05:00, +00:00), so compare as instants,
    never as strings; unknown dates sort first."""
    try:
        d = datetime.fromisoformat(iso)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _gate_ids(ids: list[str], known: set[str]) -> list[str]:
    """Evidence gate: keep only ids that exist in memory, returned in their stored spelling (case-insensitive,
    because models write INS-3FA2C1AB for INS-3fa2c1ab)."""
    canon = {k.upper(): k for k in known}
    return sorted({canon[u] for i in ids if (u := i.strip("[] ").upper()) in canon})


def _strip_unknown(text: str, known: set[str]) -> str:
    upper = {k.upper() for k in known}
    text = re.sub(r"\[([A-Za-z]+)[‐-―−](\w)", r"[\1-\2", text)  # models write EM‑03 with non-ASCII hyphens
    return re.sub(r"\s{2,}", " ", IDS.sub(lambda m: m.group(0) if m.group(1).upper() in upper else "", text)).strip()


async def _recall_both(hc, ctx: CustomerContext, prompt: str) -> tuple[list[Fact], list[Fact], list[TraceStep]]:
    trace = []
    cust_queries = [(prompt, 10), ("latest status, open commitments, open objections and deadlines", 8),
                    ("stakeholders, their roles and what each one cares about", 6)]
    cust: list[Fact] = []
    for q, n in cust_queries:
        facts = await memory.recall(hc, ctx.bank_id, q, limit=n)
        trace.append(TraceStep(step="recall", detail=f"customer: {q[:60]}", result=f"{len(facts)} facts"))
        cust += facts
    comp = await memory.recall(hc, COMPANY_BANK, f"{prompt} ({ctx.industry})", tags=[f"industry:{ctx.industry}"],
                               limit=6)
    trace.append(TraceStep(step="recall", detail=f"company, industry:{ctx.industry}", result=f"{len(comp)} lessons"))
    general = await memory.recall(hc, COMPANY_BANK, prompt, limit=4)
    trace.append(TraceStep(step="recall", detail="company, all industries", result=f"{len(general)} lessons"))
    dedupe = lambda fs: list({f.text: f for f in fs}.values())  # noqa: E731
    return dedupe(cust), dedupe(comp + general), trace


def _latest(docs: list[dict], n: int = 3) -> list[str]:
    """The newest interactions with their extraction summaries. Recall ranks by relevance, not date, so without this
    the newest message (the one that says something was approved or replaced) can be missing from the brief."""
    newest = sorted(docs, key=lambda d: _when((d.get("document_metadata") or {}).get("occurred_at", "")))[-n:]
    out = []
    for d in newest:
        md = d.get("document_metadata") or {}
        summary = md.get("summary") or md.get("title", "")
        out.append(f"[{d['id']}] {md.get('occurred_at', '')[:10]} {md.get('channel', '')} · {md.get('title', '')}: "
                   f"{summary}")
    return out


async def generate_report(ctx: CustomerContext, prompt: str, history: list[str] | None = None,
                          pieces: list[str] | None = None, org_prompt: str | None = None) -> Report:
    instructions, used = prompts.compose(ctx.exec_name, ctx.name, ctx.industry, pieces or [], org_prompt)
    async with memory.client() as hc:
        docs = await memory.documents(hc, ctx.bank_id)
        cust, comp, trace = await _recall_both(hc, ctx, prompt)
    rows = sorted((memory.source_row(d) for d in docs), key=lambda r: _when(r.occurred_at))

    candidates = {
        "convo": [f"{r.document_id} | {r.channel} | {r.occurred_at[:10]} | {r.title}" for r in rows[-25:]],
        "latest": _latest(docs), "cust": [f.line() for f in cust], "comp": [f.line() for f in comp],
    }
    budgets = {"convo": 400, "latest": 500, "cust": 1500, "comp": 600}

    def size(key: str) -> int:  # what the section actually needs, capped by its normal budget
        return min(budgets[key], sum(llm.approx_tokens(x) for x in candidates[key]))

    def build(scale: float) -> tuple[str, list[str], list[str], list[str]]:
        """The prompt, with every memory section cut to `scale` of what it actually uses. The newest interactions
        shrink least: they are what keeps the brief current."""
        convo = _fit(candidates["convo"], int(size("convo") * scale))
        # trimmed from the OLD end: the newest interaction is the last to go (listed oldest→newest)
        latest = _fit(candidates["latest"][::-1], int(size("latest") * max(scale, 0.6)))[::-1]
        cust_lines = _fit(candidates["cust"], int(size("cust") * scale))
        comp_lines = _fit(candidates["comp"], int(size("comp") * scale))
        sections = [
            ("CONVERSATIONS IN MEMORY (oldest first)", convo, "(none yet)"),
            ("MOST RECENT INTERACTIONS (newest last; they override anything older)", latest, "(none yet)"),
            ("CUSTOMER MEMORY", cust_lines, "(empty: new customer)"),
            ("COMPANY PLAYBOOK", comp_lines, "(no lessons yet)"),
        ]
        if history:
            sections.append(("EARLIER IN THIS CONVERSATION", history[-4:], ""))
        user = "\n\n".join(f"{title}:\n" + ("\n".join(lines) or empty) for title, lines, empty in sections)
        return user + f"\n\nSALESPERSON'S REQUEST: {prompt}", latest, cust_lines, comp_lines

    user, latest, cust_lines, comp_lines = build(1.0)
    trace.append(TraceStep(step="latest", detail="newest interactions",
                           result=", ".join(r.document_id for r in rows[-3:])))
    # medium reasoning: at "low", gpt-oss read "support plan instead of a 10% discount" as "10% discount agreed".
    try:
        draft = await llm.structured(ReportDraft, instructions, user, max_tokens=4000, effort="medium")
    except LLMRequestTooLarge as e:
        # Groq sizes a request by its prompt; a key with a lower per-minute limit needs less memory context.
        limit, requested = getattr(e, "limit", None), getattr(e, "requested", None)
        if not (limit and requested):
            raise
        # cut the memory context by the overshoot plus a 10% margin; instructions and schema are fixed
        over = requested - int(limit * 0.9)
        memory_tokens = sum(size(k) for k in budgets)
        scale = max(0.2, 1 - over / max(memory_tokens, 1))
        user, latest, cust_lines, comp_lines = build(scale)
        trace.append(TraceStep(step="shrink_context", detail=f"limit {limit}, requested {requested}",
                               result=f"memory context x{scale:.2f}"))
        draft = await llm.structured(ReportDraft, instructions, user, max_tokens=4000, effort="medium")
    trace.append(TraceStep(step="write_report", detail=f"pieces: {', '.join(used) or 'none'}"))

    customer_ids = {r.document_id for r in rows}
    known = customer_ids | {i for f in comp for i in f.sources}
    dropped = 0

    def keep(items, required=True, allowed=known):
        nonlocal dropped
        out = []
        for x in items:
            x.sources = _gate_ids(x.sources, allowed)
            if required and not x.sources:
                dropped += 1
                continue
            out.append(x)
        return out

    rep = Report(**draft.model_dump())
    rep.open_items = keep(rep.open_items, allowed=customer_ids)  # open items are about this customer only
    rep.risks, rep.playbook_tips = keep(rep.risks), keep(rep.playbook_tips)
    rep.stakeholders, rep.objections = keep(rep.stakeholders), keep(rep.objections)
    rep.what_to_ask = keep(rep.what_to_ask, False)
    for step in (rep.call_plan.opening, rep.call_plan.recap, rep.call_plan.discovery, rep.call_plan.value,
                 rep.call_plan.objections, rep.call_plan.close):
        step.sources = _gate_ids(step.sources, known)
        step.say = IDS.sub("", step.say).strip()
    rep.answer, rep.summary = _strip_unknown(rep.answer, known), _strip_unknown(rep.summary, known)
    rep.follow_up_email = IDS.sub("", rep.follow_up_email).strip()
    rep.next_steps = [_strip_unknown(s, known) for s in rep.next_steps]
    rep.memory_used = {"customer_facts": len(cust_lines), "company_lessons": len(comp_lines),
                       "conversations": len(rows), "latest": len(latest)}
    rep.dropped, rep.trace, rep.schema_version, rep.pieces = dropped, trace, SCHEMA_VERSION, used
    return rep


# ---------- A5 ----------

PROFILE_INSTRUCTIONS = """Build the account profile of {name} from CUSTOMER MEMORY only. Each item cites the source ids
printed in square brackets at the start of the memory lines it came from, copied exactly; never cite an id that is not
on those lines. `detail` is a few words of extra context (who raised it, role, status, due date) and must not repeat
the item. List each person once in stakeholders and each fact once overall. Later messages override earlier ones.
Leave a section empty when memory has nothing for it. Never invent anything."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


async def get_profile(ctx: CustomerContext) -> Profile:
    async with memory.client() as hc:
        docs = await memory.documents(hc, ctx.bank_id)
        if not docs:
            return Profile(pain_points=[], goals=[], objections=[], stakeholders=[], competitors=[],
                           requirements=[], commitments=[], pricing=[])
        facts: list[Fact] = []
        for q in ("pain points, goals and requirements", "stakeholders, roles and what each cares about",
                  "objections, competitors, pricing and discounts", "commitments, deadlines and latest status"):
            facts += await memory.recall(hc, ctx.bank_id, q, limit=8)
    lines = _fit(list(dict.fromkeys(f.line() for f in facts)), 2200)
    draft = await llm.structured(ProfileDraft, PROFILE_INSTRUCTIONS.format(name=ctx.name),
                                 "CUSTOMER MEMORY:\n" + "\n".join(lines), max_tokens=2200)
    known = {d["id"] for d in docs}
    prof, dropped, seen = Profile(**draft.model_dump()), 0, set()
    for field in ProfileDraft.model_fields:
        kept = []
        for item in getattr(prof, field):
            item.sources = _gate_ids(item.sources, known)
            key = _norm(item.text)
            if not item.sources:
                dropped += 1
            elif key not in seen:  # the same fact (or person) once, in the first section it appears
                seen.add(key)
                if item.detail and _norm(item.detail) in key:
                    item.detail = None  # detail that only repeats the text adds nothing
                kept.append(item)
        setattr(prof, field, kept)
    prof.dropped = dropped
    return prof


# ---------- A6 ----------

async def list_company_insights(filters: InsightFilters) -> list[Insight]:
    async with memory.client() as hc:
        docs = await memory.documents(hc, COMPANY_BANK)
    out = [Insight(**memory.insight_from_doc(d)) for d in docs if d["id"].startswith("INS-")]
    if filters.industry:
        out = [i for i in out if i.industry == filters.industry.lower()]
    if filters.role:
        out = [i for i in out if (i.role or "").lower() == filters.role.lower()]
    if filters.kind:
        out = [i for i in out if i.kind == filters.kind]
    return sorted(out, key=lambda i: i.occurred_at, reverse=True)
