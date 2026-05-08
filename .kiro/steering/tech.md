# Tech Stack

## Backend

- **Language:** Python 3.9+
- **Framework:** FastAPI (async)
- **Server:** Uvicorn (ASGI)
- **LLM:** Groq (`llama3-70b-8192`) via `langchain-groq`; Anthropic/OpenAI also supported
- **Vector store:** ChromaDB (local persistence at `backend/data/chroma/`)
- **Embeddings:** `sentence-transformers`
- **Validation:** Pydantic v2
- **HTTP client:** `httpx`
- **State persistence:** JSON files with `filelock` (no database)
- **Real-time:** WebSockets via FastAPI

## Frontend

- **Language:** TypeScript
- **Framework:** React 18
- **Build tool:** Vite
- **Styling:** Tailwind CSS + `tailwind-merge` + `clsx`
- **UI primitives:** Radix UI
- **Icons:** Lucide React
- **Test runner:** Vitest

## Testing (Backend)

- **Runner:** pytest with `asyncio_mode = auto`
- **Plugins:** `pytest-asyncio`, `pytest-mock`, `pytest-cov`, `pytest-xdist`, `pytest-timeout`
- **Timeout:** 30s per test

## Common Commands

### Backend

```bash
# Setup
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (port 8000)
uvicorn main:app --reload --port 8000

# Install test deps
pip install -r requirements-test.txt

# Run all tests
pytest backend/tests/ -v

# Run a specific module
pytest backend/tests/test_pipeline_e2e.py -v

# Run with coverage
pytest backend/tests/ --cov=backend

# Run in parallel
pytest backend/tests/ -n auto
```

### Frontend

```bash
# Setup
cd frontend
npm install

# Dev server (port 3000, proxies /api → localhost:8000)
npm run dev

# Type-check + production build
npm run build

# Run tests (single pass, no watch)
npm test
```

## Environment

Copy `.env.example` to `.env`. Minimum required for demo:

```
GROQ_API_KEY=...
AIRWEAVE_API_KEY=...
AIRWEAVE_COLLECTION_ID=...
```

See `docs/CONFIGURATION.md` for all options.
