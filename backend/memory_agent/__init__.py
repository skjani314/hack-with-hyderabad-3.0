"""Sales memory agent. The backend calls only these functions (docs/architecture/contracts.md §4)."""
from .core import (  # noqa: F401
    create_customer_memory,        # A1
    prepare_interaction,           # A2
    ingest_interaction,            # A3
    generate_report,               # A4
    get_profile,                   # A5
    list_company_insights,         # A6
    list_sources,
    rebuild_ledger,                # the deal ledger from scratch (existing customers, repairs)
    source_text,
)
from .errors import AgentError  # noqa: F401
