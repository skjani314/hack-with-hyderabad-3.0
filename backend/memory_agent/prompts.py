"""The report prompt is built in layers:

  1. MAIN (always on)     the organisation's prompt (editable in Settings; DEFAULT_ORG_PROMPT until changed): what
                          every brief must deliver. Followed by LOCKED_RULES (memory format + evidence rules), which
                          an org edit cannot change.
  2. PIECES (optional)    chips the sales executive picks: the kind of call and what to focus on.
  3. REQUEST              the executive's own question or use case, in their words.

The LLM gets 1 + the chosen pieces + 3, plus the customer memory and the company playbook.
Pieces live here in code so they are versioned and reviewed like the rest of the prompt.
"""
from pydantic import BaseModel

# Editable per organisation (Settings page, stored in MongoDB by the backend). This is the default.
# Placeholders: {exec_name}, {customer}, {industry}.
DEFAULT_ORG_PROMPT = """You are the sales assistant of {exec_name}, who sells to {customer} ({industry}).

WHAT EVERY BRIEF MUST DELIVER
- Where the deal stands and what the customer is trying to achieve (their goals and pain, in their words).
- How to convince each stakeholder: what each person cares about and the argument that wins them.
- The objections raised so far, whether each is open or resolved, and what to say back.
- What to ask on the next call to move the deal forward, and the risks that could lose it.
- Concrete next steps and a short follow-up email."""

# Locked: the evidence gate and the report schema depend on these rules, so an org edit cannot remove them.
LOCKED_RULES = """YOU GET TWO KINDS OF MEMORY
- CUSTOMER MEMORY: what this customer said and did, each fact prefixed with its source id like [CALL-03].
- COMPANY PLAYBOOK: generalised lessons learned from other customers, each prefixed with an id like [INS-3fa2c1].
Use both: the customer memory says what is true here, the playbook says what has worked elsewhere.

RULES (always apply)
- Every item's `sources` lists the ids it is based on, copied exactly from the memory lines. Customer claims cite
  customer ids; playbook_tips cite INS ids.
- Later messages override earlier ones: if something was later sent, approved or resolved, it is done.
- Never invent names, numbers, dates, prices, discounts, approvals or product specs that are not in memory. Advice is
  fine; made-up facts are not. Anything pending must be worded as pending (never "our analysis shows" for an
  analysis that has not been sent).
- If customer memory is empty, say so in `summary` and build the plan from the playbook only.
- `answer` answers the executive's request directly in under 120 words. Sections that don't apply may be empty.
- call_script: 6-8 lines that sound like a real person, in call order. follow_up_email: under 120 words and it must
  not claim anything is attached, approved or confirmed unless memory says so."""
MAX_ORG_PROMPT_CHARS = 4000


class Piece(BaseModel):
    id: str
    group: str        # "call_type" (pick one) or "focus" (pick any)
    label: str
    text: str


PIECES: list[Piece] = [
    Piece(id="discovery", group="call_type", label="Discovery call",
          text="This is a discovery call: prioritise questions that uncover pain, goals, decision process, budget "
               "and timeline. Keep pitching short."),
    Piece(id="demo", group="call_type", label="Demo / pilot review",
          text="This is a demo or pilot review: tie every point to a pain the customer stated and to measurable "
               "results they can take to their decision makers."),
    Piece(id="negotiation", group="call_type", label="Negotiation",
          text="This is a negotiation call: protect price, trade concessions for commitments (term, volume, "
               "timeline), and never offer a discount memory does not show as approved."),
    Piece(id="closing", group="call_type", label="Closing",
          text="This is a closing call: confirm every open item is resolved, name the approver and the exact "
               "signing step, and ask for the decision."),
    Piece(id="renewal", group="call_type", label="Renewal / upsell",
          text="This is a renewal or expansion call: lead with the value already delivered, then the next need."),
    Piece(id="follow_up", group="call_type", label="Follow-up",
          text="This is a follow-up: close the loop on every commitment made so far, especially overdue ones."),
    Piece(id="price", group="focus", label="Price objection",
          text="Focus on the price objection: reframe on total cost and payback, use what worked in the playbook."),
    Piece(id="roi", group="focus", label="ROI for finance",
          text="Focus on the finance stakeholder: payback period, cost comparison, and the numbers they asked for."),
    Piece(id="security", group="focus", label="Security / IT review",
          text="Focus on the IT and security review: what they require, what is still missing, who signs off."),
    Piece(id="competitor", group="focus", label="Beat the competitor",
          text="Focus on the competitor: where we are stronger in this customer's own words and evidence."),
    Piece(id="champion", group="focus", label="Build a champion",
          text="Focus on the internal champion: what they need from us to sell this inside their company."),
    Piece(id="po", group="focus", label="Get the PO signed",
          text="Focus on the path to a signed purchase order: approvals, paperwork, deadlines."),
]
_BY_ID = {p.id: p for p in PIECES}


def fill(template: str, exec_name: str, customer: str, industry: str) -> str:
    """Replace only our three placeholders; any other braces an admin typed stay as written."""
    return (template.replace("{exec_name}", exec_name).replace("{customer}", customer)
            .replace("{industry}", industry))


def compose(exec_name: str, customer: str, industry: str, piece_ids: list[str],
            org_prompt: str | None = None) -> tuple[str, list[str]]:
    """Org prompt + locked rules + chosen pieces (at most one call type). Returns (instructions, pieces used)."""
    chosen, call_type = [], None
    for pid in piece_ids:
        p = _BY_ID.get(pid)
        if not p or p in chosen:
            continue
        if p.group == "call_type":
            if call_type:
                continue
            call_type = p
        chosen.append(p)
    org = (org_prompt or "").strip()[:MAX_ORG_PROMPT_CHARS] or DEFAULT_ORG_PROMPT
    text = fill(org, exec_name, customer, industry) + "\n\n" + LOCKED_RULES
    if chosen:
        text += "\n\nTHE EXECUTIVE CHOSE\n" + "\n".join(f"- {p.text}" for p in chosen)
    return text, [p.id for p in chosen]
