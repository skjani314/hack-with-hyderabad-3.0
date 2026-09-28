"""The sales agent: a Groq LLM (via Pydantic AI) that reasons over Hindsight memory.

Why an LLM at all: Hindsight recall returns separate facts ("finance wants payback under 12 months",
"competitor trial throttled", "questionnaire overdue"). Turning those into a prioritised plan and a
natural talk track for each stakeholder is reasoning and writing, which is the LLM's job.

How memory reaches the agent:
  1. Prefetch: before the LLM runs, we recall the relevant facts from Hindsight and list the
     conversations (fast, cheap, and keeps the run inside Groq's free-tier token limits).
  2. Tools: the agent can dig deeper itself (recall_memory, read_source, list_sources, save_note).
  3. Evidence gate: every citation it returns must be a source really in memory (agent.gate_*).
Every memory step is returned as a trace, so the UI can show what the agent looked at.
"""
import asyncio
import os
from datetime import datetime, timezone

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from hindsight_client import Hindsight
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.usage import UsageLimits

import agent as memory

# Groq models (the brief recommends gpt-oss-120b). If one is over capacity or errors, the next one answers.
# ponytail: fixed chain of models this key can use; check `Groq().models.list()` if Groq retires one
MODELS = [os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
# ponytail: sized for Groq free tier (8k tokens/minute per model); raise all three on the Dev tier
MAX_FACTS = 12          # facts per recall for chat; call prep uses 8 per angle over 4 angles
MAX_SOURCE_CHARS = 1500
CHAT_LIMITS = UsageLimits(request_limit=4)  # prefetch makes 1 LLM call the norm; up to 2 tool rounds + 1 retry
PREP_LIMITS = UsageLimits(request_limit=3)  # one pass, plus up to 2 retries if the output fails validation
CHAT_MAX_TOKENS = 2000  # gpt-oss is a reasoning model: hidden thinking counts against this cap too


# ---------- structured output (call prep; chat answers are plain text with inline [EM-02] citations) ----------

# Flat on purpose: open models fill simple lists of sentences reliably, but rename fields in nested objects
# (we saw title/detail for text/why_it_matters). Citations ride inline as [EM-02]; gate_prep parses them out.
class CallPrep(BaseModel):
    summary: str = Field(description="Where the deal stands, 2 sentences")
    insights: list[str] = Field(default_factory=list, description="3-4 key things to know, each ending with [IDs]")
    risks: list[str] = Field(default_factory=list, description="What could lose the deal, each with [IDs]")
    stakeholders: list[str] = Field(default_factory=list,
                                    description="One per person: 'Name (role): what they care about -> how to win them [IDs]'")
    objections: list[str] = Field(default_factory=list,
                                  description="One per objection: 'objection (who raised it) [ID] => what to say back, "
                                              "first person, natural spoken words'")
    call_script: list[str] = Field(default_factory=list,
                                   description="6-8 lines in call order, each 'Stage: exact words to say [IDs]'. "
                                               "Stages: Opening, Recap, Discovery, Value, Objections, Close")
    next_steps: list[str] = Field(default_factory=list)
    follow_up_email: str = Field("", description="Short email, under 120 words")


# ---------- the agent ----------

INSTRUCTIONS = """You are a sales assistant for {salesperson}, who is selling {product} to {customer} (deal {deal_id}, stage {stage}).
All knowledge about this customer lives in Hindsight memory. Below is what memory already returned for this request.
Usually answer directly from this. Use a tool only if something essential is missing (at most 2 tool calls):
- recall_memory(query) to search for more facts; read_source(id) for a message's exact wording;
- save_note(text) only when the salesperson explicitly asks you to remember something.
Rules:
- Later messages override earlier ones: if a newer message says something was sent, approved or resolved, it is done.
- Cite source ids like [EM-02] after every fact.
- Never invent anything: no numbers, dates, benchmarks, product specs, delivery times or discounts that are not in
  memory. Advice is fine ("ask Michael to confirm budget"), made-up facts are not. If memory has nothing, say so.
- Never say something was approved, agreed, sent or decided unless a message says so. Open questions (for example
  a discount the salesperson must still check with their manager) must be presented as open.
- Plain text, no markdown tables. Chat answers: at most 120 words, lead with the most important point.
- Scripts must sound like a real person talking, use what each stakeholder actually said, and never promise terms
  the salesperson has not confirmed.

CONVERSATIONS IN MEMORY (oldest first; the last ones show the current state):
{conversations}

FACTS RECALLED FROM MEMORY:
{facts}"""


def _model():
    # low temperature: this agent should restate memory faithfully, not be creative with facts
    return FallbackModel(*[GroqModel(m, settings={"temperature": 0.2}) for m in MODELS])


def _hindsight():
    return Hindsight(base_url=os.getenv("HINDSIGHT_URL", "https://api.hindsight.vectorize.io"),
                     api_key=os.environ["HINDSIGHT_API_KEY"])


async def _recall(hc, dl, query, limit=MAX_FACTS):
    res = await hc.arecall(bank_id=memory.BANK, query=query, tags=[memory.deal_tag(dl)],
                           tags_match="any_strict", budget="mid", max_tokens=4096)
    return memory.format_facts(res.results)[:limit]


async def _prefetch(hc, dl, queries, limit):
    """Recall several angles at once and list the conversations: the agent starts already informed."""
    page, *recalls = await asyncio.gather(
        hc._documents_api.list_documents(bank_id=memory.BANK, limit=200),
        *[_recall(hc, dl, q, limit) for q in queries])
    rows = memory.sort_sources([memory.source_row(d) for d in page.items])
    facts = list(dict.fromkeys(f for r in recalls for f in r))  # dedupe, keep order
    trace = [dict(step="list_sources", detail=f"{len(rows)} conversations")] + [
        dict(step="recall", detail=q, result=f"{len(r)} facts") for q, r in zip(queries, recalls)]
    sources = "\n".join(f"{s['id']} | {s['channel']} | {s['date'][:10]} | {s['title']}" for s in rows)
    return sources, facts, trace


def build(dl, known, hc, sources, facts, tools=True):
    """hc: a Hindsight client created inside this run's event loop (its HTTP session is bound to that loop)."""
    a = Agent(_model(), retries=2, end_strategy="early",
              instructions=INSTRUCTIONS.format(**dl, conversations=sources, facts="\n".join(facts) or "(nothing yet)"))
    if not tools:  # call prep: 4 prefetched angles already cover the deal, so write in one pass
        return a

    @a.tool_plain
    async def recall_memory(query: str) -> str:
        """Search this deal's Hindsight memory. Returns facts, each prefixed with its source id and date."""
        return "\n".join(await _recall(hc, dl, query)) or "No relevant memories found."

    @a.tool_plain
    async def read_source(source_id: str) -> str:
        """Read the original text of one remembered message, e.g. EM-02 or CALL-03."""
        sid = source_id.strip("[] ").upper()
        if sid not in known:
            raise ModelRetry(f"{sid} is not in memory. Valid ids: {', '.join(sorted(known))}")
        doc = await hc._documents_api.get_document(bank_id=memory.BANK, document_id=sid)
        return doc.original_text[:MAX_SOURCE_CHARS]

    @a.tool_plain
    async def save_note(note: str) -> str:
        """Store a salesperson's note in Hindsight memory (only when explicitly asked)."""
        it = dict(id=memory.next_id("note", known), channel="note", title="Salesperson note", content=note,
                  date=datetime.now(timezone.utc).isoformat())
        await hc.aretain_batch(bank_id=memory.BANK, items=[memory.to_retain_item(dl, it)])
        known.add(it["id"])
        return f"Saved as {it['id']}."

    return a


def tool_trace(messages):
    """The agent's own tool calls, in order, for the UI's 'what the agent looked at' view."""
    calls, out = {}, []
    for m in messages:
        for p in m.parts:
            if isinstance(p, ToolCallPart) and not p.tool_name.startswith("final_result"):
                calls[p.tool_call_id] = p
            elif isinstance(p, ToolReturnPart) and p.tool_call_id in calls:
                args = calls[p.tool_call_id].args_as_dict()
                content = str(p.content)
                out.append(dict(step=p.tool_name, detail=next(iter(args.values()), "") if args else "",
                                result=f"{content.count(chr(10)) + 1} lines" if p.tool_name == "recall_memory"
                                else content[:80]))
    return out


def _run(dl, known, prompt, output_type, queries, limit, usage, max_tokens, tools=True):
    """One agent run on its own event loop, with a Hindsight client that lives and dies in that loop."""
    async def go():
        hc = _hindsight()
        try:
            sources, facts, trace = await _prefetch(hc, dl, queries, limit)
            result = await build(dl, known, hc, sources, facts, tools).run(
                prompt, output_type=output_type, usage_limits=usage, model_settings={"max_tokens": max_tokens})
            return result.output, trace + tool_trace(result.all_messages())
        finally:
            await hc.aclose()
    return asyncio.run(go())


def ask(dl, question, known, use_memory=True):
    """Returns (answer, cited source ids, memory trace). A note saved during the run is added to `known`."""
    if not use_memory:  # same LLM, no memory at all: the honest "before" of the demo
        bare = Agent(_model(), instructions=f"You are a sales assistant helping sell {dl['product']} to "
                                            f"{dl['customer']}. You have no access to any customer history. "
                                            "Answer in under 120 words, plain text.")
        return asyncio.run(bare.run(question)).output, [], []
    # Plain text output: citations are parsed from the [EM-02] marks, and open models fail typed output more often.
    queries = [question, "latest status, open commitments and deadlines"]
    try:
        out, trace = _run(dl, known, question, str, queries, MAX_FACTS, CHAT_LIMITS, CHAT_MAX_TOKENS)
    except (UsageLimitExceeded, UnexpectedModelBehavior):
        # the agent kept digging or returned nothing usable: answer in one pass from the prefetched memory
        out, trace = _run(dl, known, question, str, queries, MAX_FACTS, PREP_LIMITS, CHAT_MAX_TOKENS, tools=False)
    answer, cited = memory.gate_answer(out, [], known)
    return answer, cited, trace


PREP_QUERIES = [
    "pain points, goals and what success looks like",
    "stakeholders, their roles and what each one cares about",
    "objections, pricing, discounts and competitors",
    "commitments we made, deadlines, and latest status of the deal",
]


def call_prep(dl, known, goal=""):
    prompt = ("Prepare me for my next call with this customer: key insights, risks (especially anything we promised "
              "and have not delivered), a plan per stakeholder, objection handling (every objection a stakeholder "
              "actually raised, each with its [ID]), a call script in order, next steps and a follow-up email."
              + (f" My goal for the call: {goal}" if goal else "") +
              "\nGROUNDING, check before you write: every number, date, duration and price you use must appear in "
              "FACTS above; if it does not, leave it out. Do not claim a delivery slot, benchmark, approval or discount "
              "that the facts do not state. Anything still pending (for example a discount awaiting the manager's "
              "check) must be worded as pending in the script and the email. Use the date of the message that says "
              "something happened. The follow-up email must not claim that anything is attached, approved or "
              "confirmed unless FACTS say so; say what you will send and by when instead.")
    prep, trace = _run(dl, known, prompt, CallPrep, PREP_QUERIES, 8, PREP_LIMITS, 2500, tools=False)
    return gate_prep(prep.model_dump(), known) | {"trace": trace}


def gate_prep(prep, known):
    """Evidence gate for call prep. Claims (insights, risks, stakeholders, objections) must cite a source that is
    really in memory or they are dropped; script lines and the email keep only real citations."""
    dropped = 0

    def claims(items):
        nonlocal dropped
        out = []
        for text in items:
            text, sources = memory.gate_answer(text, [], known)
            if sources:
                out.append(dict(text=memory.IDS.sub("", text).strip(), sources=sources))
            else:
                dropped += 1
        return out

    objections = []
    for o in prep["objections"]:
        said, _, reply = o.partition("=>")
        said, sources = memory.gate_answer(said, [], known)
        reply, more = memory.gate_answer(reply, [], known)
        if sources:
            objections.append(dict(objection=memory.IDS.sub("", said).strip(),
                                   response=memory.IDS.sub("", reply).strip(), sources=sorted(set(sources) | set(more))))
        else:
            dropped += 1

    script = []
    for line in prep["call_script"]:
        stage, _, say = line.partition(":") if ":" in line[:20] else ("", "", line)
        say, sources = memory.gate_answer(say, [], known)
        script.append(dict(stage=stage.strip(), say=memory.IDS.sub("", say).strip().strip('"'), sources=sources))

    email, _ = memory.gate_answer(prep["follow_up_email"], [], known)
    steps = [memory.gate_answer(s, [], known)[0] for s in prep["next_steps"]]  # invalid ids like [CALL-11] removed
    return dict(summary=memory.gate_answer(prep["summary"], [], known)[0], insights=claims(prep["insights"]),
                risks=claims(prep["risks"]), stakeholders=claims(prep["stakeholders"]), objections=objections,
                call_script=script, next_steps=steps, follow_up_email=memory.IDS.sub("", email).strip(),
                dropped=dropped)
