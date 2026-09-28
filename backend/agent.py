"""Machine Never Miss agent: sensor reading -> Hindsight recall -> decision -> (outcome) -> Hindsight retain.

The status is decided here from recalled experiences, so the demo is deterministic.
Hindsight reflect only writes the human explanation.
"""
import math
import os
import uuid
from collections import Counter
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
    modes = Counter(e["failure_mode"] for e in risky if e["failure_mode"])
    pattern = modes.most_common(1)[0][0] if modes else None

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
            # closest successful intervention for the dominant pattern; newest wins ties, so a just-learned outcome is used
            pool = [e for e in prevented if e["failure_mode"] == pattern] or prevented
            best = min(pool, key=lambda e: (e["distance"], -datetime.fromisoformat(e["timestamp"]).timestamp()))
            rec = f"Repeat what worked before: {best['action_taken']} (case {best['experience_id']})."
        else:
            rec = f"Escalate to maintenance inspection. Similar cases failed from {failed[0]['root_cause']}."

    # ponytail: frequency + outcome consistency only; add recency weighting if old cases dominate
    strength = round(0.6 * min(1, len(risky) / 8) + 0.4 * share, 2)

    return dict(
        status=status,
        pattern=pattern,
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


LEVELS = ["NORMAL", "MONITOR", "ESCALATE"]


def grade(status, outcome):
    """How good was the agent's call, judged in hindsight."""
    if outcome in ("failed", "prevented_failure"):
        # a real problem existed: ESCALATE (or MONITOR for a problem that was caught in time) was right
        return "caught" if status == "ESCALATE" or (status == "MONITOR" and outcome == "prevented_failure") else "missed"
    return "false_alarm" if status == "ESCALATE" else "correct"


def self_correct(s, d, reviews):
    """Adjust a decision using the agent's own graded past calls on similar readings. Pure."""
    near = [r for r in reviews if distance(s, r["sensor_state"]) < SIMILAR]
    by = {v: [r for r in near if r["verdict"] == v] for v in ("caught", "missed", "false_alarm", "correct")}
    original, note = d["status"], None
    i = LEVELS.index(original)
    if by["missed"] and original != "ESCALATE":
        m = max(by["missed"], key=lambda r: r["timestamp"])
        d["status"] = LEVELS[i + 1]
        note = (f"Raised from {original}: I under-called a similar reading before ({m['event_id']}, I said "
                f"{m['status']}) and it ended as {m['outcome'].replace('_', ' ')}.")
    # ponytail: 2 false alarms outweigh history; only when I never missed here. Tune if it lowers real risks.
    elif original == "ESCALATE" and len(by["false_alarm"]) >= 2 and not by["missed"] and len(by["false_alarm"]) > len(by["caught"]):
        d["status"] = "MONITOR"
        ids = ", ".join(r["event_id"] for r in by["false_alarm"][:3])
        note = f"Lowered from ESCALATE: my recent escalations on similar readings were false alarms ({ids})."
    d["self_check"] = dict(similar_reviews=len(near), caught=len(by["caught"]), missed=len(by["missed"]),
                           false_alarms=len(by["false_alarm"]), correct=len(by["correct"]),
                           original_status=original, adjustment=note)
    if note:
        d["recommendation"] = note + " " + d["recommendation"]
    return d


def review_item(s, event_id, status, outcome, action):
    verdict = grade(status, outcome)
    words = {"caught": "correct call, the risk was real", "missed": "I under-called a real problem",
             "false_alarm": "false alarm, nothing was wrong", "correct": "correct call, the machine was fine"}[verdict]
    ts = datetime.now(timezone.utc).isoformat()
    md = dict(kind="agent_review", event_id=event_id, status=status, outcome=outcome, verdict=verdict, timestamp=ts,
              **{k: str(s[k]) for k in SENSORS})
    text = (f"Agent self-review for machine {s['machine_id']}: on reading [{reading_text(s)}] I decided {status}. "
            f"Engineer action: {action}. Actual outcome: {outcome.replace('_', ' ')}. Verdict: {words}.")
    return verdict, dict(content=text, timestamp=ts, context="agent decision review", document_id=f"RV-{event_id}",
                         metadata=md, tags=["agent:review", f"machine:{s['machine_id']}"])


def recall_reviews(s):
    res = client().recall(bank_id=BANK, query="Agent self-review of my past decisions on: " + reading_text(s),
                          tags=["agent:review"], tags_match="any_strict", max_tokens=4096, budget="low")
    seen = {}
    for r in res.results:
        md = r.metadata or {}
        if md.get("kind") == "agent_review" and md["event_id"] not in seen:
            seen[md["event_id"]] = dict(event_id=md["event_id"], status=md["status"], outcome=md["outcome"],
                                        verdict=md["verdict"], timestamp=md["timestamp"],
                                        sensor_state={k: float(md[k]) for k in SENSORS})
    return list(seen.values())


PLAYBOOKS = {
    "HDF": "heat dissipation failures", "PWF": "power failures",
    "OSF": "overstrain failures", "TWF": "tool wear failures",
}


def playbook_id(mode):
    return f"playbook-{mode.lower()}"


def playbook_query(name):
    return (f"Maintenance playbook for {name}. Start with a '## Latest lessons' section listing the most recently "
            f"recorded engineer interventions and outcomes, quoting the exact action taken and its date. Then: which "
            f"sensor conditions came before failures and near-misses, which interventions prevented failure, and "
            f"where the agent's own past decisions turned out wrong (missed or false alarm). Be concise.")


def create_playbooks():
    """Hindsight mental models: self-maintained summaries the agent rewrites as memories arrive."""
    for mode, name in PLAYBOOKS.items():
        client().create_mental_model(
            bank_id=BANK, id=playbook_id(mode), name=f"Playbook: {name}", max_tokens=600,
            trigger={"refresh_after_consolidation": True},  # rewrites itself once new memories are processed
            source_query=playbook_query(name))


def refresh_playbook(mode):
    if mode in PLAYBOOKS:
        client().refresh_mental_model(bank_id=BANK, mental_model_id=playbook_id(mode))


def get_playbooks():
    out = []
    for mode, name in PLAYBOOKS.items():
        try:
            m = client().get_mental_model(bank_id=BANK, mental_model_id=playbook_id(mode), detail="content")
        except Exception:
            continue  # not created yet
        out.append(dict(pattern=mode, name=m.name, content=m.content, last_refreshed_at=m.last_refreshed_at))
    return out


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
    archive = client().recall(bank_id=BANK, query=query, max_tokens=8192, budget="mid")
    # Live-learned outcomes are few but the freshest lessons; a scoped recall stops the archive crowding them out.
    live = client().recall(bank_id=BANK, query=query, tags=["source:live"], tags_match="any_strict",
                           max_tokens=4096, budget="low")
    seen = {}
    for r in live.results + archive.results:
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
    adjust = d.get("self_check", {}).get("adjustment")
    try:
        return client().reflect(bank_id=BANK, budget="low", query=(
            f"Current reading: {reading_text(s)} The agent decided {d['status']} because these historical cases are "
            f"similar: {cases}." + (f" It also corrected itself: {adjust}" if adjust else "") +
            " In 2-3 sentences tell the maintenance engineer why, citing case ids, what happened in them, and any "
            "conflicting outcomes or context differences. Only use remembered evidence.")).text
    except Exception:
        return fallback


def analyze(reading, use_memory=True):
    s = derive(reading)
    if use_memory:
        d = self_correct(s, decide(s, recall(s)), recall_reviews(s))
        d["reason"] = explain(s, d)
    else:
        d = self_correct(s, decide(s, []), [])
        d["reason"] = "Memory off: judging from current values only. " + (
            "Some sensor values are elevated; monitor the machine." if describe(s) else "Values look normal.")
    d["event_id"] = f"EV-{uuid.uuid4().hex[:8]}"
    d["reading"] = s
    return d


def learn(event, action, outcome, notes=""):
    """Store what happened AND how good the agent's call was, then let the pattern playbook rewrite itself."""
    s = event["reading"]
    e = outcome_experience(s, event["event_id"], action, outcome, notes, event["pattern"])
    verdict, review = review_item(s, event["event_id"], event["status"], outcome, action)
    # memory-off calls are the "before" demo, not the agent's judgement, so they are not graded
    items = [to_retain_item(e)] + ([review] if event.get("memory", True) else [])
    client().retain_batch(bank_id=BANK, items=items)
    # No manual playbook refresh: it would run before Hindsight has processed the new memory.
    # Playbooks use refresh_after_consolidation, so they rewrite themselves once it is in.
    return e, verdict if event.get("memory", True) else None


def outcome_experience(s, event_id, action, outcome, notes="", pattern=None):
    kind = {"prevented_failure": "near_miss", "failed": "failure"}.get(outcome, "normal")
    ts = datetime.now(timezone.utc).isoformat()
    text = reading_text(s) + {
        "near_miss": f" Near-miss flagged by the agent. Engineer action: {action}. Outcome: failure prevented.",
        "failure": f" Engineer action: {action}. Outcome: machine failed.",
        "normal": f" Engineer action: {action}. Outcome: machine ran normally.",
    }[kind] + (f" Notes: {notes}" if notes else "")
    return dict(experience_id=event_id, machine_id=s["machine_id"], timestamp=ts, event_type=kind,
                failure_mode=pattern, sensor_state={k: s[k] for k in SENSORS}, action_taken=action,
                outcome=outcome, root_cause=notes or None, text=text,
                tags=[f"machine:{s['machine_id']}", f"event:{kind}", "source:live"])
