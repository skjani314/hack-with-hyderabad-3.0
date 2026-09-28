"""Import the sample CRM + conversations into Hindsight from the terminal.

    python seed.py           # import everything not yet in memory (~13 docs, ~$0.40)
    python seed.py --reset   # delete the memory bank first
"""
import sys

import agent
import sample_connector

if "--reset" in sys.argv:
    try:
        agent.client().delete_bank(bank_id=agent.BANK)
        print("memory bank deleted")
    except Exception as e:
        if not agent._not_found(e):
            raise
known = {s["id"] for s in agent.sources()}
ids = sample_connector.import_items(known)
print(f"imported {len(ids)} conversations into '{agent.BANK}':", ", ".join(ids) or "nothing new")
print("memory now holds:", ", ".join(s["id"] for s in agent.sources()))
