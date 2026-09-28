"""Build the demo deal: REAL CRM rows + generated conversations.

CRM: Maven Analytics "CRM Sales Opportunities" (fictional B2B computer-hardware company; 85 accounts,
8,800 opportunities). Account facts, the open opportunity, the sales agent/manager and the account's
won/lost history are taken from the CSVs as-is. Dates are shifted into 2026 for the demo.
Conversations (email, calls, WhatsApp) are generated to fit that opportunity and marked synthetic;
they only restate CRM facts that are true in the data.

    python backend/build_deal.py   ->  backend/acme_deal.json
"""
import csv
import io
import json
import urllib.request
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
RAW = DATA / "raw" / "crm.zip"
URL = "https://maven-datasets.s3.amazonaws.com/CRM+Sales+Opportunities/CRM+Sales+Opportunities.zip"
OUT = Path(__file__).parent / "acme_deal.json"  # inside backend/ so the Vercel backend deploy includes it

ACCOUNT, OPPORTUNITY = "Acme Corporation", "S3W6Q07M"
DEAL_START = date(2026, 8, 3)       # the open opportunity's engage date is moved here
HISTORY_END = date(2026, 7, 31)     # the account's closed deals are moved to end just before it

# Generated conversations for the open opportunity. {placeholders} are filled from the CRM rows.
CONVERSATIONS = [
    ("EM-01", "email", 1, "Dana: our simulation workloads are too slow",
     {"from": "Dana Whitfield <dana.whitfield@acme-corp.example>", "to": "{agent} <{agent_email}>"},
     "Hi {first}, our hardware engineering team runs thermal and stress simulations overnight, and each run now "
     "takes 9 to 11 hours on our current servers. Engineers wait a full day for results, which is slowing our Q4 "
     "product launch. We've bought {product} from you before and the team liked it. Can we talk about another one "
     "for the simulation lab? We need it running before the launch freeze on 15 October. Thanks, Dana Whitfield, "
     "Engineering Manager, {account}."),
    ("CALL-01", "call", 4, "Discovery call (Dana, Sam)",
     {"participants": "{agent}; Dana Whitfield (Engineering Manager); Sam Keller (Procurement Lead)"},
     "Call transcript (30 min).\n{first}: What would success look like?\nDana: Simulation runs under 3 hours, so "
     "engineers get results the same day.\nSam: From procurement side, delivery time matters most. Last quarter a "
     "different supplier delivered 5 weeks late and we missed a milestone.\n{first}: {product} ships in about 10 "
     "business days from order.\nSam: Also any purchase above 5,000 dollars needs sign-off from our finance "
     "controller, Michael Torres.\nDana: And it must fit our existing rack and power setup, no facility changes.\n"
     "{first}: I will send the rack and power specs today."),
    ("WA-01", "whatsapp", 9, "Dana: finance wants the cost case",
     {"from": "Dana Whitfield"},
     "Hi {first}, Michael from finance asked why we can't just add cloud compute instead. He wants a simple cost "
     "comparison, one page, before he approves anything above 5k."),
    ("EM-02", "email", 13, "Michael: price and competitor quote",
     {"from": "Michael Torres <michael.torres@acme-corp.example>", "to": "{agent} <{agent_email}>"},
     "{first}, thanks for the cost note. {list_price_text} is higher than we expected. Nexbyte has quoted about 15% "
     "less for a similar server. I also need the 3-year cost including support, compared with renting cloud "
     "compute for the same workload. Please use our actual run hours, not generic benchmarks. Michael Torres, "
     "Finance Controller."),
    ("CALL-02", "call", 18, "IT security call (Priya)",
     {"participants": "{agent}; Priya Nair (IT Security Manager); Dana Whitfield"},
     "Call transcript (35 min).\nPriya: Before anything connects to our lab network I need to know about firmware "
     "security. Secure boot? TPM?\n{first}: Yes, both, and signed firmware updates.\nPriya: We manage devices through "
     "our central device management tool. It has to enrol there. And when hardware is retired, drives must be "
     "certified wiped.\n{first}: We provide a certified drive-wipe service.\nPriya: Send me our 30-question hardware "
     "security questionnaire filled in. I cannot approve without it.\n{first}: I will send it by 30 August."),
    ("WA-02", "whatsapp", 22, "Dana: Nexbyte trial feedback",
     {"from": "Dana Whitfield"},
     "{first}, Nexbyte sent a trial unit. Honestly it throttled under our 6-hour thermal simulation, the run took "
     "longer than expected. My engineers prefer yours. But Michael still keeps pushing on price."),
    ("EM-03", "email", 25, "{first}: next steps and commitments",
     {"from": "{agent} <{agent_email}>", "to": "Dana Whitfield; Priya Nair; Michael Torres"},
     "Hi all, thank you for this week. Next steps from our side: (1) completed security questionnaire to Priya by "
     "30 August, (2) 3-year cost comparison against cloud compute using Acme's real run hours to Michael by "
     "5 September, (3) confirm a delivery slot so the server is live before 15 October. Best, {agent}."),
    ("CRM-04", "crm", 29, "Opportunity update (next step, close target)",
     {},
     "CRM note on opportunity {opp}: next step - finance approval by Michael Torres after cost comparison. "
     "Competitor on deal: Nexbyte. Target close: 30 September 2026 (Acme quarter-end budget cut-off). Stage in CRM: "
     "{stage}."),
    ("CALL-03", "call", 37, "Pricing call (Michael, Dana)",
     {"participants": "{agent}; Michael Torres (Finance Controller); Dana Whitfield"},
     "Call transcript (25 min).\nMichael: Your 3-year comparison shows the server pays for itself against cloud in "
     "about 14 months. That works. But Nexbyte is still cheaper.\n{first}: Nexbyte's unit throttled in Dana's own "
     "simulation test, so the real run time was longer.\nMichael: Fair. If we also order the 3-year support plan, "
     "can you do 10% off?\n{first}: I need to check with my manager, {manager}. I will confirm by Friday.\nMichael: "
     "Budget closes at quarter end, 30 September. I need the final quote a week before."),
    ("WA-03", "whatsapp", 43, "Dana: IT still waiting",
     {"from": "Dana Whitfield"},
     "{first}, quick heads up. Priya says she still has not received the security questionnaire. She's annoyed, "
     "she said IT will not approve the purchase without it. Can you send it today?"),
]


def load_csvs():
    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, RAW)
    z = zipfile.ZipFile(RAW)
    return {n[:-4]: list(csv.DictReader(io.TextIOWrapper(z.open(n), "utf-8-sig")))
            for n in z.namelist() if n.endswith(".csv") and n != "data_dictionary.csv"}


def money(v):
    return f"${float(v):,.0f}"


def build():
    t = load_csvs()
    acc = next(a for a in t["accounts"] if a["account"] == ACCOUNT)
    opp = next(o for o in t["sales_pipeline"] if o["opportunity_id"] == OPPORTUNITY)
    team = next(s for s in t["sales_teams"] if s["sales_agent"] == opp["sales_agent"])
    price = next(p for p in t["products"] if p["product"] == opp["product"])

    closed = [o for o in t["sales_pipeline"] if o["account"] == ACCOUNT and o["deal_stage"] in ("Won", "Lost")]
    shift = HISTORY_END - max(date.fromisoformat(o["close_date"]) for o in closed)
    first_day = min(date.fromisoformat(o["engage_date"]) for o in closed) + shift
    by_product = Counter((o["product"], o["deal_stage"]) for o in closed)
    products = sorted({o["product"] for o in closed})
    won = [o for o in closed if o["deal_stage"] == "Won"]
    same = [o for o in closed if o["product"] == opp["product"]]
    last_same = max(same, key=lambda o: o["close_date"])

    agent, first = team["sales_agent"], team["sales_agent"].split()[0]
    fill = dict(agent=agent, first=first, agent_email=f"{first.lower()}@clarity-hw.example", manager=team["manager"],
                product=opp["product"], account=ACCOUNT, opp=OPPORTUNITY, stage=opp["deal_stage"],
                list_price_text=f"The list price of {money(price['sales_price'])}")

    def at(days):
        return f"{DEAL_START + timedelta(days=days)}T10:00:00-05:00"

    crm = [
        ("CRM-01", "crm", -30, "Account record",
         f"CRM account record: {ACCOUNT}. Sector: {acc['sector'].replace('technolgy', 'technology')}. "
         f"Established {acc['year_established']}. Annual revenue {money(float(acc['revenue']) * 1e6)}. "
         f"Employees: {int(acc['employees']):,}. Headquarters: {acc['office_location']}."),
        ("CRM-02", "crm", -3, "Account purchase history",
         f"CRM account history for {ACCOUNT} ({first_day:%b %Y} to {HISTORY_END:%b %Y}): {len(closed)} closed "
         f"opportunities, {len(won)} won and {len(closed) - len(won)} lost, total won revenue "
         f"{money(sum(float(o['close_value']) for o in won))}. By product: "
         + "; ".join(f"{p} {by_product[(p, 'Won')]} won / {by_product[(p, 'Lost')]} lost" for p in products)
         + f". Most recent {opp['product']} opportunity: {last_same['opportunity_id']}, {last_same['deal_stage']}, "
         f"closed {date.fromisoformat(last_same['close_date']) + shift}."),
        ("CRM-03", "crm", 0, "Opportunity created",
         f"CRM opportunity {OPPORTUNITY}: {ACCOUNT}, product {opp['product']} (series {price['series']}, list price "
         f"{money(price['sales_price'])}). Owner: {agent}, manager {team['manager']}, {team['regional_office']} "
         f"regional office. Stage: {opp['deal_stage']}. Engaged {DEAL_START}."),
    ]
    interactions = [dict(id=i, channel=c, date=at(d), title=title, content=text) for i, c, d, title, text in crm]
    for i, c, d, title, people, text in CONVERSATIONS:
        interactions.append(dict(id=i, channel=c, date=at(d), title=title.format(**fill),
                                 **{k: v.format(**fill) for k, v in people.items()}, content=text.format(**fill)))
    interactions.sort(key=lambda x: x["date"])

    return {
        "deal": {
            "deal_id": OPPORTUNITY, "customer": ACCOUNT, "product": opp["product"],
            "industry": acc["sector"].replace("technolgy", "technology"),
            "value": money(price["sales_price"]) + " list price", "stage": opp["deal_stage"],
            "salesperson": f"{agent} ({team['regional_office']} office, manager {team['manager']})",
            "sources": ("CRM records: Maven Analytics 'CRM Sales Opportunities' dataset (real rows, dates shifted to "
                        "2026). Emails, calls and WhatsApp: generated sample conversations. All people and "
                        "companies are fictional."),
        },
        "interactions": interactions,
    }


if __name__ == "__main__":
    d = build()
    ids = [i["id"] for i in d["interactions"]]
    assert len(ids) == len(set(ids))
    assert all("{" not in i["content"] for i in d["interactions"]), "unfilled placeholder"
    OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(ids)} interactions -> {OUT.name}")
    for i in d["interactions"]:
        print(f"  {i['date'][:10]}  {i['id']:8} {i['title']}")
    print("\n" + "\n\n".join(i["content"] for i in d["interactions"] if i["channel"] == "crm"))
