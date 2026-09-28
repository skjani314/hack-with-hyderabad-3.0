"""Turn the AI4I 2020 dataset into Machine Never Miss experiences.

Failures come straight from the dataset labels. Near-misses are rows that got
close to a documented failure rule (AI4I paper) but did not fail. Actions and
outcomes are not in the dataset, so they are filled from the failure mode.

    python backend/build_experiences.py   ->  data/experiences.json
"""
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
RAW = DATA / "raw" / "ai4i2020.csv"
OUT = DATA / "experiences.json"

# ponytail: retain costs ~2.4k tokens (~$0.024) per experience; 25 per bucket keeps seeding ~$5.5
CAP_FAILURE, CAP_NEAR_MISS, CAP_NORMAL = 25, 25, 25
OSF_LIMIT = {"L": 11000, "M": 12000, "H": 13000}  # tool wear x torque, per variant
PREFIX = {"normal": "NO", "near_miss": "NM", "failure": "FL"}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)

MODES = {
    "HDF": dict(name="heat dissipation failure", signals="small air-process temperature gap + low spindle speed",
                root_cause="insufficient heat dissipation", action="checked coolant flow and raised spindle speed"),
    "PWF": dict(name="power failure", signals="spindle power outside the 3.5-9 kW band",
                root_cause="power demand out of safe band", action="adjusted torque/speed setpoint back into power band"),
    "OSF": dict(name="overstrain failure", signals="high torque on a worn tool",
                root_cause="tool overstrain", action="replaced worn tool before continuing high-torque job"),
    "TWF": dict(name="tool wear failure", signals="tool wear above 200 min",
                root_cause="tool reached end of life", action="scheduled tool change"),
    "RNF": dict(name="random failure", signals="no identifiable precursor",
                root_cause="unknown / random", action="none"),
}


def derive(r):
    """Add the combined signals the failure rules use. Shared with the live agent."""
    return dict(r,
                temp_gap_k=round(r["process_temperature_k"] - r["air_temperature_k"], 1),
                power_w=round(r["torque_nm"] * r["rpm"] * 2 * math.pi / 60),
                strain=round(r["tool_wear_min"] * r["torque_nm"]))


def load():
    with RAW.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            yield derive(dict(
                udi=int(r["UDI"]), variant=r["Type"],
                air_temperature_k=float(r["Air temperature [K]"]), process_temperature_k=float(r["Process temperature [K]"]),
                rpm=int(r["Rotational speed [rpm]"]), torque_nm=float(r["Torque [Nm]"]), tool_wear_min=int(r["Tool wear [min]"]),
                failed=r["Machine failure"] == "1",
                labels=[m for m in MODES if r[m] == "1"],
            ))


def rule_hits(r, near=False):
    """Failure rules from the AI4I paper. near=True widens each by ~10% to catch near-misses."""
    k = 1.1 if near else 1.0  # ponytail: one margin for all modes; tune per mode if one floods the bank
    hits = []
    if r["temp_gap_k"] <= 8.6 * k and r["rpm"] < 1380 * k:
        hits.append("HDF")
    if r["power_w"] < 3500 * k or r["power_w"] > 9000 / k:
        hits.append("PWF")
    if r["strain"] > OSF_LIMIT[r["variant"]] / k:
        hits.append("OSF")
    if near and r["tool_wear_min"] >= 200:  # TWF is stochastic in 200-240 min, so only a near-miss signal
        hits.append("TWF")
    return hits


def text_for(r, kind, mode):
    m = MODES[mode] if mode else None
    s = (f"Machine {r['machine_id']} (variant {r['variant']}): air {r['air_temperature_k']}K, "
         f"process {r['process_temperature_k']}K (gap {r['temp_gap_k']}K), {r['rpm']} rpm, "
         f"torque {r['torque_nm']} Nm, power {r['power_w'] / 1000:.1f} kW, tool wear {r['tool_wear_min']} min.")
    if kind == "normal":
        return s + " All readings in normal range. No action taken. Outcome: machine ran normally."
    if kind == "near_miss":
        return (s + f" Near-miss: {m['signals']}, close to {m['name']}. Engineer {m['action']}. "
                f"Outcome: failure prevented. Suspected cause: {m['root_cause']}.")
    return (s + f" FAILURE: {m['name']} ({m['signals']}). No intervention; condition was not flagged in time. "
            f"Outcome: machine failed. Root cause: {m['root_cause']}. Preventive action: {m['action']}.")


def spread(items, cap):
    """Evenly sample across time instead of taking the first N."""
    step = max(1, len(items) // cap)
    return items[::step][:cap]


def build():
    rows = list(load())
    buckets = {"normal": [], **{("failure", m): [] for m in MODES}, **{("near_miss", m): [] for m in MODES}}
    for r in rows:
        r["machine_id"] = f"M-{101 + r['udi'] % 5}"  # ponytail: dataset has no machine id, spread rows over 5 machines
        if r["failed"]:
            mode = r["labels"][0] if r["labels"] else "RNF"
            buckets[("failure", mode)].append(r)
        elif near := rule_hits(r, near=True):
            buckets[("near_miss", near[0])].append(r)
        elif r["udi"] % 50 == 0:
            buckets["normal"].append(r)

    out = []
    for key, items in buckets.items():
        kind, mode = key if isinstance(key, tuple) else (key, None)
        cap = {"normal": CAP_NORMAL, "near_miss": CAP_NEAR_MISS, "failure": CAP_FAILURE}[kind]
        for r in spread(items, cap):
            m = MODES[mode] if mode else None
            out.append(dict(
                experience_id=f"{PREFIX[kind]}-{r['udi']}",
                machine_id=r["machine_id"],
                timestamp=(START + timedelta(minutes=35 * r["udi"])).isoformat(),
                event_type=kind,
                failure_mode=mode,
                sensor_state={k: r[k] for k in ("air_temperature_k", "process_temperature_k", "rpm", "torque_nm",
                                                "tool_wear_min", "temp_gap_k", "power_w")},
                action_taken=None if kind == "normal" else (m["action"] if kind == "near_miss" else "none"),
                outcome={"normal": "normal", "near_miss": "prevented_failure", "failure": "failed"}[kind],
                root_cause=m["root_cause"] if m else None,
                text=text_for(r, kind, mode),
                tags=[f"machine:{r['machine_id']}", f"event:{kind}"] + ([f"mode:{mode}"] if mode else []),
            ))
    out.sort(key=lambda e: e["timestamp"])
    return rows, out


def check(rows, out):
    # our rules must reproduce the dataset's own labels, or the "pattern" story is fiction
    for mode in ("HDF", "PWF", "OSF"):
        for r in rows:
            if mode == "HDF" and r["temp_gap_k"] == 8.6:
                continue  # published temps are rounded to 0.1K, so the exact boundary is ambiguous
            assert (mode in rule_hits(r)) == (mode in r["labels"]), (mode, r["udi"])
    assert len({e["experience_id"] for e in out}) == len(out)
    assert all(e["text"] for e in out)


if __name__ == "__main__":
    rows, out = build()
    check(rows, out)
    OUT.write_text(json.dumps(out, indent=2))
    counts = {}
    for e in out:
        k = f"{e['event_type']}:{e['failure_mode'] or '-'}"
        counts[k] = counts.get(k, 0) + 1
    print(f"{len(out)} experiences -> {OUT.name}")
    for k, v in sorted(counts.items()):
        print(f"  {k:18} {v}")
