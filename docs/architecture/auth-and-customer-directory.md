# Authentication and customer directory

Status: **proposed** (2026-09-28). Who logs in, how customers are listed, and how a customer maps to its Hindsight
memory bank. Companion to [`call-memory-pipeline.md`](./call-memory-pipeline.md) and
[`hindsight-memory-shape.md`](./hindsight-memory-shape.md).

## 1. Two stores, two jobs

| Store | Holds | Never holds |
|---|---|---|
| **MongoDB** | Who can log in, what they may see, the list of customers and which memory bank each one uses | Conversation content, transcripts, extracted facts |
| **Hindsight** | Everything the customer said and everything learned (one bank per customer + `company`) | Logins, passwords, permissions |

MongoDB is the **directory**; Hindsight is the **memory**. Customer data stays in one place (Hindsight), and the
login/permission data stays out of it.

## 2. Collections

### `users`: sales executives (the people who log in and make calls)

```json
{
  "_id": "ObjectId",
  "email": "kami@ourco.example",
  "name": "Kami Bicknell",
  "password_hash": "argon2 / bcrypt hash, never the password",
  "role": "sales_exec",
  "customer_ids": ["acme", "globex"],
  "active": true,
  "created_at": "2026-09-28T10:00:00Z"
}
```

- `role`: `sales_exec` (sees only their assigned customers) or `admin` (sees and assigns all customers).
- `customer_ids`: the customers this person is allowed to open. This is the permission.

### `customers`: the accounts being sold to (they never log in)

```json
{
  "_id": "acme",
  "name": "Acme Manufacturing",
  "industry": "manufacturing",
  "bank_id": "cust-acme",
  "owner_user_id": "ObjectId of the sales exec",
  "status": "active",
  "created_at": "2026-09-28T10:00:00Z"
}
```

- `_id` is the customer id used in URLs; `bank_id` is the Hindsight bank.
- `industry` feeds the company-bank tag filter (`industry:manufacturing`) when building a brief.

## 3. The flow

```
Sales exec opens the app
   │
   ▼
Login (email + password) ──► POST /api/auth/login ──► session token (JWT, short-lived)
   │
   ▼
Customer list ──► GET /api/customers ──► only customers in the user's customer_ids (admin: all)
   │
   ▼
Select customer ──► customer page: timeline of interactions + "New request"
   │
   ▼
New request: the exec types a prompt, e.g.
  "I'm calling Acme tomorrow about the renewal. What should I ask? What are the next steps?"
   │
   ▼
POST /api/customers/{id}/requests  { prompt }
   │  server: check permission → look up bank_id in Mongo → run the agent
   │  agent: recall(cust-<id>) + recall(company, tags from customer.industry …) → Groq LLM → report
   ▼
Report shown to the exec: situation, open items, stakeholders, what to ask, talking points,
playbook tips, risks, next steps, follow-up draft (every item cited)
   │
   ▼
Exec makes the call ──► uploads recording / transcript ──► pipeline writes back to memory
   │
   ▼
Next request for this customer uses the new memory
```

New customer: `POST /api/customers` (after the "Create customer X?" confirmation) inserts the Mongo document with
`bank_id = "cust-<id>"` and adds the id to the creator's `customer_ids`. The Hindsight bank is created then too
(with our sales extraction config), so it exists before the first upload.

## 4. Rules the backend enforces

1. **Permission on every customer request, server-side.** Every `/api/customers/{id}/…` call checks that `id` is
   in the logged-in user's `customer_ids` (or the user is `admin`). Hiding customers in the UI is not enough:
   otherwise changing the id in the URL opens another exec's customer.
2. **`bank_id` comes from Mongo, never from the browser.** The client sends a customer id; the server looks up the
   bank. A client-supplied bank id would let anyone read any bank.
3. **The Hindsight and Groq keys stay on the server.** The browser only ever holds its own session token.
4. **Passwords are hashed** (argon2 or bcrypt); the token expires (e.g. 12 hours).
5. **Creating a customer touches two stores.** Write Mongo first with `status: "creating"`, create the bank, then
   set `status: "active"`. If the bank step fails, the record shows it and can be retried, instead of a customer
   that exists in one store and not the other.

## 5. API surface for this part

| Method | Path | Auth | Does |
|---|---|---|---|
| `POST` | `/api/auth/login` | none | Email + password → token |
| `GET` | `/api/auth/me` | token | Current user, role |
| `GET` | `/api/customers` | token | Customers this user may see |
| `POST` | `/api/customers` | token | Create customer (Mongo + Hindsight bank), assign to creator |
| `GET` | `/api/customers/{id}` | token + permission | Customer header + interaction timeline |
| `POST` | `/api/customers/{id}/requests` | token + permission | Prompt → agent → report |
| `POST` | `/api/customers/{id}/interactions` | token + permission | Upload call / email / chat / file (see memory-shape doc) |
| `POST` | `/api/users/{id}/customers` | admin | Assign customers to an exec |

Exact request/response shapes go in the API contracts doc (next).

## 6. For the hackathon

- **MongoDB Atlas free tier** works with a Vercel backend (connection string in `MONGODB_URI`).
- Seed two execs and two or three customers; one exec sees only their own, which demonstrates the permission
  rule in one click.
- The existing `DEMO_KEY` can stay as an outer gate on the public URL.

## Open

- Store past requests and reports in Mongo (a `requests` collection) so the exec can reopen yesterday's brief, or
  only in Hindsight? Proposed: Mongo keeps the report for display; Hindsight keeps a short "recommended X"
  experience fact so the learning loop can compare advice with outcome.
- Can two execs share a customer? The model allows it (`customer_ids` on each user); decide if the UI shows it.
- Login method: email + password for the demo; Google sign-in later.
