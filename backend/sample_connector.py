"""Demo connector: imports the sample CRM + conversation export INTO Hindsight.

This stands in for real connectors (HubSpot/Salesforce, Gmail, call recorder, WhatsApp Business).
It is the only code that reads the sample file; the agent and API read memory only from Hindsight.
"""
import json
from pathlib import Path

import agent

SAMPLE = Path(__file__).parent / "sample_data" / "acme_import.json"


def load():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def pending(known):
    """Sample messages not yet in memory, oldest first."""
    return [it for it in load()["interactions"] if it["id"] not in known]


def import_items(known, how_many=None):
    data = load()
    todo = pending(known)[:how_many]
    items = [agent.to_retain_item(data["deal"], it) for it in todo]
    if agent.DEAL_DOC not in known:
        items.insert(0, agent.deal_retain_item(data["deal"]))  # the deal record arrives with the first import
    if items:
        agent.retain(items)
    return [it["id"] for it in todo]
