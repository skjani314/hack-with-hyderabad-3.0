# Sales Memory Agent — the complete guide

**Remembers the customer so the salesperson doesn't have to.**

This is the one document to read before writing about, demoing, or judging the project. It covers what the app does,
how it uses Hindsight memory, how to use every screen, the exact prompts, a demo script, and what does not work yet.
Deeper design notes are linked at the end.

- **Live app:** https://frontend-one-liart-v1r1f1weeq.vercel.app
- **API:** https://backend-two-green-16.vercel.app
- **Code:** https://github.com/skjani314/hack-with-hyderabad-3.0
- **Logins (with passwords):** see [section 4](#4-logins).

---

## 1. The problem

Sales teams talk to a customer across calls, email, WhatsApp and the CRM. What the customer cares about, who objected
to what, what we promised and by when — it is scattered across all of them. Before a call, a salesperson either
re-reads everything or goes in half-prepared. And whatever one salesperson learns ("finance heads accept a 3-year cost
comparison instead of a discount") stays in their head; the next salesperson on the next account starts from zero.

## 2. What we built

A sales assistant with **two memories**:

1. **Customer memory** — one Hindsight memory bank per customer holding every call, email, chat and file.
2. **Company playbook** — one shared Hindsight bank of *generalised* lessons learned across all customers, with names
   removed ("a finance controller at a technology company accepted bundled support instead of a discount").

Every new interaction is split between the two. Every question the salesperson asks is answered from both. On top,
a **deal ledger** keeps each customer's *current* state (what's open, what's done, where each person stands), so
answers reflect the latest message, not an old one.

The one-sentence version: **the agent remembers the customer, and the company remembers what works.**

## 3. How it works

```
 salesperson adds a call / email / WhatsApp / CRM export / PDF
        │
        ▼
 PREVIEW  parse · transcribe audio (Groq Whisper) · label speakers (AI) · de-duplicate · pick the date
        │  (the salesperson checks speakers, names and date, then clicks Remember)
        ▼
 EXTRACT  one Groq call, strict Pydantic output
        ├── source text + customer facts ──► Hindsight bank  cust-<customer>
        └── generalised lessons (names removed) ──► Hindsight bank  company
        ▼
 LEDGER   one Groq call: current ledger + the new interaction → updated ledger (MongoDB)
          closes what's done, adds new commitments, moves people's stances — every line cites its source

 salesperson asks a question (+ picks call-type and focus chips)
        │
        ▼
 BRIEF    ledger (current state) + recall from the customer bank + recall from the company bank
          (same industry first) + the newest 3 interactions → Groq writes a structured brief
          → evidence gate (every cited id must exist) → the section that answers the question is shown first
```

### How Hindsight memory is used (for the "use of Hindsight" criterion)

| Step | Hindsight feature | Where |
|---|---|---|
| New customer | `create_bank` — one isolated bank per customer, with sales-specific extraction instructions | `memory_agent/memory.py` `ensure_bank` |
| Remember an interaction | `retain` with `document_id` (CALL-07, EM-12, WA-2026-09-24 …), timestamp, context, metadata, tags | `memory_agent/core.py` `_ingest` |
| WhatsApp days that grow | `retain` with `update_mode: append` | `parsing.parse_whatsapp` |
| Company lessons | `retain` into the shared `company` bank, tagged `industry:*`, `role:*`, `kind:*`; queued with `retain_async` | `core._ingest` |
| Answer a question | `recall` on the customer bank (3 angles) and on the company bank (filtered by industry, then all) with `include_source_facts` | `core._recall_both`, `memory.recall` |
| Cross-customer patterns | Hindsight **observations** (auto-merged conclusions) — **on** for the company bank | bank config |
| Show sources | `list_documents`, `get_document` (original text) | `memory.documents`, `memory.document_text` |

Hindsight's own knowledge graph (entities, links, temporal and keyword search) does the retrieval. Our code adds the
split between the two banks, the evidence gate, the deal ledger and the learning loop.

### What makes it more than a chatbot

- **It learns across customers.** A lesson learned on one account shows up, cited, in the brief for another. Demo:
  Globex had two interactions of its own, and its first brief already recommended "security documents early" and
  "a multi-year cost comparison with real usage" — learned on Acme and Brightline.
- **It learns from outcomes.** When a new interaction is linked to an earlier brief ("This follows the brief…"), the
  agent compares the advice with what happened and stores *what worked / what failed* marked **confirmed by outcome**.
- **It keeps the current state.** The deal ledger closes items when a message shows they happened, so a brief does
  not tell you to send something that was already received.
- **Every claim is sourced.** Each line links to the message it came from (click the grey chip) or to the playbook
  lesson (amber chip). Unsourced claims are removed and counted.
- **Privacy between customers.** Company lessons that name the customer or any of its people are withheld
  automatically; each customer's raw data lives only in its own bank.

### Tech stack

| Layer | Choice |
|---|---|
| Memory | Hindsight Cloud (Vectorize) — one bank per customer + one company bank |
| LLM | Groq: `openai/gpt-oss-120b`, fallbacks `gpt-oss-20b`, `qwen3.8-27b`; key rotation across several keys |
| Speech-to-text | Groq `whisper-large-v3-turbo` + an AI speaker-labelling step |
| Structured output | Pydantic models sent to Groq as **strict JSON schemas** (the model cannot return another shape) |
| Backend | Python, FastAPI, Pydantic AI, on Vercel |
| Directory & state | MongoDB Atlas: users, customers, saved briefs, org settings, deal ledgers |
| Frontend | React + TypeScript + Tailwind (Vite), on Vercel; API types generated from the backend's OpenAPI schema |

---

## 4. Logins

> **Temporary, for the judges.** These logins open the live app; they will be removed and the password changed
> after judging.

| Who | Email | Password | Role | Sees |
|---|---|---|---|---|
| Kami Bicknell | `kami@clarity.example` | `u0VNTWanCO42` | sales exec | Acme Corporation, Globex Systems |
| Rahul Mehta | `rahul@clarity.example` | `u0VNTWanCO42` | sales exec | Brightline Logistics |
| Sales Manager | `admin@clarity.example` | `u0VNTWanCO42` | admin | every customer + can edit **Settings** |

Use **Kami** for the demo; use **admin** only to show Settings.
A sales exec cannot open another exec's customer — the server checks every request.

### The demo customers

We are **Clarity Hardware**, selling servers and workstations. All people and companies are fictional.

| Customer | Industry | Story | Memory |
|---|---|---|---|
| **Acme Corporation** | technology | A full deal from first email to **won**: slow simulations → security review (Priya) → price pushback vs competitor Nexbyte (Michael) → support bundled instead of a discount → board approval → PO-88213, delivery 6 Oct | ~20 interactions (CRM rows from the real Maven Analytics CRM dataset + generated emails, calls, WhatsApp) |
| **Brightline Logistics** | logistics | Won: pilot proved the latency gain, 3-year support bundled instead of a discount | 5 interactions |
| **Globex Systems** | technology | A new customer: only an opportunity record and one email at the start — shows the company playbook helping from day one | 2+ interactions |

---

## 5. Using the app

### Customers
After login you see your customers. **New customer** (right side) asks for a name, an id and an industry, asks you to
confirm, and creates the customer's own memory bank.

### The customer page — three columns

**Left: memory and adding to it**
- **Memory: interactions** — every remembered call, email, chat and file, oldest first. Click one to read the original.
- **Add to memory**
  1. Choose **Paste text**, **Upload file** (call MP3, `.eml` email, WhatsApp "Export chat" `.txt`, CRM `.csv`,
     PDF / DOCX / XLSX, up to 4 MB) or **Recording URL** (long calls; Groq downloads it).
  2. **Type** — leave on *detect automatically* or pick one.
  3. **Happened on** — the date and time it happened. *Important:* the agent treats the newest interaction as the
     current state, so a wrong date changes the advice. Empty means "now".
  4. Optional title and participants (name, role, our side / customer) — they help label who said what.
  5. **Preview** shows exactly what will be remembered: you can fix speaker names and sides and the date (amber when
     it's today). Nothing is saved yet.
  6. **This follows the brief "…"** — tick it when this interaction is the result of the last brief you asked for;
     the playbook then learns what worked.
  7. **Remember** — saved to the customer's bank; lessons (names removed) go to the company playbook; the deal ledger
     updates. The green box says what was stored and how many lessons were added or withheld.

**Middle: ask the agent**
- **Kind of call** (pick one): Discovery · Demo / pilot review · Negotiation · Closing · Renewal / upsell · Follow-up.
- **Focus on** (any): Price objection · ROI for finance · Security / IT review · Beat the competitor · Build a
  champion · Get the PO signed. Hover a chip to see the exact text it adds to the prompt.
- Type your question, then:
  - **Get my brief** — a fresh answer from memory.
  - **Ask as follow-up** — continues from the brief on screen (the agent sees your previous question and its answer).
- **The brief** shows the deal's health and stage, a direct answer, and **the section that answers your question**:
  open items (for "what's open"), the email (for "draft an email"), objection replies with the playbook lessons behind
  them (for "they want a discount"), the stakeholder map, or the call plan. **More details** opens everything else:
  what to ask, risks, playbook tips, next steps, and how much of each memory was used.
- **Agent memory work** (bottom) lists every step: which recalls ran, what was retrieved, whether the ledger or a
  placeholder check changed anything.
- **Earlier briefs** — reopen any previous answer.

**Right: what memory knows**
- **Deal ledger** — the current state: stage, open items (owner, due date), where each customer person stands, done /
  resolved items, standing requirements. Updated on every upload; **Rebuild** recomputes it from all interactions.
- **What memory knows** — a profile (pain points, goals, stakeholders, objections, competitors, requirements,
  commitments, pricing). It refreshes when you click **Memory changed · Refresh** (to save AI calls).

### Company playbook (top menu)
Every lesson the agent learned across customers, filterable by industry and kind (*what worked*, *objection
handling*, *competitor intel* …). **Confirmed by outcome** marks lessons proven by a linked result.

### Settings (top menu)
The organisation's **main prompt** — what every brief must deliver. Admins edit it here (stored in MongoDB); the next
brief for every salesperson uses it. The **locked rules** on the right always apply and cannot be edited, because the
evidence checks depend on them.

---

## 6. The prompts

Every brief's prompt is built in layers:

1. **Organisation main prompt** — editable by an admin in Settings (default below).
2. **Locked rules** — always added; the evidence gate relies on them.
3. **Prompt pieces** — the chips the salesperson picked.
4. **The salesperson's question.**
5. **Memory**, in this order: deal ledger → conversation list → newest 3 interactions → customer facts → company
   playbook → (for a follow-up) the previous question and answer.

The texts below are generated from the code (`backend/memory_agent/`) at commit `ff9ef66`.

### 1. Organisation main prompt (default, editable in Settings)

Placeholders `{exec_name}`, `{customer}`, `{industry}` are filled in for each brief.

```text
You are the sales assistant of {exec_name}, who sells to {customer} ({industry}).

WHAT EVERY BRIEF MUST DELIVER
- Where the deal stands and what the customer is trying to achieve (their goals and pain, in their words).
- How to convince each stakeholder: what each person cares about and the argument that wins them.
- The objections raised so far, whether each is open or resolved, and what to say back.
- What to ask on the next call to move the deal forward, and the risks that could lose it.
- Concrete next steps and a short follow-up email.
```

### 2. Locked rules (always added)

```text
YOU GET TWO KINDS OF MEMORY
- CUSTOMER MEMORY: what this customer said and did, each fact prefixed with its source id like [CALL-03].
- COMPANY PLAYBOOK: generalised lessons learned from other customers, each prefixed with an id like [INS-3fa2c1].
Use both: the customer memory says what is true here, the playbook says what has worked elsewhere.

RULES (always apply)
- Every item's `sources` lists the ids it is based on, copied exactly from the memory lines. Customer claims cite
  customer ids; open_items cite customer ids only; playbook_tips cite INS ids. A date or fact is cited to the line it
  appears on, not to a nearby one.
- The DEAL LEDGER is the current state and wins over anything below it: an item marked done, resolved or dropped
  is finished and must not appear as open, pending or to-do. Each objection's `ledger_id` names its ledger item.
  Stakeholders are the customer's people only, never our own team.
- Later messages override earlier ones: if something was later sent, approved, replaced or resolved, it is done.
  MOST RECENT INTERACTIONS shows the newest state; check it before calling anything open or pending.
- A promise is not a delivery: "I will send X" means X is still open until a later message says it was sent,
  received or approved. Mark an objection resolved only when a message shows the customer accepted the answer.
- Never invent names, numbers, dates, prices, discounts, approvals or product specs that are not in memory. Advice is
  fine; made-up facts are not. Anything pending must be worded as pending (never "our analysis shows" for an
  analysis that has not been sent).
- If customer memory is empty, say so in `summary` and build the plan from the playbook only.
- `answer` answers the executive's request directly in under 120 words. Sections that don't apply may be empty.
- call_plan: one natural spoken line per step (opening, recap, discovery, value, objections, close).
  follow_up_email: under 120 words and it must not claim anything is attached, approved or confirmed unless memory
  says so.
```

### 3. Prompt pieces (the chips)

Pick one *kind of call* and any number of *focus* chips; each adds its text.

| Group | Chip | Adds to the prompt |
|---|---|---|
| Kind of call | **Discovery call** | This is a discovery call: prioritise questions that uncover pain, goals, decision process, budget and timeline. Keep pitching short. |
| Kind of call | **Demo / pilot review** | This is a demo or pilot review: tie every point to a pain the customer stated and to measurable results they can take to their decision makers. |
| Kind of call | **Negotiation** | This is a negotiation call: protect price, trade concessions for commitments (term, volume, timeline), and never offer a discount memory does not show as approved. |
| Kind of call | **Closing** | This is a closing call: confirm every open item is resolved, name the approver and the exact signing step, and ask for the decision. |
| Kind of call | **Renewal / upsell** | This is a renewal or expansion call: lead with the value already delivered, then the next need. |
| Kind of call | **Follow-up** | This is a follow-up: close the loop on every commitment made so far, especially overdue ones. |
| Focus on | **Price objection** | Focus on the price objection: reframe on total cost and payback, use what worked in the playbook. |
| Focus on | **ROI for finance** | Focus on the finance stakeholder: payback period, cost comparison, and the numbers they asked for. |
| Focus on | **Security / IT review** | Focus on the IT and security review: what they require, what is still missing, who signs off. |
| Focus on | **Beat the competitor** | Focus on the competitor: where we are stronger in this customer's own words and evidence. |
| Focus on | **Build a champion** | Focus on the internal champion: what they need from us to sell this inside their company. |
| Focus on | **Get the PO signed** | Focus on the path to a signed purchase order: approvals, paperwork, deadlines. |

### 4. Extraction (every new interaction: customer facts + company lessons)

Returns the `Extraction` schema. `{advice}` is filled only when the interaction is linked to an earlier brief: the agent then writes *what worked / what failed* lessons.

```text
You extract sales memory from one customer interaction.
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
Never invent facts that are not in the text.{advice}
```

### 5. Deal ledger update (every new interaction)

Returns the `LedgerUpdate` schema.

```text
You maintain the deal ledger for {customer}: the CURRENT state of the deal, not its history.
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
Keep text short: one sentence per item.
```

### 6. Hindsight retain instructions — customer banks

Configured on each customer bank; Hindsight's own extraction follows it.

```text
These are sales interactions with one customer account (call transcripts, emails, WhatsApp chats, CRM notes, documents, call outcomes). Extract: pain points and goals; objections and who raised them; stakeholders with role and what each cares about; competitors and what was said about them; requirements; pricing and discount discussions; commitments with owner and due date; deadlines; decisions and call outcomes. Keep the source id in square brackets (for example [EM-02]) and the date with each fact.
```

### 7. Hindsight retain instructions — company bank

```text
These are generalised sales lessons learned across many customers: what worked, what failed, how to handle objections, buyer-role patterns, competitor intelligence, pricing patterns. Keep each lesson general. Keep the lesson id in square brackets (for example [INS-3fa2c1]).
```

### 8. Company bank observations mission

```text
Record only generalised, reusable sales patterns by industry and buyer role. Never name a specific customer company or person.
```


---

## 7. Demo script (about 3 minutes)

1. **Log in as Kami → Globex** (a new customer, little memory). Pick **Negotiation** + **Price objection** and ask:
   *"Omar says a competitor is 12% cheaper and wants a discount. How do I handle it?"*
   → The objection answer comes first, backed by amber **INS-…** playbook lessons learned on Acme and Brightline
   ("bundle support instead of discounting"). Click an amber chip to show the lesson with no names in it.
2. **Acme** — ask *"Is anything still open? What do I need to do before delivery on 6 October?"*
   → The deal ledger says **won**; only delivery-day items are open; the stakeholder map shows everyone as supporter
   or champion. Click any grey chip to open the exact message behind a claim.
3. **Add to memory** on Globex: paste a short WhatsApp chat or email where the customer accepts bundled support,
   tick **This follows the brief**, and Remember → the green box shows lessons added; the **Company playbook** page
   shows a new lesson **confirmed by outcome**.
4. Ask the same Globex question again → the answer has moved on (the ledger closed the objection).
5. **Log in as admin → Settings** → change the main prompt (e.g. "Always end with one question for the CFO") →
   ask again → the brief follows it.

## 8. Happy-path test script (Globex, step by step)

**What this test proves, in the problem's own terms:** a salesperson should not have to re-read a customer's history
before a call, and what one account teaches should help the next. The test continues the **Globex Systems** deal
with a new chapter and checks four things in order:

1. **Memory is used** — before anything new is added, the brief already knows where Globex stands, with sources.
2. **Memory builds up** — after a new email and a call, the brief knows the new objection, the new person and the new
   deadlines, each linked to its source.
3. **Current state stays current** — when a later chat says something was sent, approved or accepted, the deal ledger
   closes it and briefs stop listing it as open.
4. **The company learns** — the outcome, linked to the brief that advised it, becomes a playbook lesson marked
   *confirmed by outcome*, and that lesson then shows up for a **different customer** (Acme).

**Before you start**
- Log in as **Kami** (`kami@clarity.example`, password in [section 4](#4-logins)) and open **Globex Systems**.
- **Run it once.** Memory remembers everything: pasting the same text a second time is rejected as "already in
  memory" — that is the duplicate check working, not a bug.
- Paste the texts below **exactly as shown, lines starting at the left edge** (copy from GitHub's rendered page or the
  raw file). Leave **Type** on *detect automatically* unless a step says otherwise.
- Each step takes 10–60 seconds (Groq's free tier); if a message says Groq is busy, wait a minute and retry.

**Where Globex stands before the test:** Lena Park (Verification Lead) wants overnight verification runs; Omar
(Finance Lead) accepted a 13-month payback and bundled support instead of a discount; security approved the
questionnaire; a PO for 10 units was expected "next week".

### Step 1 — a brief from existing memory
Chips: **Closing**. Ask:
```text
Where do we stand with Globex, and what's still open?
```
✅ **Check**
- The answer knows the story: payback accepted, bundled support agreed, security approved, PO expected.
- Every line has a grey source chip (`EM-01`, `WA-2026-09-24`, `OUT-01` …). Click one: the drawer shows the message.
- The **Deal ledger** panel (right) shows those items under **Done / resolved**.

### Step 2 — remember a new email (a new objection and a new person)
**Add to memory → Paste text.** Happened on: **26 Sep 2026, 10:00**. Paste:
```text
From: Omar <omar@globex.example>
To: Kami Bicknell <kami@clarity.example>
Cc: Ravi Menon <ravi.menon@globex.example>; Lena Park <lena.park@globex.example>
Subject: PO for 10 GTX Pro workstations - two blockers
Date: Sat, 26 Sep 2026 10:00:00 +0530

Hi Kami,

The PO for the 10 GTX Pro workstations is ready, but two things block it.

First, our procurement policy requires net-60 payment terms for a purchase this size. Your quote says net-30.

Second, Ravi Menon, our Head of Infrastructure, must sign off the rack and power requirements and an installation
date before anything ships. Our only maintenance window this month is 2 October.

Omar
Finance Lead, Globex Systems
```
**Preview** → type **Email**, title = the subject, date 26 Sep → **Remember**.

✅ **Check:** the green box says *Remembered EM-02*. The Deal ledger shows new open items (payment terms, Ravi's
sign-off) and **Ravi Menon** appears under "Where people stand".

### Step 3 — remember the call
**Add to memory → Paste text**, **Type: Call**, Happened on **27 Sep 2026, 11:00**. Add participants: *Kami
Bicknell · Account Executive · ours*, *Omar · Finance Lead · customer*, *Ravi Menon · Head of Infrastructure ·
customer*, *Lena Park · Verification Lead · customer*. Paste:
```text
Kami: Thanks for making time. Let's close the two open points: payment terms and installation.
Omar: Net-60 is our policy for purchases this size. Net-30 will not get through procurement.
Kami: I can't approve net-60 myself. I'll ask my manager, Summer, for net-45 and confirm by 28 September.
Ravi: Before anything ships I need the rack and power specs for the GTX Pro. Our only maintenance window is 2 October.
Kami: I'll send the specs today and an installation plan for 2 October by 28 September.
Lena: My team is ready to start verification runs the day it is installed.
Omar: If net-45 is approved, I'll raise the PO the same day.
```
**Preview** → each line is Kami (ours) or Omar / Ravi / Lena (customer); fix any wrong side → **Remember**.

Now ask, chips **Negotiation** + **Get the PO signed**:
```text
Omar wants net-60 payment terms. What's open, and how do I handle it?
```
✅ **Check**
- **Shown first:** the objection answer — payment terms, **open**, raised by Omar, with a suggested reply.
- **More details → Open items:** the net-45 approval and the installation plan (due 28 Sep) and the rack and power
  specs, owner Kami, each citing **CALL-01**.
- **Stakeholder map:** Omar, Ravi and Lena — **not Kami, not Summer** (our own side is filtered out).
- Click **CALL-01** on any line: the drawer shows the exact call.
- No "X%" or "[amount]" placeholders anywhere.

### Step 4 — a WhatsApp chat that closes things (current state stays current)
**Add to memory → Paste text** (the type detects WhatsApp; each day becomes its own document). Paste:
```text
27/09/2026, 16:10 - Kami Bicknell: Ravi, the rack and power specs for the GTX Pro are in your inbox.
27/09/2026, 18:45 - Ravi Menon: The specs fit our racks and power budget. 2 October works for installation.
28/09/2026, 10:05 - Kami Bicknell: Omar, Summer approved net-45 payment terms. The installation plan for 2 October is in your inbox.
28/09/2026, 10:30 - Omar: Net-45 works for procurement. I'm raising the PO for 10 units today.
```
**Preview** → two documents (`WA-2026-09-27`, `WA-2026-09-28`); set Ravi and Omar to **customer** if needed → tick
**This follows the brief "…"** → **Remember**.

Ask (**Follow-up** chip):
```text
Is anything still open? Where do we stand?
```
✅ **Check**
- **Shown first:** Open items. The specs, the installation plan and the net-45 approval are **gone** from the list;
  what remains is the PO and the installation on 2 October.
- **Deal ledger** (right): specs, plan and net-45 under **Done / resolved**; the payment-terms objection
  **resolved**; each citing a `WA-2026-09-…` document.
- **Where people stand:** Omar, Ravi and Lena are supporters or champions, not blockers.

### Step 5 — a draft email (the answer shape follows the question)
Ask:
```text
Draft a follow-up email to Omar, Ravi and Lena confirming the next steps.
```
✅ **Check:** the **email draft is shown first** with a **Copy** button; everything else sits under *More details*.
It mentions net-45 and installation on 2 October, and claims nothing memory does not say.

### Step 6 — the outcome (the company learns)
**Add to memory → Paste text**, **Type: Outcome**, Happened on **28 Sep 2026, 17:00**, tick **This follows the brief**:
```text
Result: Won. PO-GX-5521 received for 10 GTX Pro workstations with 3-year support. What worked: offering net-45 payment terms with manager approval instead of refusing net-60, and sending the rack specs and an installation plan before the infrastructure sign-off. Next step: install on 2 October.
```
✅ **Check**
- The green box reports new lessons added to the company playbook.
- **Deal ledger:** stage **won**.
- **Company playbook** page → filter **what worked** → a new lesson about payment terms marked **confirmed by
  outcome**, naming no customer or person.

### Step 7 — the lesson helps another customer
Open **Acme Corporation**, chips **Negotiation** + **Get the PO signed**, ask:
```text
A customer's procurement insists on net-60 payment terms. How do I handle it?
```
✅ **Check:** the objection answer cites **amber `INS-…` lessons**, including the payment-terms compromise learned
on Globex a minute ago. Click the amber chip: the lesson names no customer.

### Quick negative checks
| Try | Expected |
|---|---|
| Log in with a wrong password | "Wrong email or password" |
| As Kami, open `…/#/customer/brightline` in the address bar | "This customer is not assigned to you" |
| Paste the Step 2 email again on Globex | "This email is already in memory." |
| Paste the Step 4 chat again | "All … messages in this chat are already in memory." |
| As Kami, open **Settings** | The prompt is read-only ("Only an admin can change…") |

### If a check fails
Note the question and the time, and open **Agent memory work** under the brief: it lists what was recalled, whether
the ledger was read, and any retry. Answers are written by an AI, so wording differs between runs; the checks above
are about **which items are open or closed, who is on which side, and which sources are cited** — those should not
change.

## 9. Limits and known issues (be honest in the write-up)

- **Groq free tier**: 8,000 tokens per minute and 200,000 tokens per day per model per key. The app rotates across
  several keys and three models and waits when Groq says "try again in N s", but a burst of questions can still make
  one answer take 30–60 s.
- **Accuracy**: the evidence gate checks that every cited source exists, not that the model paraphrased it correctly.
  In testing the free-text answer occasionally still mentioned an item the ledger had closed; the open-items list is
  set in code from the ledger and is reliable.
- **Speaker labels** for uploaded audio are assigned by the AI (Whisper has no speaker separation) — check them in
  the preview.
- **Uploads** are limited to 4 MB (Vercel); long calls go in as a recording URL.
- **Pasted text** that arrives indented (copied from a terminal or a chat window) can lose email headers; paste plain
  text.
- **Live connectors** (MCube, WhatsApp Business, Gmail, CRM webhooks) are designed but not built; the POC uses manual
  upload. See `docs/architecture/call-memory-pipeline.md` §7.

## 10. Cost

- Hindsight Cloud (promo credit $50): about $0.02–0.05 per remembered item; recall is cheap; storage is free for 30 days.
- Groq: free tier.
- Vercel and MongoDB Atlas: free tiers.

## 11. For the judges' criteria

| Criterion | Where it shows |
|---|---|
| **Innovation** | Two memories (customer + company) with an automatic split; a deal ledger that keeps the current state; learning from linked outcomes |
| **Use of Hindsight memory** | One bank per customer + a shared company bank; retain with document ids, timestamps, tags, append; recall with tags and source facts; observations for cross-customer patterns — table in §3 |
| **Technical implementation** | Strict Pydantic schemas for every AI output; evidence gate; server-side permissions; key rotation and rate-limit handling; generated API types; offline test suite (`backend/test_memory_agent.py`) |
| **User experience** | The answer to your question first, the rest one click away; hover help on every control; preview-before-save; clickable sources |
| **Real-world impact** | Replaces re-reading a customer's history before every call; carries what one salesperson learned to the whole team |

## 12. Where to read more

| Doc | What |
|---|---|
| `README.md` | Setup, environment variables, deploy |
| `CHANGELOG.md` | Every change, with the reason |
| `docs/architecture/call-memory-pipeline.md` | Inputs, processing, memory, output |
| `docs/architecture/hindsight-memory-shape.md` | Banks, documents, retain fields, cost check |
| `docs/architecture/deal-ledger.md` | The ledger: why, how, what code guarantees |
| `docs/architecture/contracts.md` | Every API and agent contract |
| `docs/architecture/auth-and-customer-directory.md` | Logins, permissions, MongoDB |
| `docs/architecture/decisions.md` | Every decision and why |
| `docs/resources/hindsight.md` | What Hindsight is, with links |
