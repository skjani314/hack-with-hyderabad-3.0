"""python test_memory_agent.py  -- parsing, evidence gate and leak checks. No network, no keys needed."""
from contracts import CustomerContext, Extraction, Interaction, Participant, ReportDraft, Turn
from memory_agent import core, parsing
from memory_agent.errors import DuplicateContent

ctx = CustomerContext(customer_id="acme", bank_id="cust-acme", name="Acme Manufacturing", industry="manufacturing",
                      exec_name="Kami Bicknell")

# 1. WhatsApp exports: Android and iOS formats, multi-line messages, day-first dates, de-duplication
android = """12/09/2026, 21:16 - Messages and calls are end-to-end encrypted.
12/09/2026, 21:16 - Dana Whitfield: Hi Kami, finance wants the cost case
before Friday
12/09/2026, 21:18 - Kami Bicknell: Sending it tomorrow
13/09/2026, 9:02 am - Dana Whitfield: <Media omitted>
13/09/2026, 9:05 am - Dana Whitfield: Priya approved the questionnaire"""
items, new, dup = parsing.parse_whatsapp(android, set(), set())
assert [i.document_id for i in items] == ["WA-2026-09-12", "WA-2026-09-13"], items
assert new == 3 and dup == 0 and items[0].turns[0].text.endswith("before Friday"), items[0].turns
assert items[1].turns[0].at == "09:05" and items[1].mode == "replace"
again, new2, dup2 = parsing.parse_whatsapp(android + "\n13/09/2026, 10:00 am - Dana Whitfield: Call at 4?",
                                           {"WA-2026-09-13"}, {fp for i in items for fp in i.fingerprints})
assert new2 == 1 and dup2 == 3 and again[0].mode == "append" and again[0].turns[0].text == "Call at 4?", again

ios = "[09/12/26, 9:16:05 PM] Uday: price is too high\n[09/13/26, 10:01:00 AM] Uday: ok send the quote"
items, _, _ = parsing.parse_whatsapp(ios, set(), set())
assert [i.document_id for i in items] == ["WA-2026-09-12", "WA-2026-09-13"], [i.document_id for i in items]
assert items[0].turns[0].at == "21:16", items[0].turns[0]
us = "12/13/2026, 9:00 - Sam: month-first because 13 can't be a month"
assert parsing.parse_whatsapp(us, set(), set())[0][0].document_id == "WA-2026-12-13"

# 2. Channel detection
assert parsing.detect_channel(android) == "whatsapp"
assert parsing.detect_channel("From: a@b.com\nTo: c@d.com\nSubject: Quote\n\nHi") == "email"
assert parsing.detect_channel("Kami: hello\nDana: hi there\nKami: how is the lab?") == "call"
assert parsing.detect_channel("x", "call.mp3") == "call" and parsing.detect_channel("x", "q.pdf") == "document"
assert parsing.detect_channel("remember to send the deck") == "note"

# 3. Email: headers, body, Message-ID fingerprint, id numbering
eml = (b"From: Michael Torres <michael@acme.example>\r\nTo: Kami <kami@us.example>\r\nSubject: Price vs Nexbyte\r\n"
       b"Date: Sun, 16 Aug 2026 10:00:00 -0500\r\nMessage-ID: <abc@acme>\r\nContent-Type: text/plain\r\n\r\n"
       b"Nexbyte quoted 15% less.")
e = parsing.parse_email(eml, {"EM-01", "EM-02"}, set())
assert e.document_id == "EM-03" and e.title == "Price vs Nexbyte" and "15% less" in e.text, e
assert e.occurred_at.isoformat().startswith("2026-08-16") and e.participants[0].name == "Michael Torres"
try:
    parsing.parse_email(eml, set(), set(e.fingerprints))
    raise AssertionError("duplicate email accepted")
except DuplicateContent:
    pass

# 4. Transcript text becomes speaker turns; rendering adds header, sides and keeps the raw body separate
t = parsing.parse_text("Kami: What would success look like?\nDana (Eng Mgr): Runs under 3 hours.\nsame day results",
                       "call", {"CALL-01"}, "Discovery", None,
                       [Participant(name="Dana Whitfield", side="customer", role="Engineering Manager")])
assert t.document_id == "CALL-02" and len(t.turns) == 2 and t.turns[1].text.endswith("same day results")
core._apply_sides(t, t.participants, "Kami Bicknell")
assert [x.side for x in t.turns] == ["ours", "customer"], t.turns
r = parsing.render(t)
assert r.startswith("[CALL-02] CALL on ") and "Kami (our side): What would" in r and "Dana (customer)" in r, r
assert not t.text.startswith("[CALL-02]")  # raw body stays raw, so an edited preview re-renders cleanly

# 5. Ids
assert parsing.next_id("email", {"EM-01", "EM-09", "CALL-02"}) == "EM-10"
assert parsing.next_id("outcome", set()) == "OUT-01"

# 6. Evidence gate: unknown ids dropped, case-insensitive match returns the stored spelling
known = {"CALL-03", "EM-02", "INS-3fa2c1ab", "FILE-proposal-v2"}
assert core._gate_ids(["[EM-02]", "EM-99", "ins-3FA2C1AB", "FILE-PROPOSAL-V2"], known) == \
    ["EM-02", "FILE-proposal-v2", "INS-3fa2c1ab"]
s = core._strip_unknown("Price [EM-02] and [CALL-11] and [EM‑02] ok", known)
assert s == "Price [EM-02] and and [EM-02] ok", s

# 7. Company insights must not name the customer or its people
it = Interaction(document_id="CALL-02", channel="call", occurred_at=parsing.now(), title="x", text="",
                 participants=[Participant(name="Michael Torres")], turns=[Turn(speaker="Priya", text="hi")])
blocked = core._names_to_block(ctx, it, None)
assert core.leaks("Michael pushed back on price", blocked) and core.leaks("Acme wanted ROI", blocked)
assert core.leaks("Priya approved it", blocked) and core.leaks("Kami offered a discount", blocked)
assert not core.leaks("Finance controllers at manufacturing companies want a 3-year cost comparison", blocked)

# 8. Long text is split into chunks under the token budget, nothing lost
long = "\n".join(f"line {i} " + "word " * 40 for i in range(200))
parts = core._chunks(long, 2500)
assert len(parts) > 1 and all(core.llm.approx_tokens(p) <= 2600 for p in parts) and "\n".join(parts) == long

# 9. LLM schemas are Groq-strict: every property required, no extra properties, at every level
def strict(schema, defs):
    if "$ref" in schema:
        return strict(defs[schema["$ref"].split("/")[-1]], defs)
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        assert schema.get("additionalProperties") is False, schema.get("title")
        assert set(schema.get("required", [])) == set(props), (schema.get("title"), set(props) - set(schema.get("required", [])))
        for p in props.values():
            strict(p, defs)
    for key in ("items",):
        if key in schema:
            strict(schema[key], defs)
    for alt in schema.get("anyOf", []):
        strict(alt, defs)
for model in (Extraction, ReportDraft):
    js = model.model_json_schema()
    strict(js, js.get("$defs", {}))

# 10. A single pasted WhatsApp message (not an export) is kept as plain text, not rejected
single = parsing.parse_text("Priya says she still has not received the questionnaire.", "whatsapp", {"WA-2026-09-12"},
                            "Dana: IT still waiting", None, [])
assert single.document_id == "WA-01" and single.channel == "whatsapp" and not single.turns
assert parsing.detect_channel(single.text) != "whatsapp"  # so prepare_interaction routes it to parse_text

# 11. Groq wait time: Retry-After header wins, else the "try again in" text; unknown → None
from memory_agent import llm, memory
class E(Exception):
    def __init__(self, msg, headers=None): super().__init__(msg); self.headers = headers or {}; self.body = msg
assert llm._retry_after([E("x", {"retry-after": "7"})]) == 7.0
assert abs(llm._retry_after([E("Rate limit reached ... Please try again in 6.52s. Need more tokens?")]) - 6.52) < 1e-6
assert abs(llm._retry_after([E("try again in 450ms")]) - 0.45) < 1e-6
assert llm._retry_after([E("try again in 1m3.5s")]) == 63.5 and llm._retry_after([E("boom")]) is None

# 12. Recalled lines carry every real source id; untraceable facts get none, so they can't be cited
assert memory.Fact(["WA-02"], "2026-08-25", "throttled", []).line() == "[WA-02] 2026-08-25 throttled"
assert memory.Fact(["CRM-04", "WA-02"], "", "competitor", []).line() == "[CRM-04][WA-02] competitor"
assert memory.Fact([], "", "merged", []).line() == "- merged"

# 13. Stored dates carry different UTC offsets: sort as instants, not strings
from datetime import datetime, timezone
a, b = "2026-09-09T10:00:00-05:00", "2026-09-09T12:00:00+00:00"   # a is 15:00 UTC, so it is LATER than b
assert sorted([a, b], key=core._when) == [b, a] and sorted([a, b]) == [a, b]
assert core._when("") == datetime.min.replace(tzinfo=timezone.utc)

# 14. Newest interactions are listed with their summaries, oldest of the three first
docs = [{"id": f"EM-0{i}", "document_metadata": {"occurred_at": f"2026-09-0{i}T10:00:00+00:00", "channel": "email",
                                                 "title": f"t{i}", "summary": f"s{i}"}} for i in range(1, 6)]
lat = core._latest(docs)
assert [x.split("]")[0] for x in lat] == ["[EM-03", "[EM-04", "[EM-05"] and lat[-1].endswith("t5: s5"), lat

# 15. Interaction ids from the browser are validated (never INS-…, never free text)
from pydantic import ValidationError
for bad in ("INS-3fa2c1ab", "CALL 07", "", "X-01"):
    try:
        Interaction(document_id=bad, channel="note", occurred_at=parsing.now(), title="t", text="x")
        raise AssertionError(f"accepted {bad!r}")
    except ValidationError:
        pass

# 16. Groq 413 sizes are read from its message; the smallest overshoot across fallback models wins
assert llm._too_large([E("Request too large ... on tokens per minute (TPM): Limit 6000, Requested 7400"),
                       E("... Limit 8000, Requested 7400 ...")]) == (8000, 7400)
assert llm._too_large([E("boom")]) is None

# 17. When the newest-interactions block must shrink, the NEWEST survives (it keeps the brief current)
lines = [f"[EM-0{i}] " + "word " * 40 for i in range(1, 4)]   # oldest → newest, ~50 tokens each
kept = core._fit(lines[::-1], 60)[::-1]
assert kept == [lines[-1]], kept

print("ok")
