"""Sales Memory Agent API.   Local: uvicorn main:app --reload   (run from backend/)

Routes live in api_v2.py (docs/architecture/contracts.md §5). MongoDB holds the directory (users, customers, saved
briefs, org settings); Hindsight holds everything the customers said, one bank per customer plus a shared `company`
playbook bank. Stateless on purpose (Vercel serverless).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # local dev: repo-root .env; on Vercel the env is set directly
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

import api_v2  # noqa: E402
import memory_agent  # noqa: E402

app = FastAPI(title="Sales Memory Agent")
# CLIENT_URL: deployed frontend URL(s), comma-separated. Localhost is always allowed for development.
PROD_FRONTEND = "https://frontend-one-liart-v1r1f1weeq.vercel.app"  # public URL, safe default if CLIENT_URL is unset
origins = ["http://localhost:5173"] + [u.strip().rstrip("/") for u in os.getenv("CLIENT_URL", PROD_FRONTEND).split(",") if u.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "Authorization"])
app.include_router(api_v2.router)


@app.get("/")
def health():
    return {"ok": True, "service": "sales-memory-agent", "version": 2}


@app.exception_handler(memory_agent.AgentError)
async def agent_error(_: Request, e: memory_agent.AgentError):
    """Typed agent errors → {error, message} with the contract's status code (contracts.md §6)."""
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, e: StarletteHTTPException):
    body = e.detail if isinstance(e.detail, dict) else {"error": "http_error", "message": str(e.detail)}
    return JSONResponse(body, status_code=e.status_code, headers=getattr(e, "headers", None))
