# Project Structure

## Top-Level Layout

```
backend/        Python FastAPI backend
frontend/       React/TypeScript frontend
docs/           Architecture and configuration docs
.env.example    All available environment variables
```

## Backend (`backend/`)

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app entry point — routes, WebSocket, pipeline orchestration |
| `config.py` | Centralized config via env vars; use `get_config()` singleton |
| `schemas.py` | Pydantic v2 data models shared across the app (`RawError`, `ErrorCluster`, etc.) |
| `state.py` | JSON-based state persistence; use `get_state_manager()` singleton |
| `pipeline/` | Core processing stages: clustering → search → analysis → actions |
| `core/` | Pure logic utilities: scoring, normalization, identity, confidence, signal fusion |
| `memory/` | Regression detection, incident graphs, hybrid search, evidence building |
| `observability/` | Metrics, traces, deployment tracking, anomaly detection, service topology |
| `sources/` | Data source adapters (`base.py` defines the interface; `sample_source.py` is the default) |
| `clients/` | External API clients: Airweave, Linear, Slack, ChromaDB |
| `repository/` | GitHub repo analysis and analysis state tracking |
| `ontology/` | Domain models and ontology definitions |
| `contracts/` | Typed contracts for analysis, evidence, memory, regression, retrieval |
| `samples/` | Sample error data for demo mode |
| `datasets/` | Incident corpus and replay engine for testing |
| `data/` | Runtime data — JSON state files and ChromaDB persistence (gitignored except `.gitkeep`) |
| `tests/` | pytest test suite (80+ tests across 4 modules) |
| `scripts/` | One-off utility scripts (ingestion, debugging) |

### Pipeline stages (`pipeline/`)

1. `clustering.py` — 3-stage: regex error-type grouping → LLM semantic clustering → LLM merge
2. `search.py` — Airweave context search (code, tickets, docs)
3. `enrichment.py` — Combines search results into enriched cluster context
4. `analysis.py` — Severity (S1–S4) and status (NEW / REGRESSION / ONGOING) determination
5. `semantic_matcher.py` — Deduplication against existing tickets and mutes
6. `actions.py` — Linear ticket creation and Slack alerting (or preview objects)

## Frontend (`frontend/`)

| Path | Purpose |
|------|---------|
| `src/App.tsx` | Root component — WebSocket connection, pipeline state |
| `src/components/` | Pipeline visualization UI components |
| `src/hooks/` | Custom React hooks |
| `src/lib/` | Shared utilities |
| `vite.config.ts` | Dev server on port 3000; proxies `/api` → `localhost:8000` |

## Key Conventions

- **New data sources** go in `sources/`, extending `base.py`'s `DataSource` interface.
- **New pipeline stages** go in `pipeline/` and are exported from `pipeline/__init__.py`.
- **Shared data models** go in `schemas.py` (Pydantic v2).
- **Config** is always read via `get_config()` — never access `os.environ` directly in feature code.
- **State** is always accessed via `get_state_manager()`.
- **Tests** live in `backend/tests/`; use `conftest.py` fixtures; mark async tests with `@pytest.mark.asyncio` (or rely on `asyncio_mode = auto`).
- **Debug/one-off scripts** go in `scripts/` or as top-level `debug_*.py` files — not in core modules.
