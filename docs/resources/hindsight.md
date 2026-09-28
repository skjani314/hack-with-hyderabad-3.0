# Hindsight: what it is and why we use it

Hindsight (by Vectorize) is the memory layer the hackathon requires. This note explains what it is, how our repo
uses it, and where the official docs live. Links checked on 2026-09-28.

## In one paragraph

Hindsight is not a plain vector database like Pinecone. Pinecone is a filing cabinet: you put text in and later
get back the passages most *similar* to your question; it never reads them. Hindsight reads each conversation as
it is saved, pulls out the facts ("Michael is the finance controller", "Nexbyte quoted 15% less"), links them by
person and time, and notices when things change. When asked, it searches four ways at once (by meaning, by exact
names, by connections between people and topics, by time) and can reason over what it found to write an answer.
That fits sales, where the questions are about *who said what, and when*, not just "find similar text".

## The three operations

| Operation | Uses an LLM? | What it does |
|---|---|---|
| **retain** (save) | Yes | An LLM reads the content and extracts facts, entities (people, companies) and relationships. |
| **recall** (search) | No generative LLM | Returns matching facts as a list. Four search arms run in parallel (below), results are merged and reranked. |
| **reflect** (answer) | Yes | Recalls relevant memory, then an LLM reasons over it and writes an answer (optionally as JSON matching a schema). Checks sources in the order mental models → observations → raw facts. |

### Recall's four search arms ("TEMPR")

1. **Semantic**: similar meaning / paraphrases (vector embeddings)
2. **Keyword (BM25)**: exact names and terms
3. **Graph**: related entities and indirect connections
4. **Temporal**: time ranges ("last week", "in August")

Results are merged with RRF fusion, then reranked by a cross-encoder with a recency boost.

### What kinds of memory it keeps

| Type | Meaning | Sales example |
|---|---|---|
| World facts | Facts received from content | "Priya Nair is IT Security Manager" |
| Experience facts | The agent's own actions | "Recommended leading with the ROI case" |
| Observations | Auto-consolidated knowledge, tracks change over time | "Priya blocked on the questionnaire, now approved" |
| Mental models | User-curated summaries for common queries | A maintained "Acme deal brief" |

Other useful concepts:

- **Memory bank**: an isolated memory store. We use one bank, `sales-memory`, and scope each deal with a tag.
- **`document_id`**: groups content into a document. Retaining again with the same id **replaces** the old
  version (upsert). We use source ids (`EM-02`, `CALL-01`, `DEAL`) as document ids.
- **Tags**: filter recall/reflect to a subset of memory. We tag every item `deal:<id>` and `channel:<channel>`.

## What's underneath

- **Storage:** PostgreSQL 15+ with the pgvector extension (HNSW indexes). Oracle AI Database is an enterprise
  alternative. Local dev uses `pg0`, an embedded Postgres. The docs say they deliberately did not abstract storage
  behind a generic interface.
- **LLM:** configurable, 30+ providers including OpenAI, Anthropic, Gemini, **Groq** (default model there:
  `openai/gpt-oss-120b`), Ollama, Bedrock, plus any OpenAI-compatible API or LiteLLM. The model must support
  **at least 65,000 output tokens** for reliable fact extraction.
- **Embeddings:** default `BAAI/bge-small-en-v1.5` (384 dimensions).
- **Reranker:** default `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- **Hindsight Cloud:** the docs do **not** say which models Cloud uses.

## How this repo uses it (as of commit `7c998e1`)

| Our step | Hindsight call | Code |
|---|---|---|
| Create the bank with sales extraction instructions | `create_bank(retain_custom_instructions=..., reflect_mission=...)` | `backend/agent.py` `ensure_bank` |
| Save a conversation / outcome / deal record | `retain_batch` with `document_id`, tags, metadata, timestamp | `agent.retain`, `to_retain_item`, `deal_retain_item` |
| Show the source list and original text | documents API `list_documents` / `get_document` | `agent.sources`, `agent.source_text`, `agent.deal` |
| Build the deal profile | `reflect` with `response_schema=PROFILE_SCHEMA`, tag-scoped | `agent.profile` |
| Answer a question | `reflect` with `response_schema=CHAT_SCHEMA`, tag-scoped | `agent.chat` |
| "Memory off" demo | same `reflect`, scoped to an empty tag | `agent.chat` (`use_memory=False`) |
| Reset | `delete_bank` | `main.reset`, `seed.py --reset` |

Notes:

- We call **reflect** for every answer, so **Hindsight's LLM writes the answers** and bills Cloud credits. The
  backend holds only `HINDSIGHT_API_KEY`; there is no separate LLM key.
- We never call **recall** directly. The alternative design is `recall` → our own LLM (e.g. Groq), which gives full
  control over prompt, tone and format at the cost of more code. Open decision for planning.
- Client pinned to `hindsight-client==0.10.1` (`backend/requirements.txt`).
- Cost estimates from our README: ~$0.03 per retained message, ~$0.05 per reflect.

## Official links

### Start here
- Docs home: https://hindsight.vectorize.io/
- LLM-friendly index: https://hindsight.vectorize.io/llms.txt
- Full docs as one file: https://hindsight.vectorize.io/llms-full.txt
- Quickstart: https://hindsight.vectorize.io/developer/api/quickstart
- FAQ: https://hindsight.vectorize.io/faq
- Best practices: https://hindsight.vectorize.io/best-practices
- RAG vs Hindsight: https://hindsight.vectorize.io/developer/rag-vs-hindsight

### Repos, packages, cloud
- GitHub (source, issues): https://github.com/vectorize-io/hindsight
- Example agents (named in the hackathon brief): https://github.com/vectorize-io/self-driving-agents
- Hindsight Cloud console: https://ui.hindsight.vectorize.io
- Python client on PyPI: https://pypi.org/project/hindsight-client/
- TypeScript client: `npm install @vectorize-io/hindsight-client`
- Self-host with Docker: `ghcr.io/vectorize-io/hindsight` (needs `HINDSIGHT_API_LLM_PROVIDER` and `HINDSIGHT_API_LLM_API_KEY`)

### Concepts
- Retain: https://hindsight.vectorize.io/developer/retain
- Retrieval (recall): https://hindsight.vectorize.io/developer/retrieval
- Reflect: https://hindsight.vectorize.io/developer/reflect
- Observations: https://hindsight.vectorize.io/developer/observations
- Mental models: https://hindsight.vectorize.io/developer/mental-models
- Knowledge pages: https://hindsight.vectorize.io/developer/knowledge-pages
- Memory defense: https://hindsight.vectorize.io/developer/memory-defense
- Multilingual: https://hindsight.vectorize.io/developer/multilingual

### API
- API reference: https://hindsight.vectorize.io/api-reference
- OpenAPI spec: https://hindsight.vectorize.io/openapi.json
- Main methods: https://hindsight.vectorize.io/developer/api/main-methods
- Retain: https://hindsight.vectorize.io/developer/api/retain
- Recall: https://hindsight.vectorize.io/developer/api/recall
- Reflect: https://hindsight.vectorize.io/developer/api/reflect
- Memory banks: https://hindsight.vectorize.io/developer/api/memory-banks
- Bank templates: https://hindsight.vectorize.io/developer/api/bank-templates
- Documents: https://hindsight.vectorize.io/developer/api/documents
- Memories: https://hindsight.vectorize.io/developer/api/memories
- Mental models: https://hindsight.vectorize.io/developer/api/mental-models
- Knowledge pages: https://hindsight.vectorize.io/developer/api/knowledge-pages
- Operations: https://hindsight.vectorize.io/developer/api/operations
- Webhooks: https://hindsight.vectorize.io/developer/api/webhooks

### Running and configuring
- Installation: https://hindsight.vectorize.io/developer/installation
- Configuration: https://hindsight.vectorize.io/developer/configuration
- Models (LLM, embeddings, reranker): https://hindsight.vectorize.io/developer/models
- Storage: https://hindsight.vectorize.io/developer/storage
- Performance: https://hindsight.vectorize.io/developer/performance
- Monitoring: https://hindsight.vectorize.io/developer/monitoring
- Services: https://hindsight.vectorize.io/developer/services
- Extensions: https://hindsight.vectorize.io/developer/extensions
- Admin CLI: https://hindsight.vectorize.io/developer/admin-cli
- MCP server: https://hindsight.vectorize.io/developer/mcp-server
- Development: https://hindsight.vectorize.io/developer/development

### SDKs
- Python: https://hindsight.vectorize.io/sdks/python
- Node.js / TypeScript: https://hindsight.vectorize.io/sdks/nodejs
- Go: https://hindsight.vectorize.io/sdks/go
- CLI: https://hindsight.vectorize.io/sdks/cli
- Embedded: https://hindsight.vectorize.io/sdks/embed
- hindsight-all (Python): https://hindsight.vectorize.io/sdks/hindsight-all
- hindsight-all (npm): https://hindsight.vectorize.io/sdks/hindsight-all-npm
- Integrations index: https://hindsight.vectorize.io/integrations
- OpenClaw plugin (named in the brief): https://hindsight.vectorize.io/sdks/integrations/openclaw

### Cookbook (examples)
- Index: https://hindsight.vectorize.io/cookbook
- Quickstart recipe: https://hindsight.vectorize.io/cookbook/recipes/quickstart
- Per-user memory: https://hindsight.vectorize.io/cookbook/recipes/per-user-memory
- Support agent + shared knowledge: https://hindsight.vectorize.io/cookbook/recipes/support-agent-shared-knowledge
- Personal assistant: https://hindsight.vectorize.io/cookbook/recipes/personal_assistant
- Tool-learning demo: https://hindsight.vectorize.io/cookbook/recipes/tool-learning-demo
- Claude Agent SDK: https://hindsight.vectorize.io/cookbook/recipes/claude-agent-sdk
- Chat memory (Cloud): https://hindsight.vectorize.io/cookbook/applications/chat-memory-cloud
- Stance tracker (tracks changing positions): https://hindsight.vectorize.io/cookbook/applications/stancetracker
- Claims IQ: https://hindsight.vectorize.io/cookbook/applications/claims-iq
- Templates: https://hindsight.vectorize.io/templates

### Guides most relevant to us
- Sales research memory: https://hindsight.vectorize.io/guides/2026/06/02/guide-hermes-sales-research-memory-with-hindsight
- Hindsight vs RAG for agents: https://hindsight.vectorize.io/guides/2026/04/21/comparison-hindsight-vs-rag-for-ai-agents
- Single bank vs multi bank: https://hindsight.vectorize.io/guides/2026/04/16/comparison-single-bank-vs-multi-bank-hindsight
- Designing agents that remember what matters: https://hindsight.vectorize.io/guides/2026/04/23/guide-designing-ai-agents-that-remember-what-matters
- How AI agents learn across sessions: https://hindsight.vectorize.io/guides/2026/04/23/guide-how-ai-agents-learn-across-sessions
- Memory vs retrieval vs context: https://hindsight.vectorize.io/guides/2026/04/23/guide-the-difference-between-memory-retrieval-and-context
- All guides: https://hindsight.vectorize.io/guides
- Blog: https://hindsight.vectorize.io/blog
- Every page (sitemap): https://hindsight.vectorize.io/sitemap.xml

### Hackathon
- Problem statement (Google Doc): https://docs.google.com/document/d/1A4ezag02em823ZzYF34DiUVHUNLWI5ztm70QvWidWoQ/preview
- Cloud promo code: `MEMHACK99` ($50 credits, add under Billing after registering)
- Recommended LLM: Groq (https://groq.com/), models `openai/gpt-oss-120b` or `qwen/qwen3-32b`

## Sources for this note

- Docs home and `llms.txt`: the three operations, memory types, TEMPR, RAG comparison, `document_id` upsert.
- `developer/storage`: Postgres + pgvector.
- `developer/models`: LLM providers, defaults, 65k output token requirement, embedding and reranker models,
  and the absence of any statement about Cloud's models.
- `backend/agent.py`, `backend/main.py`, `README.md` in this repo: how we use it.
- Docs are versioned (e.g. `/0.7/...`); the links above are the current unversioned pages.
