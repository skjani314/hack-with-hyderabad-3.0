"""Load data/experiences.json into the Hindsight bank.

    python seed.py            # create bank if missing, retain all experiences (~$0.35)
    python seed.py --reset    # delete the bank first (empty-memory demo, then seed again)
    python seed.py --check    # recall a known dangerous reading and print what comes back
"""
import json
import sys
from pathlib import Path

import agent

BATCH = 25


def main():
    hs = agent.client()
    if "--check" in sys.argv:
        s = agent.derive(dict(machine_id="M-103", variant="M", air_temperature_k=300.8, process_temperature_k=309.4,
                              rpm=1342, torque_nm=62.4, tool_wear_min=113))
        found = agent.recall(s)
        print(f"recalled {len(found)} experiences")
        print(json.dumps(agent.decide(s, found), indent=2)[:2000])
        return
    if "--reset" in sys.argv:
        hs.delete_bank(bank_id=agent.BANK)
        print("bank deleted")
        return
    try:
        hs.create_bank(bank_id=agent.BANK, name="Machine Never Miss",
                       mission="Remember machine near-misses, failures, interventions and outcomes "
                               "so maintenance engineers can recognise precursor patterns early.")
    except Exception as e:  # already exists
        print("create_bank:", str(e)[:120])
    items = [agent.to_retain_item(e) for e in json.loads((Path(__file__).parent.parent / "data" / "experiences.json").read_text())]
    for i in range(0, len(items), BATCH):
        agent.client().retain_batch(bank_id=agent.BANK, items=items[i:i + BATCH])
        print(f"retained {min(i + BATCH, len(items))}/{len(items)}")


if __name__ == "__main__":
    main()
