"""python test_agent.py  -- evidence gate and memory formatting, no Hindsight needed."""
from agent import gate_answer, gate_profile, item_text, load_deal, to_retain_item

deal = load_deal()
it = next(i for i in deal["interactions"] if i["id"] == "EM-02")  # finance pricing email

# Every retained memory carries its source id, channel, date and deal tag
text = item_text(deal, it)
assert text.startswith("[EM-02] EMAIL on 2026-08-16") and "Michael" in text, text
r = to_retain_item(deal, it)
assert r["document_id"] == it["id"] and "deal:s3w6q07m" in r["tags"] and r["metadata"]["channel"] == "email"

# Profile gate: unsourced or invented sources are dropped, real ones kept
known = {"EM-01", "EM-02"}
p, dropped = gate_profile({
    "objections": [{"text": "too expensive", "sources": ["EM-02"]},
                   {"text": "invented objection", "sources": ["EM-99"]},
                   {"text": "no source at all", "sources": []}],
    "pain_points": [{"text": "reporting takes 5-6 days", "sources": ["[EM-01]", "CALL-01"]}],
}, known)
assert [o["text"] for o in p["objections"]] == ["too expensive"] and dropped == 2, (p, dropped)
assert p["pain_points"][0]["sources"] == ["EM-01"], p  # brackets stripped, unknown CALL-01 removed

# Answer gate: citations to messages not in memory disappear from the text too
text, srcs = gate_answer("CFO wants payback under 12 months [EM-02] and a board date [CRM-02].", ["EM-02", "CRM-02"], known)
assert "[CRM-02]" not in text and "[EM-02]" in text and srcs == ["EM-02"], (text, srcs)

# Every interaction id is unique and dated
ids = [i["id"] for i in deal["interactions"]]
assert len(ids) == len(set(ids)) and all(i["date"] for i in deal["interactions"])

print("ok")
