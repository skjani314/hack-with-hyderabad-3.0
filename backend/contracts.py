"""Every shape that crosses a boundary: frontend <-> API <-> agent, and agent <-> LLM.

Spec: docs/architecture/contracts.md. If this module and the doc disagree, one of them is a bug.

Two families of models:
  * `Strict` models are sent to the LLM as JSON schemas. Groq strict mode (constrained decoding) requires every
    field to be required and `additionalProperties: false`, so they forbid extras and have NO defaults; optional
    values are nullable instead (`str | None`).
  * Everything else is our own API/agent data and may use defaults.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

Channel = Literal["call", "email", "whatsapp", "crm", "note", "document", "outcome"]
Side = Literal["ours", "customer", "unknown"]


class Strict(BaseModel):
    """Base for LLM output schemas (Groq strict structured outputs)."""
    model_config = ConfigDict(extra="forbid")


# ---------- context handed from the backend to the agent ----------

class CustomerContext(BaseModel):
    """Built by the backend after login + permission check; the agent trusts it and never sees a user."""
    customer_id: str
    bank_id: str
    name: str
    industry: str
    exec_name: str
    our_team: list[str] = []           # names of our own people (every user): never shown as customer stakeholders


# ---------- interactions (every input is normalised to this) ----------

class Participant(BaseModel):
    name: str
    side: Side = "customer"
    role: str = ""


class Turn(BaseModel):
    speaker: str
    side: Side = "unknown"
    text: str
    at: str = ""                       # "00:03:12" for calls, ISO time for chats
    speaker_inferred: bool = False     # true when the LLM guessed who spoke


class Interaction(BaseModel):
    # CALL-07, EM-12, WA-2026-09-12, FILE-proposal-v2. The browser sends previews back, so the id is validated:
    # the agent cites it, the UI links it, and it must never be shaped like a company lesson (INS-…).
    document_id: str = Field(pattern=r"^(CALL|EM|WA|CRM|NOTE|FILE|OUT)-[A-Za-z0-9-]{1,60}$")
    channel: Channel
    occurred_at: datetime
    title: str
    participants: list[Participant] = []
    turns: list[Turn] = []
    text: str                          # raw body; header + speaker labels are added at retain time
    source_ref: str = ""               # file name, recording URL, Message-ID
    fingerprints: list[str] = []       # de-duplication keys
    mode: Literal["replace", "append"] = "replace"
    request_id: str | None = None      # the report this call followed (learning loop)


class RawInput(BaseModel):
    """What the salesperson uploaded or pasted, before parsing (agent contract A2)."""
    kind: Literal["text", "file", "recording_url"]
    text: str | None = None
    file_name: str | None = None
    file_bytes: bytes | None = None
    recording_url: str | None = None
    channel: Channel | None = None     # user override; detected when None
    title: str | None = None
    occurred_at: datetime | None = None
    participants: list[Participant] = []


class InteractionPreview(BaseModel):
    schema_version: int = SCHEMA_VERSION
    interactions: list[Interaction]
    detected_channel: Channel
    new_fingerprints: int = 0
    duplicate_fingerprints: int = 0
    unknown_names: list[str] = []
    warnings: list[str] = []
    trace: list["TraceStep"] = []


class TraceStep(BaseModel):
    step: str                          # recall, read_source, retain, extract, transcribe, …
    detail: str = ""
    result: str = ""


# ---------- LLM schemas: speaker labelling ----------

class LabelledTurn(Strict):
    segment: int = Field(description="Index of the transcript segment this label is for")
    speaker: str = Field(description="Person's name if known from the participant list, else 'Salesperson' or 'Customer'")
    side: Literal["ours", "customer", "unknown"]


class SpeakerLabels(Strict):
    turns: list[LabelledTurn]


# ---------- LLM schemas: extraction (one call per interaction) ----------

class SourcedFact(Strict):
    text: str


class ObjectionFact(Strict):
    text: str
    raised_by: str | None
    status: Literal["open", "resolved"]


class StakeholderFact(Strict):
    name: str
    role: str | None
    cares_about: str


class CompetitorFact(Strict):
    name: str
    notes: str


class CommitmentFact(Strict):
    text: str
    owner: str | None = Field(description="Who must do it: our salesperson's name or a customer person")
    due: str | None
    status: Literal["open", "done", "overdue"]


class CustomerFacts(Strict):
    pain_points: list[SourcedFact]
    goals: list[SourcedFact]
    objections: list[ObjectionFact]
    stakeholders: list[StakeholderFact]
    competitors: list[CompetitorFact]
    requirements: list[SourcedFact]
    commitments: list[CommitmentFact]
    pricing: list[SourcedFact]
    sentiment: Literal["positive", "neutral", "negative"]


InsightKind = Literal["objection_handling", "what_worked", "what_failed", "competitor_intel",
                      "persona_pattern", "pricing_pattern", "buying_process"]


class CompanyInsight(Strict):
    kind: InsightKind
    text: str = Field(description="A generalised, reusable sales lesson. Never name the customer company or any person.")
    industry: str | None
    role: str | None = Field(description="Buyer role the lesson is about, e.g. finance, it_security, operations")
    evidence: Literal["observed_once", "confirmed_outcome"]


class Extraction(Strict):
    summary: str = Field(description="3-5 sentences: what happened in this interaction")
    customer: CustomerFacts
    company_insights: list[CompanyInsight]
    next_steps: list[str]


# ---------- deal ledger: the customer's current state, kept up to date on every upload ----------

LedgerStatus = Literal["open", "at_risk", "overdue", "done", "resolved", "dropped"]


class LedgerItem(Strict):
    id: str | None = Field(description="The existing item's id when updating it (e.g. L-03); null for a new item")
    kind: Literal["commitment", "objection", "requirement", "risk", "decision"]
    text: str = Field(description="One sentence, current wording (update the text when the item changes)")
    owner: str | None = Field(description="Who must act: a person's name, or null")
    due: str | None = Field(description="YYYY-MM-DD when a date is known, else null")
    status: LedgerStatus = Field(description="done/resolved only when a message shows it happened or was accepted; "
                                             "a promise keeps it open; dropped when replaced or no longer relevant")
    sources: list[str] = Field(description="Ids of the interactions behind the current status, newest last")


class LedgerPerson(Strict):
    name: str
    role: str | None
    side: Literal["ours", "customer"]
    stance: Literal["champion", "supporter", "neutral", "skeptic", "blocker"]
    position: str = Field(description="What they want or their latest position, one sentence")
    sources: list[str]


class LedgerUpdate(Strict):
    """What the LLM returns: the whole ledger after applying the new interactions."""
    summary: str = Field(description="Where the deal stands now, 2 sentences")
    stage: Literal["discovery", "evaluation", "negotiation", "closing", "won", "lost"]
    items: list[LedgerItem]
    people: list[LedgerPerson]


class Ledger(BaseModel):
    """Stored per customer (MongoDB `ledgers`). Every item has a stable id and cites the messages behind it."""
    summary: str = ""
    stage: str = "discovery"
    items: list[LedgerItem] = []
    people: list[LedgerPerson] = []
    based_on: list[str] = []           # every interaction id folded into this ledger, oldest first
    updated_at: datetime | None = None

    def open_items(self) -> list[LedgerItem]:
        return [i for i in self.items if i.status in ("open", "at_risk", "overdue")]


# ---------- agent results ----------

class MemoryCreated(BaseModel):
    bank_id: str
    created: bool


class IngestResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    remembered: list[str]
    company_insights: list[str]
    rejected_insights: int = 0
    summary: str = ""
    next_steps: list[str] = []
    extraction_ok: bool = True
    ledger: Ledger | None = None       # the customer's ledger after this upload (the backend stores it)
    trace: list[TraceStep] = []


# ---------- report (LLM schema + API response) ----------

class Cited(Strict):
    text: str
    sources: list[str] = Field(description="Source ids from memory, e.g. CALL-03, EM-02, or INS-… for company lessons")


class StakeholderPlay(Strict):
    name: str
    role: str | None
    stance: Literal["champion", "supporter", "neutral", "skeptic", "blocker"] = Field(
        description="Where this person stands on the deal right now, from what memory shows")
    cares_about: str
    how_to_win: str
    sources: list[str]


class OpenItem(Strict):
    text: str
    owner: str | None = Field(description="Who must act: our salesperson or a named customer person")
    due: str | None = Field(description="Due date as YYYY-MM-DD when memory gives one, else null")
    status: Literal["open", "overdue", "at_risk"]
    sources: list[str]


class ObjectionPlay(Strict):
    objection: str
    ledger_id: str | None = Field(description="The DEAL LEDGER objection id this is about (e.g. L-04), or null")
    raised_by: str | None
    status: Literal["open", "resolved"]
    response: str = Field(description="What to say back, first person, natural spoken words")
    sources: list[str]


class ScriptStep(Strict):
    say: str = Field(description="What to say at this step, first person, natural spoken words")
    sources: list[str]


class CallPlan(Strict):
    """The call in order. Each step is a separate field, so the order is guaranteed by the schema."""
    opening: ScriptStep
    recap: ScriptStep
    discovery: ScriptStep
    value: ScriptStep
    objections: ScriptStep
    close: ScriptStep


class ReportDraft(Strict):
    """What the LLM writes. The API response (`Report`) adds gate results and the memory trace."""
    answer: str = Field(description="Direct answer to the salesperson's question, under 120 words")
    summary: str = Field(description="Where the deal stands, 2 sentences")
    deal_stage: Literal["discovery", "evaluation", "negotiation", "closing", "won", "lost"]
    deal_health: Literal["on_track", "at_risk", "off_track"]
    health_reason: str = Field(description="One short sentence: the main reason for the health rating")
    what_to_ask: list[Cited]
    open_items: list[OpenItem]
    stakeholders: list[StakeholderPlay]
    objections: list[ObjectionPlay]
    risks: list[Cited]
    playbook_tips: list[Cited]
    call_plan: CallPlan
    next_steps: list[str]
    follow_up_email: str


class Report(ReportDraft):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    memory_used: dict[str, int] = {}
    pieces: list[str] = []             # prompt pieces the executive chose (prompts.py)
    dropped: int = 0
    trace: list[TraceStep] = []


class PromptPiece(BaseModel):
    id: str
    group: Literal["call_type", "focus"]
    label: str
    text: str


# ---------- profile ----------

class ProfileItem(Strict):
    text: str = Field(description="The fact, one sentence")
    detail: str | None = Field(description="At most 8 words of extra context (who raised it, role, status or due "
                                           "date). Never repeat `text`. null when there is nothing to add")
    sources: list[str]


class ProfileDraft(Strict):
    pain_points: list[ProfileItem]
    goals: list[ProfileItem]
    objections: list[ProfileItem]
    stakeholders: list[ProfileItem]
    competitors: list[ProfileItem]
    requirements: list[ProfileItem]
    commitments: list[ProfileItem]
    pricing: list[ProfileItem]


class Profile(ProfileDraft):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    dropped: int = 0


# ---------- company insights ----------

class InsightFilters(BaseModel):
    industry: str | None = None
    role: str | None = None
    kind: str | None = None


class Insight(BaseModel):
    id: str
    kind: str
    text: str
    industry: str | None = None
    role: str | None = None
    evidence: str = "observed_once"
    occurred_at: str = ""


# ---------- HTTP-only shapes ----------

class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: Literal["sales_exec", "admin"]
    customer_ids: list[str]


class LoginOut(BaseModel):
    token: str
    user: UserOut


class CustomerIn(BaseModel):
    id: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=2, max_length=120)
    industry: str = Field(min_length=2, max_length=60)


class CustomerOut(BaseModel):
    id: str
    name: str
    industry: str
    bank_id: str
    status: Literal["creating", "active"]
    owner_user_id: str | None = None
    created_at: datetime | None = None


class SourceRow(BaseModel):
    document_id: str
    channel: str
    title: str
    occurred_at: str
    people: str | None = None
    memories: int | None = None


class CustomerDetail(BaseModel):
    customer: CustomerOut
    interactions: list[SourceRow]


class SourceText(BaseModel):
    document_id: str
    text: str


class IngestIn(BaseModel):
    interactions: list[Interaction] = Field(min_length=1, max_length=40)
    request_id: str | None = None


class JobOut(BaseModel):
    job_id: str
    status: Literal["running", "done", "failed"]
    stage: str
    result: IngestResult | None = None
    error: str | None = None


class RequestIn(BaseModel):
    prompt: str = Field(min_length=2, max_length=1000)
    pieces: list[str] = Field(default=[], max_length=8)   # ids from GET /api/prompt-pieces
    parent_request_id: str | None = None


class RequestOut(BaseModel):
    request_id: str
    customer_id: str
    prompt: str
    created_at: datetime
    report: Report


class RequestRow(BaseModel):
    request_id: str
    prompt: str
    created_at: datetime
    summary: str


class OrgSettings(BaseModel):
    main_prompt: str                   # what the org's briefs must deliver (editable)
    default_prompt: str
    is_default: bool
    locked_rules: str                  # shown read-only: the evidence rules an edit cannot change
    placeholders: list[str]
    updated_by: str | None = None
    updated_at: datetime | None = None


class OrgSettingsIn(BaseModel):
    main_prompt: str = Field(min_length=20, max_length=4000)


class AssignIn(BaseModel):
    customer_ids: list[str]


InteractionPreview.model_rebuild()
