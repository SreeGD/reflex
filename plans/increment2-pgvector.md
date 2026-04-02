# Plan: Increment 2 — pgvector Knowledge Base + PostgreSQL Persistence

> Source PRD: https://github.com/SreeGD/reflex/issues/3

## Architectural decisions

Durable decisions that apply across all phases:

- **Database**: Local PostgreSQL with pgvector extension, `DATABASE_URL` env var
- **Driver**: `psycopg[binary]` (psycopg3) for SQLAlchemy 2.0 async + LangGraph
- **Engine**: Global `AsyncEngine` + `async_sessionmaker` in `backend/app/db.py`
- **Fallback**: No `DATABASE_URL` → in-memory (current behavior). Demo stays zero-dependency.
- **Embedding**: Auto-detect from `OPENAI_API_KEY` (1536d) or local sentence-transformers (384d). Dimension via `EMBEDDING_DIM` env var.
- **Schema**: `knowledge_chunks` (pgvector), `incidents` (JSONB state), LangGraph checkpoint tables
- **Migrations**: Alembic with async support
- **Ingestion**: `python -m backend.app.knowledge.ingest` CLI, reads `mock/data/`, semantic chunking by markdown headings

---

## Phase 1: Database foundation

**User stories**: 6, 8, 14

### What to build

Database connection module (`backend/app/db.py`) with async engine, sessionmaker, and `get_db` dependency. Alembic configuration with async support. Initial migration creating `knowledge_chunks` and `incidents` tables with pgvector extension. Environment-based configuration: if `DATABASE_URL` is set, create engine; if not, return None. All downstream code checks for engine availability before using DB.

### Acceptance criteria

- [ ] `backend/app/db.py` creates async engine from `DATABASE_URL` or returns None
- [ ] `alembic.ini` and `alembic/` directory configured for async migrations
- [ ] First migration creates `knowledge_chunks` table with VECTOR column and `incidents` table
- [ ] `alembic upgrade head` succeeds against local PostgreSQL with pgvector
- [ ] `pgvector` extension auto-created in migration
- [ ] Existing tests pass without `DATABASE_URL` set

---

## Phase 2: Embedding provider

**User stories**: 7, 13

### What to build

Embedding provider protocol and factory, following the existing LLM provider pattern. OpenAI embeddings when API key available, local sentence-transformers as fallback. Both produce vectors of the configured dimension. Mock embedding provider for testing returns zero vectors.

### Acceptance criteria

- [ ] `EmbeddingProvider` protocol with `embed(texts: List[str]) -> List[List[float]]` method
- [ ] `OpenAIEmbeddingProvider` using `text-embedding-3-small` with configurable dimensions
- [ ] `LocalEmbeddingProvider` using `sentence-transformers/all-MiniLM-L6-v2`
- [ ] `MockEmbeddingProvider` returning zero vectors (for tests)
- [ ] Factory auto-detects from environment
- [ ] `sentence-transformers` is an optional dependency (`pip install -e ".[embeddings]"`)
- [ ] Tests verify correct provider selection and output dimensions

---

## Phase 3: Knowledge ingestion CLI

**User stories**: 5, 9, 11

### What to build

CLI command that reads all mock data files, chunks them semantically, generates embeddings, and upserts into the `knowledge_chunks` table. Markdown files split on `##` headings. Jira tickets split by field. Each chunk gets a deterministic ID (source_type + source_id + chunk_index) for upsert idempotency. Dry-run mode prints chunks without database access.

### Acceptance criteria

- [ ] `python -m backend.app.knowledge.ingest` loads all 31 data files
- [ ] Markdown chunked by `##` headings, preserving section structure
- [ ] Jira tickets chunked into summary, description, resolution_notes
- [ ] Each chunk embedded via the embedding provider
- [ ] Upsert: re-running doesn't create duplicates
- [ ] `--dry-run` flag prints chunks and stats without DB access
- [ ] Reports: X chunks created, Y embeddings generated, Z seconds elapsed

---

## Phase 4: PgVectorKnowledgeProvider

**User stories**: 2, 12

### What to build

A new `PgVectorKnowledgeProvider` that fulfills the `KnowledgeProvider` protocol using pgvector similarity search. `search_similar()` embeds the query, then runs `SELECT ... ORDER BY embedding <=> query_embedding LIMIT N`. `get_runbook()` and `get_ticket()` query by source_id. The provider factory returns this when `DATABASE_URL` is set, otherwise `MockKnowledgeProvider`.

### Acceptance criteria

- [ ] `search_similar(query)` returns ranked results using cosine similarity
- [ ] Results include source_type, source_id, title, content, score, metadata
- [ ] `get_runbook(id)` returns full runbook content
- [ ] `get_ticket(key)` returns full ticket dict
- [ ] Provider factory auto-selects: DB available → PgVector, else → Mock
- [ ] RCA node uses PgVector provider transparently (no code changes in rca.py)
- [ ] Search quality: "database connection pool" returns RB-001 as top result

---

## Phase 5: PostgreSQL incident store

**User stories**: 3, 4, 15

### What to build

`PostgresIncidentStore` implementing the same interface as `InMemoryIncidentStore` (put, get, list_all, list_since, update, to_summary_list). Full pipeline state stored as JSONB. The singleton `incident_store` in `backend/app/incidents.py` is selected by factory: DB available → Postgres, else → in-memory. All API endpoints and chat tools work unchanged.

### Acceptance criteria

- [ ] `PostgresIncidentStore` with same interface as `InMemoryIncidentStore`
- [ ] Incidents persist across server restarts
- [ ] `GET /incidents` returns incidents from PostgreSQL
- [ ] `POST /incidents/{id}/approve` updates incident in PostgreSQL
- [ ] Webhook-created incidents visible after restart
- [ ] Fallback to in-memory when no DATABASE_URL
- [ ] Existing tests pass (use in-memory, no DB needed)

---

## Phase 6: AsyncPostgresSaver for chat

**User stories**: 1

### What to build

Wire LangGraph's `AsyncPostgresSaver` as the chat checkpointer when `DATABASE_URL` is available. The checkpointer tables are auto-created by `AsyncPostgresSaver.setup()`. Conversation state survives server restarts. Falls back to `MemorySaver` without DB.

### Acceptance criteria

- [ ] Chat conversations persist across server restarts
- [ ] `GET /chat/{session_id}/history` returns history after restart
- [ ] Multi-turn context retained after restart
- [ ] Falls back to MemorySaver without DATABASE_URL
- [ ] LangGraph checkpoint tables auto-created on first use

---

## Phase 7: Integration + documentation

**User stories**: 6, 10

### What to build

End-to-end integration: start server with DATABASE_URL, send webhook, chat about the incident, restart server, verify everything persists. Update README with PostgreSQL setup instructions, Alembic commands, ingest CLI usage. Update CLAUDE.md with new conventions. Add `.env.example`.

### Acceptance criteria

- [ ] Full flow works: ingest → webhook → chat → restart → data persists
- [ ] README documents: PostgreSQL setup, pgvector install, alembic upgrade, ingest CLI
- [ ] `.env.example` with DATABASE_URL, EMBEDDING_DIM, OPENAI_API_KEY
- [ ] All existing tests pass without DATABASE_URL
- [ ] New tests for embedding provider, ingestion chunking, provider factories
