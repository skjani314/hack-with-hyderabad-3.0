"""MongoDB: the directory (who logs in, which customers exist, which bank each uses), plus saved reports and jobs.

Never conversation content: that lives only in Hindsight. docs/architecture/auth-and-customer-directory.md
"""
import os

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient

from memory_agent.errors import ConfigMissing

_client: AsyncMongoClient | None = None


def database():
    """Lazy, so the API still starts (and old routes still work) when MONGODB_URI is not configured."""
    global _client
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise ConfigMissing("MONGODB_URI is not set on the server")
    if _client is None:
        _client = AsyncMongoClient(uri, serverSelectionTimeoutMS=8000, appname="sales-memory-agent")
    return _client[os.getenv("MONGODB_DB", "sales-memory")]


async def ensure_indexes() -> None:
    db = database()
    await db.users.create_index([("email", ASCENDING)], unique=True)
    await db.requests.create_index([("customer_id", ASCENDING), ("created_at", DESCENDING)])
    await db.jobs.create_index([("created_at", DESCENDING)])
