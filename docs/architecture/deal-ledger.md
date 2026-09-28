# Deal ledger

Status: **built** (2026-09-29). Code: `backend/memory_agent/ledger.py`, wired in `memory_agent/core.py`
(`ingest_interaction`, `rebuild_ledger`, `generate_report` → `_apply_ledger`), stored by `backend/api_v2.py`.

## Why

Hindsight keeps the **history**: every call, email and chat, split into facts. A brief used to work out the
**current state** from ~30 recalled facts every time. Old promises ("I will send the questionnaire") are permanent
facts and are said many times; the one line that closed them ("I got your questionnaire on Monday") is easy to miss.
Briefs showed finished items as open, stale stances, our own manager as a customer stakeholder, and placeholder
figures. Prompt rules ("later messages override earlier ones") did not fix it: the model can only apply them to what
it is shown.

The ledger is the one-page summary on top of the pile: the current state, written down and kept up to date.

## What it holds

One document per customer in MongoDB (`ledgers`, `_id` = customer id):

| Field | Meaning |
|---|---|
| `summary`, `stage` | Where the deal stands (2 sentences) and its stage |
| `items[]` | `id` (stable, `L-01`…), `kind` (commitment · objection · requirement · risk · decision), `text`, `owner`, `due`, `status` (open · at_risk · overdue · done · resolved · dropped), `sources` (interaction ids) |
| `people[]` | `name`, `role`, `side` (ours · customer), `stance` (blocker · skeptic · neutral · supporter · champion), `position`, `sources` |
| `based_on[]` | Every interaction folded in, oldest first |

It stays **derived state**: every line cites the Hindsight documents it came from, and it can be rebuilt from them at
any time. The conversations themselves still live only in Hindsight.

## How it is kept

```
upload → retain in Hindsight (as before) → LEDGER UPDATE → stored in Mongo
          one strict Groq call: CURRENT LEDGER + NEW INTERACTIONS → whole updated ledger (LedgerUpdate schema)
```

- **Update** (`ledger.update`): new interactions are fed one or two at a time (`MAX_BATCH_TOKENS = 1200`). With six
  per call the model skimmed and missed indirect closings ("your 3-year comparison shows…" = delivered).
- **Rebuild** (`rebuild_ledger`, `POST /api/customers/{id}/ledger/rebuild`, the *Rebuild* button): folds every stored
  interaction in date order. Used for existing customers and after repairing old data. Acme: ~2 minutes.
- **If the update fails** (LLM error, rate limit) the upload is still saved; the ledger catches up on the next upload
  or a rebuild.

## What code guarantees (not the prompt)

`ledger.merge`:
- existing ids stay stable; an item the model leaves out is **kept unchanged**, never silently deleted;
- a new item without a real source (an id that exists in the customer's bank) is refused;
- an updated item with no new evidence keeps its old sources;
- anyone matching our team (all app users, plus people the messages show work for us) is forced to side `ours`;
- `_close_duplicates`: an open item that says the same as a finished one (≥ 50% word overlap) closes with it.

`core._apply_ledger` (every brief):
- **open items come from the ledger**, not from the model: open commitments and decisions (standing requirements
  like "must fit the rack" stay in the ledger);
- objections take their status from the ledger item they reference (`ledger_id`);
- stakeholder stances come from the ledger; our own people are removed from the stakeholder map;
- the deal stage comes from the ledger.

`core._placeholders`: a draft with template figures (`X%`, `[amount]`, `TBD`) is sent back once with the instruction
to use only numbers from memory.

## Hindsight observations

Customer banks now have **observations off** (`enable_observations=False`): their merged conclusions had no source
of their own (the model borrowed a nearby id) and stayed stale for a while after a document was replaced. The ledger
does that job with a source on every line. The **company bank keeps observations on**: merging lessons across many
customers into patterns is what that bank is for.

## Verified on Acme (2026-09-29)

After a rebuild, against the messages: questionnaire done (`CALL-04`), firmware + wipe certificate open and overdue
(nothing says they were sent), 3-year comparison resolved (`CALL-03`), price objection resolved (`CALL-04`), final quote
done (`WA-2026-09-22`), Priya and Michael neutral, Dana champion, Summer on our side. The brief with the ledger listed
exactly those open items, no placeholder figures, and no one from our side in the stakeholder map.

Known gaps: the model's free-text answer can still mention an item the ledger has closed (seen once: "confirm the
delivery slot"); stances can differ between rebuilds; "rack and power specs" stays overdue because memory really has
no message saying they were sent.
