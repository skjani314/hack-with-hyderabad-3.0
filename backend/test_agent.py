"""python test_agent.py  -- decision logic against the seed data, no Hindsight needed."""
import json
from pathlib import Path

from agent import SENSORS, decide, derive, grade, outcome_experience, self_correct

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
learned = outcome_experience(heat, "EV-test", "reduced load and cleaned coolant filter", "prevented_failure", pattern="HDF")
learned["timestamp"] = "2099-01-01T00:00:00+00:00"
d = decide(heat, SEED + [learned])
assert "reduced load and cleaned coolant filter" in d["recommendation"] and "EV-test" in d["recommendation"], d

# Grading the agent's own calls in hindsight
assert grade("ESCALATE", "failed") == "caught" and grade("NORMAL", "failed") == "missed"
assert grade("MONITOR", "prevented_failure") == "caught" and grade("ESCALATE", "normal") == "false_alarm"


def review(verdict, status, outcome, ts="2026-09-01T00:00:00+00:00", eid="EV-r"):
    return dict(event_id=eid, status=status, outcome=outcome, verdict=verdict, timestamp=ts,
                sensor_state={k: normal[k] for k in SENSORS})


# A past miss on a similar reading raises the level, and says why
d = self_correct(normal, decide(normal, SEED), [review("missed", "NORMAL", "failed")])
assert d["status"] == "MONITOR" and "under-called" in d["self_check"]["adjustment"], d["self_check"]

# Repeated false alarms lower an escalation
far = [review("false_alarm", "ESCALATE", "normal", eid=f"EV-f{i}") for i in range(2)]
d = self_correct(normal, dict(decide(normal, SEED), status="ESCALATE"), far)
assert d["status"] == "MONITOR" and "false alarms" in d["self_check"]["adjustment"], d["self_check"]

# Reviews of a different situation change nothing
d = self_correct(heat, decide(heat, SEED), [review("missed", "NORMAL", "failed")])
assert d["status"] == "ESCALATE" and d["self_check"]["similar_reviews"] == 0, d["self_check"]

print("ok")
