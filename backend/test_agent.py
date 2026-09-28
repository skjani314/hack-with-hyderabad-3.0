"""python test_agent.py  -- evidence gate, memory formatting and ids. No Hindsight needed."""
from agent import DEAL_DOC, deal_retain_item, gate_answer, gate_profile, item_text, next_id, to_retain_item
from sample_connector import load, pending

data = load()
deal = data["deal"]
it = next(i for i in data["interactions"] if i["id"] == "EM-02")  # finance pricing email

# 1. Every retained memory carries its source id, channel, date, people and deal tag
text = item_text(deal, it)
assert text.startswith("[EM-02] EMAIL on 2026-08-16") and "Michael" in text, text
r = to_retain_item(deal, it)
assert r["document_id"] == "EM-02" and "deal:s3w6q07m" in r["tags"], r
assert r["metadata"]["channel"] == "email" and "Michael" in r["metadata"]["from"], r["metadata"]

# 2. The deal record is itself a memory document, with all fields as metadata strings
d = deal_retain_item(deal)
assert d["document_id"] == DEAL_DOC and d["metadata"]["customer"] == "Acme Corporation"
assert all(isinstance(v, str) for v in d["metadata"].values())

# 3. New ids continue per channel and stay citeable
assert next_id("email", {"EM-01", "EM-03", "CALL-02"}) == "EM-04"
assert next_id("whatsapp", set()) == "WA-01" and next_id("outcome", {"OUT-01"}) == "OUT-02"

# 4. Profile gate: unsourced or invented sources are dropped, real ones kept
known = {"EM-01", "EM-02"}
p, dropped = gate_profile({
    "objections": [{"text": "too expensive", "sources": ["EM-02"]},
                   {"text": "invented objection", "sources": ["EM-99"]},
                   {"text": "no source at all", "sources": []}],
    "pain_points": [{"text": "slow simulations", "sources": ["[EM-01]", "CALL-01"]}],
}, known)
assert [o["text"] for o in p["objections"]] == ["too expensive"] and dropped == 2, (p, dropped)
assert p["pain_points"][0]["sources"] == ["EM-01"], p  # brackets stripped, unknown CALL-01 removed

# 5. Answer gate: citations to messages not in memory disappear from the text too
text, srcs = gate_answer("Finance wants 3-year cost [EM-02] and a budget date [CRM-04].", ["EM-02", "CRM-04"], known)
assert "[CRM-04]" not in text and "[EM-02]" in text and srcs == ["EM-02"], (text, srcs)

# 6. The connector only offers what memory does not hold yet, oldest first
left = pending({"CRM-01", "CRM-02"})
assert left[0]["id"] == "CRM-03" and all(i["id"] not in {"CRM-01", "CRM-02"} for i in left)

print("ok")
