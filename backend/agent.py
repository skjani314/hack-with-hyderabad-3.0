"""Machine Never Miss agent: sensor reading -> Hindsight recall -> decision -> (outcome) -> Hindsight retain.

The status is decided here from recalled experiences, so the demo is deterministic.
Hindsight reflect only writes the human explanation.
"""
import math
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

from build_experiences import derive

load_dotenv()
BANK = os.getenv("HINDSIGHT_BANK", "machine-never-miss")
USE_REFLECT = os.getenv("USE_REFLECT", "1") == "1"  # reflect costs $0.05/call; set 0 while developing

SENSORS = ("air_temperature_k", "process_temperature_k", "rpm", "torque_nm", "tool_wear_min", "temp_gap_k", "power_w")
# How far apart two readings can be and still count as "the same situation", per signal.
# ponytail: hand-tuned scales on 4 signals; the knob to turn if matches feel too loose/strict
SCALES = {"temp_gap_k": 0.8, "rpm": 120, "torque_nm": 8, "tool_wear_min": 40}
SIMILAR = 1.0

_client = None


def client():
    global _client
    if _client is None:
        from hindsight_client import Hindsight
        _client = Hindsight(base_url=os.getenv("HINDSIGHT_URL", "https://api.hindsight.vectorize.io"),
                            api_key=os.environ["HINDSIGHT_API_KEY"])
    return _client


def describe(s):
    """Per-sensor words an engineer would use. Single-sensor bands only; the combinations come from memory."""
    words = []
    if s["temp_gap_k"] <= 9.5: words.append("small air-process temperature gap")
    if s["rpm"] < 1450: words.append("low spindle speed")
    if s["rpm"] > 2000: words.append("high spindle speed")
    if s["torque_nm"] > 55: words.append("high torque")
    if s["tool_wear_min"] >= 180: words.append("worn tool, tool wear above 180 min")
    if s["power_w"] < 4000: words.append("low spindle power")
    if s["power_w"] > 8500: words.append("high spindle power")
    return words


def reading_text(s):
    return (f"Machine {s['machine_id']} (variant {s['variant']}): air {s['air_temperature_k']}K, "
            f"process {s['process_temperature_k']}K (gap {s['temp_gap_k']}K), {s['rpm']} rpm, "
            f"torque {s['torque_nm']} Nm, power {s['power_w'] / 1000:.1f} kW, tool wear {s['tool_wear_min']} min.")


def distance(a, b):
    return math.sqrt(sum(((a[k] - b[k]) / v) ** 2 for k, v in SCALES.items()) / len(SCALES))


def decide(s, experiences):
    """Pure decision from the current reading + recalled experiences (dicts with sensor_state/outcome/...)."""
    signals = describe(s)
    similar = sorted((dict(e, distance=round(distance(s, e["sensor_state"]), 2)) for e in experiences),
                     key=lambda e: e["distance"])
    similar = [e for e in similar if e["distance"] < SIMILAR]
    # random failures have no precursor, so they are not evidence of a pattern
    failed = [e for e in similar if e["outcome"] == "failed" and e["failure_mode"] != "RNF"]
    prevented = [e for e in similar if e["outcome"] == "prevented_failure"]
    risky = failed + prevented
    share = len(risky) / len(similar) if similar else 0

    if not experiences:
        status = "MONITOR" if signals else "NORMAL"
        rec = "No historical experience for this condition yet. Monitor and record the outcome."
    elif not similar:
        status = "MONITOR" if signals else "NORMAL"
        rec = ("Unfamiliar condition: elevated signals but no similar history. Monitor and record the outcome."
               if signals else "No similar history and values look normal. Continue normal operation.")
    else:
        # ponytail: fixed cut-offs (3 cases, 50% / 20% share); tune on the demo scenarios
        status = ("ESCALATE" if len(risky) >= 3 and failed and share >= 0.5
                  else "MONITOR" if share >= 0.2 else "NORMAL")
        if status == "NORMAL":
            rec = "Similar past readings ran normally. Continue normal operation."
        elif prevented:
            # closest successful intervention; newest wins ties, so a just-learned outcome is used
            best = min(prevented, key=lambda e: (e["distance"], -datetime.fromisoformat(e["timestamp"]).timestamp()))
            rec = f"Repeat what worked before: {best['action_taken']} (case {best['experience_id']})."
        else:
            rec = f"Escalate to maintenance inspection. Similar cases failed from {failed[0]['root_cause']}."

    # ponytail: frequency + outcome consistency only; add recency weighting if old cases dominate
    strength = round(0.6 * min(1, len(risky) / 8) + 0.4 * share, 2)

    return dict(
        status=status,
        pattern_strength=strength,
        pattern_label="HIGH" if strength >= 0.6 else "MEDIUM" if strength >= 0.3 else "LOW",
        historical_matches=len(similar),
        similar_failures=len(failed),
        similar_prevented_events=len(prevented),
        recurring_signals=signals,
        recommendation=rec,
        evidence=[{k: e.get(k) for k in ("experience_id", "timestamp", "event_type", "failure_mode", "outcome",
                                         "action_taken", "root_cause", "distance", "text")} for e in similar[:8]],
    )


def _from_metadata(md):
    """Hindsight metadata values are strings; turn them back into an experience dict."""
    return dict(
        experience_id=md["experience_id"], timestamp=md["timestamp"], event_type=md["event_type"],
        failure_mode=md.get("failure_mode") or None, outcome=md["outcome"],
        action_taken=md.get("action_taken") or None, root_cause=md.get("root_cause") or None,
        text=md.get("text", ""), sensor_state={k: float(md[k]) for k in SENSORS},
    )


def to_retain_item(e):
    md = {k: str(v) for k, v in e.items() if k not in ("sensor_state", "tags") and v is not None}
    md.update({k: str(v) for k, v in e["sensor_state"].items()})
    return dict(content=e["text"], timestamp=e["timestamp"], context="machine maintenance log",
                document_id=e["experience_id"], metadata=md, tags=e["tags"])


def recall(s):
    query = reading_text(s) + " Signals: " + (", ".join(describe(s)) or "all normal") + \
        ". Similar near-misses, failures, interventions and outcomes."
    res = client().recall(bank_id=BANK, query=query, max_tokens=8192, budget="mid")
    seen = {}
    for r in res.results:
        md = r.metadata or {}
        if "experience_id" in md and md["experience_id"] not in seen:
            seen[md["experience_id"]] = _from_metadata(md)
    return list(seen.values())


def explain(s, d):
    """Hindsight reflect writes the 'why'. Falls back to a template so a reflect hiccup never breaks the demo."""
    fallback = (f"{d['historical_matches']} similar past cases: {d['similar_failures']} failed, "
                f"{d['similar_prevented_events']} were prevented by intervention.")
    if not USE_REFLECT or not d["evidence"]:
        return fallback
    cases = "; ".join(f"{e['experience_id']} ({e['outcome']}, {e['failure_mode']})" for e in d["evidence"])
    try:
        return client().reflect(bank_id=BANK, budget="low", query=(
            f"Current reading: {reading_text(s)} The agent decided {d['status']} because these historical cases are "
            f"similar: {cases}. In 2-3 sentences tell the maintenance engineer why, citing case ids, what happened "
            f"in them, and any conflicting outcomes or context differences. Only use remembered evidence.")).text
    except Exception:
        return fallback


def analyze(reading, use_memory=True):
    s = derive(reading)
    d = decide(s, recall(s) if use_memory else [])
    d["reason"] = explain(s, d) if use_memory else (
        "Memory off: judging from current values only. " +
        ("Some sensor values are elevated; monitor the machine." if describe(s) else "Values look normal."))
    d["event_id"] = f"EV-{uuid.uuid4().hex[:8]}"
    d["reading"] = s
    return d


def outcome_experience(s, event_id, action, outcome, notes=""):
    kind = {"prevented_failure": "near_miss", "failed": "failure"}.get(outcome, "normal")
    ts = datetime.now(timezone.utc).isoformat()
    text = reading_text(s) + {
        "near_miss": f" Near-miss flagged by the agent. Engineer action: {action}. Outcome: failure prevented.",
        "failure": f" Engineer action: {action}. Outcome: machine failed.",
        "normal": f" Engineer action: {action}. Outcome: machine ran normally.",
    }[kind] + (f" Notes: {notes}" if notes else "")
    return dict(experience_id=event_id, machine_id=s["machine_id"], timestamp=ts, event_type=kind,
                failure_mode=None, sensor_state={k: s[k] for k in SENSORS}, action_taken=action,
                outcome=outcome, root_cause=notes or None, text=text,
                tags=[f"machine:{s['machine_id']}", f"event:{kind}", "source:live"])


def retain(experience):
    client().retain_batch(bank_id=BANK, items=[to_retain_item(experience)])
