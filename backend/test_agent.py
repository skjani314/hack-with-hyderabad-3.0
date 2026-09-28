"""python test_agent.py  -- decision logic against the seed data, no Hindsight needed."""
import json
from pathlib import Path

from agent import decide, derive, outcome_experience

SEED = json.loads((Path(__file__).parent.parent / "data" / "experiences.json").read_text())


def reading(**kw):
    return derive(dict(dict(machine_id="M-103", variant="M", air_temperature_k=300.0, process_temperature_k=311.0,
                            rpm=1550, torque_nm=40.0, tool_wear_min=60), **kw))


heat = reading(air_temperature_k=300.8, process_temperature_k=309.4, rpm=1340, torque_nm=55.0)  # known HDF pattern
normal = reading()

# Scenario 1: no memory -> never invents history
d = decide(heat, [])
assert d["status"] == "MONITOR" and d["historical_matches"] == 0, d

# Scenario 2: known dangerous pattern -> escalate, backed by real failures
d = decide(heat, SEED)
assert d["status"] == "ESCALATE", d
assert d["similar_failures"] >= 1 and all(e["distance"] < 1 for e in d["evidence"]), d

# healthy reading -> not escalated
d = decide(normal, SEED)
assert d["status"] == "NORMAL", d

# Scenario 3: a newly learned prevention is recommended next time
learned = outcome_experience(heat, "EV-test", "reduced load and cleaned coolant filter", "prevented_failure")
learned["timestamp"] = "2099-01-01T00:00:00+00:00"
d = decide(heat, SEED + [learned])
assert "reduced load and cleaned coolant filter" in d["recommendation"] and "EV-test" in d["recommendation"], d

print("ok")
