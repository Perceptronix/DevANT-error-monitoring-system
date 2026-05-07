# Intelligent Error Monitoring Agent

Build production-grade error monitoring with **semantic understanding**. This project shows how [Airweave](https://airweave.ai) transforms raw errors into actionable insights by connecting your codebase, tickets, and Slack discussions.

> **Background:** This project is based on our internal agent "Donke" that handles ~40,000 Airweave queries/month. Read more about [how we use Airweave to improve Airweave](https://airweave.ai/blog/how-we-use-airweave-to-improve-airweave).

<video width="100%" src="https://github.com/user-attachments/assets/4756ef10-8a8a-440f-a397-609e8afb3e44" controls></video>

## Why This Exists

Error monitoring tools give you alerts. What you actually need is **context**:
- What code is involved?
- Has someone already worked on this?
- Is this a new issue or a regression?

This agent uses Airweave to automatically find that context and make intelligent decisions about severity, deduplication, and alerting.

## What It Does

```
Raw Errors → [Clustering] → [Context Search] → [Analysis] → Intelligent Alerts
                  │               │               │
                  └── Groups      └── Airweave    └── Severity + status
                      similar         finds code,     determination with
                      errors          tickets, Slack  suppression logic
```

*Example: 20 raw errors → 4 actionable clusters → 4 alerts (instead of 20)*

---

# Part 1: Interactive Demo

The frontend provides a visual demonstration of how the error monitoring pipeline works. It's designed to showcase the tool's capabilities with sample data.

## Quick Start (2 minutes)

```bash
# Clone and setup
git clone <repo-url>
cd support-agent
cp .env.example .env

# Optional: Add LLM key for smarter clustering (works without it too)
# OPENAI_API_KEY=your_key  (or ANTHROPIC_API_KEY)

# Start backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Start frontend (new terminal)
cd frontend
npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000) and click **Run Demo**.

## What the Demo Shows

The interactive visualization walks you through:

1. **Raw Errors** - 20 sample production errors from a data sync platform
2. **Semantic Clustering** - Errors grouped by root cause (rate limiting, DB issues, auth failures, etc.)
3. **Context Search** - Related code, Linear tickets, and Slack threads found via Airweave
4. **Severity Analysis** - S1-S4 classification with reasoning
5. **Alert Preview** - What Slack messages and Linear issues would be created

The demo uses:
- **Sample data** by default (realistic errors from a SaaS platform)
- **Mock search results** showing what Airweave would return
- **Preview mode** for Linear/Slack (no actual tickets/messages created)

---

# Part 2: Production Setup

To use this as an actual error monitoring agent for your application:

## Step 1: Connect Your Error Source

Replace sample data with real errors from your monitoring stack.

### Option A: Sentry

```bash
DATA_SOURCE=sentry
SENTRY_AUTH_TOKEN=your_token
SENTRY_ORG_SLUG=your_org
SENTRY_PROJECT_SLUG=your_project  # Optional: filter to specific project
```

### Option B: Azure Log Analytics

```bash
DATA_SOURCE=azure
AZURE_TENANT_ID=your_tenant
AZURE_CLIENT_ID=your_client
AZURE_CLIENT_SECRET=your_secret
AZURE_LOG_ANALYTICS_WORKSPACE_ID=your_workspace_id
```

### Option C: Custom Source

Create `backend/sources/your_source.py`:

```python
from sources.base import DataSource

class YourSource(DataSource):
    @property
    def name(self) -> str:
        return "Your Source"
    
    async def fetch_errors(self, window_minutes=30, limit=100):
        # Fetch from your API and normalize to RawError format
        return [RawError(...) for error in your_api.get_errors()]
```

## Step 2: Connect Airweave for Context Search

This is where the magic happens - Airweave searches your GitHub code, Linear tickets, and Slack threads.

```bash
AIRWEAVE_API_KEY=your_key
AIRWEAVE_COLLECTION_ID=your_collection
AIRWEAVE_API_URL=https://api.airweave.ai  # or self-hosted
```

**Set up your Airweave collection:**
1. Create a collection at [airweave.ai](https://airweave.ai)
2. Connect your sources (GitHub, Linear, Slack)
3. Wait for initial sync to complete

Now when errors occur, the agent will find relevant context from your actual codebase and history.

## Step 3: Enable Real Integrations

### Linear (Ticket Creation)

```bash
LINEAR_ENABLED=true
LINEAR_API_KEY=lin_api_...
LINEAR_TEAM_ID=your_team_uuid
LINEAR_DEFAULT_LABEL_IDS=label1,label2  # Optional
```

### Slack (Alert Notifications)

```bash
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_CHANNEL_ID=C0123456789
```

## Step 4: Run in Production

### As a Scheduled Job (Recommended)

Run the pipeline on a schedule (e.g., every 5 minutes):

```python
# run_monitoring.py
import asyncio
from main import run_pipeline, PipelineConfig

async def main():
    config = PipelineConfig(use_sample_data=False)  # Use real data source
    # Runs the full pipeline: fetch → cluster → search → analyze → alert
    result = await run_pipeline(config)
    print(f"Pipeline completed: {result.status}")

if __name__ == "__main__":
    asyncio.run(main())
```

```bash
# Cron (every 5 minutes)
*/5 * * * * cd /path/to/backend && source venv/bin/activate && python run_monitoring.py

# Or use a scheduler like APScheduler, Celery, etc.
```

### As an API Service

Run the FastAPI server and trigger via API:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000

# Trigger pipeline
curl -X POST http://localhost:8000/api/run
```

---

# How It Works

## Multi-Stage Clustering

Errors are grouped by semantic similarity to reduce alert noise:

| Stage | Method | Example |
|-------|--------|---------|
| 1. Error Type | HTTP code, exception class | All 429 rate limit errors together |
| 2. Merge | Combine similar clusters | Auth errors from different services |
| 3. LLM (optional) | Semantic similarity | "Rate limit" + "Too many requests" |

## Smart Suppression

Not every error needs an alert:

| Status | Meaning | Action |
|--------|---------|--------|
| `NEW` | First occurrence | Create ticket + Alert |
| `REGRESSION` | Was fixed, came back | Reopen ticket + Alert |
| `ONGOING` | Known issue | Comment on ticket (suppressed) |

- ✅ `NEW` or `REGRESSION` → Always alert
- ✅ `S1`/`S2` severity → Always alert (override suppression)
- ❌ `ONGOING` with open ticket → Suppress (don't spam)
- ❌ Muted signatures → Suppress
- ❌ Alerted within 24h → Suppress

## Context Enrichment via Airweave

Each error cluster is enriched with relevant context from your connected sources:

```python
# The agent searches your Airweave collection for each error cluster
from airweave import AirweaveSDK

client = AirweaveSDK(api_key=AIRWEAVE_API_KEY)

# Search with optional source filtering
results = client.search.search(
    collection_id=COLLECTION_ID,
    query="timeout in sync_worker batch processing",
    source_name="github",  # Filter to specific source (github, linear, slack)
    limit=5
)
```

The agent automatically searches for:
- **GitHub**: Related code files and functions
- **Linear**: Existing tickets about similar issues  
- **Slack**: Past discussions and incident threads

This context informs severity analysis and helps engineers understand the issue immediately.

---

# Project Structure

```
├── backend/
│   ├── main.py              # FastAPI + WebSocket + Pipeline orchestration
│   ├── config.py            # Configuration management
│   ├── state.py             # JSON-based state storage (signatures, mutes)
│   ├── schemas.py           # Pydantic data models
│   ├── samples/             # Sample error data for demo
│   ├── sources/             # Data sources (sample, sentry, azure)
│   ├── clients/             # External APIs (airweave, linear, slack)
│   └── pipeline/
│       ├── clustering.py    # Error type clustering
│       ├── search.py        # Airweave context search
│       ├── analysis.py      # Severity + status determination
│       └── actions.py       # Linear/Slack integrations
├── frontend/                # React demo visualization (not needed for production)
│   ├── src/
│   │   ├── App.tsx          # Main app with WebSocket connection
│   │   └── components/      # Pipeline visualization components
├── docs/
│   ├── CONFIGURATION.md     # All configuration options
│   └── ARCHITECTURE.md      # Technical deep dive
└── .env.example             # All available environment variables
```

---

# API Reference

## REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config` | GET | Current configuration status |
| `/api/state` | GET | State storage statistics |
| `/api/samples` | GET | Sample error data |
| `/api/run` | POST | Trigger pipeline run |
| `/api/mute` | POST | Mute an error signature |
| `/api/mute/{sig}` | DELETE | Unmute a signature |

## WebSocket

Connect to `/ws` for real-time pipeline updates (used by the frontend demo):

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.send(JSON.stringify({ action: 'run_pipeline' }));
ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  // Events: step_started, step_data_ready, step_completed, pipeline_completed
};
```

---

# Configuration Reference

See [.env.example](.env.example) for all options. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATA_SOURCE` | Error source: `sample`, `sentry`, `azure` | `sample` |
| `AIRWEAVE_API_KEY` | Airweave API key for context search | - |
| `OPENAI_API_KEY` | OpenAI key for LLM clustering/analysis | - |
| `LINEAR_ENABLED` | Enable real Linear ticket creation | `false` |
| `SLACK_ENABLED` | Enable real Slack notifications | `false` |

---

# Learn More

- [How we use Airweave to improve Airweave](https://airweave.ai/blog/how-we-use-airweave-to-improve-airweave) - The story behind this project
- [Airweave Documentation](https://docs.airweave.ai)
- [Configuration Guide](docs/CONFIGURATION.md)
- [Architecture Deep Dive](docs/ARCHITECTURE.md)

## License

MIT License - use this as a starting point for your own error monitoring system.

---

Built with [Airweave](https://airweave.ai) - context retrieval for AI agents across apps & databases.
# DevANT-error-monitoring-system
# DevANT-error-monitoring-system
# DevANT-error-monitoring-system
