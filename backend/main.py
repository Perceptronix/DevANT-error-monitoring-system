"""
FastAPI backend for the Error Monitoring Agent demo.

This demo showcases how to build intelligent error monitoring with Airweave.
It features:
- Pluggable data sources (sample data by default, Sentry/Azure optional)
- LLM-powered semantic clustering
- Airweave context search for related code and tickets
- Smart suppression logic (NEW/REGRESSION/ONGOING)
- Optional GitHub Issues and Slack integrations with preview fallbacks
"""
import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import our modules
from config import get_config
from state import get_state_manager
from sources import get_data_source, get_available_sources
from samples import get_sample_errors
from pipeline import ErrorClusterer, ContextSearcher, ErrorAnalyzer, get_action_executor
from core.scoring import severity_priority
from repository.repo_analyzer import analyze_repository
from repository.analysis_state import (
    create_run,
    fail_run,
    get_run_snapshot,
    cancel_run,
    list_runs,
    transition_run,
    set_partial_update,
    finalize_run,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Removed old Pipeline Execution and ConnectionManager ---


def _generate_actionable_title(analysis: Dict[str, Any]) -> str:
    """Generate a human-readable, actionable title from analysis data."""
    # Use LLM-generated title if available (from analysis step)
    if analysis.get("title"):
        return analysis["title"]
    
    # Fallback: pattern matching for common error types
    signature = analysis.get("signature", "").lower()
    
    if "429" in signature or "rate limit" in signature:
        if "google" in signature or "drive" in signature:
            return "Google Drive API rate limits exceeded"
        elif "dropbox" in signature:
            return "Dropbox API rate limits exceeded"
        elif "slack" in signature:
            return "Slack API rate limits exceeded"
        return "External API rate limiting errors"
    
    if "database" in signature or "connection pool" in signature or "postgres" in signature or "sqlalchemy" in signature:
        if "pool" in signature or "exhaust" in signature:
            return "Database connection pool exhausted"
        if "timeout" in signature:
            return "Database connection timeouts"
        return "Database connectivity issues"
    
    if "401" in signature or "oauth" in signature or "token" in signature or "unauthorized" in signature:
        if "refresh" in signature or "expired" in signature or "revoked" in signature:
            return "OAuth tokens expired - users need to reconnect"
        return "Authentication failures with external service"
    
    if "pdf" in signature or "corrupt" in signature or "parse" in signature:
        return "Document processing failures"
    
    if "memory" in signature or "oom" in signature:
        return "Worker memory limit exceeded"
    
    if "timeout" in signature or "504" in signature:
        return "Request timeouts on external API calls"
    
    if "502" in signature or "503" in signature or "bad gateway" in signature:
        return "Upstream service unavailable"
    
    # Fallback: extract module/function info
    modules = analysis.get("modules", [])
    if modules:
        module = modules[0].replace("_", " ").replace(".", " ")
        return f"Errors in {module}"
    
    return "Production error requiring investigation"


def _generate_slack_preview(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Slack message preview."""
    severity_icon = {
        "S1": "🔴",
        "S2": "🟠", 
        "S3": "🟡",
        "S4": "🔵"
    }
    
    title = _generate_actionable_title(analysis)
    
    return {
        "blocks": [
            {
                "type": "header",
                "text": f"{severity_icon.get(analysis['severity'], '⚪')} {analysis['severity']}: {title}"
            },
            {
                "type": "section",
                "text": analysis.get("root_cause", "Error detected in production")
            },
            {
                "type": "context",
                "text": f"Affected: {', '.join(analysis.get('affected_orgs', ['Unknown']))}"
            }
        ]
    }


def _generate_github_issue_preview(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a GitHub issue preview."""
    title = _generate_actionable_title(analysis)
    
    return {
        "title": f"[{analysis['severity']}] {title}",
        "description": f"""## Summary
{analysis.get('root_cause', 'Error detected')}

## Impact
- Organizations affected: {len(analysis.get('affected_orgs', []))}
- Severity: {analysis['severity']}

## Suggested Action
{analysis.get('suggested_action', 'Investigate and resolve')}
""",
        "priority": severity_priority(analysis["severity"]),
        "labels": ["bug", "monitoring", analysis["severity"].lower()]
    }


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Error Monitoring Agent Demo...")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Error Monitoring Agent Demo",
    description="Intelligent error monitoring with LLM clustering and Airweave search",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Error Monitoring Agent Demo",
        "version": "1.0.0"
    }


@app.get("/api/config")
async def get_app_config():
    """
    Get current configuration status.
    
    Returns detailed information about:
    - Airweave configuration
    - LLM provider
    - Data source (sample, azure, sentry, etc.)
    - Integration status (GitHub Issues, Slack)
    - State storage stats
    """
    config = get_config()
    state = get_state_manager()
    
    # Get data source info
    data_source = get_data_source()
    available_sources = get_available_sources()
    
    # Mark active source
    for name, info in available_sources.items():
        info["active"] = (name == data_source.source_type)
    
    return {
        # Basic status (for backwards compatibility)
        "airweave_configured": config.airweave.is_configured,
        "openai_configured": bool(config.llm.openai_api_key),
        "anthropic_configured": bool(config.llm.anthropic_api_key),
        "llm_provider": config.llm.provider,
        
        # Detailed configuration
        "airweave": {
            "configured": config.airweave.is_configured,
            "collection_id": config.airweave.collection_id[:8] + "..." if config.airweave.collection_id else None,
        },
        "llm": {
            "configured": config.llm.is_configured,
            "provider": config.llm.provider,
            "model": config.llm.model,
        },
        "data_source": {
            "active": data_source.name,
            "type": data_source.source_type,
            "available": available_sources,
        },
        "integrations": {
            "github_issues": {
                "enabled": config.github.enabled,
                "configured": config.github.is_configured,
                "owner": config.github.owner,
                "repo": config.github.repo,
                "mode": "live" if config.github.is_configured else "preview",
            },
            "slack": {
                "enabled": config.slack.enabled,
                "configured": config.slack.is_configured,
                "mode": "live" if config.slack.is_configured else "preview",
            },
        },
        "state": state.get_stats(),
    }


@app.get("/api/samples")
async def get_samples():
    """Get sample error data."""
    return {
        "samples": get_sample_errors(include_extended=True),
        "count": len(get_sample_errors(include_extended=True))
    }


@app.get("/api/state")
async def get_state():
    """
    Get current state storage information.
    
    Returns statistics and recent signatures for debugging/admin.
    """
    state = get_state_manager()
    signatures = state.get_all_signatures()
    mutes = state.get_active_mutes()
    
    return {
        "stats": state.get_stats(),
        "recent_signatures": list(signatures.keys())[-10:],  # Last 10
        "active_mutes": list(mutes.keys()),
    }


class MuteRequest(BaseModel):
    """Request to mute an error signature."""
    signature: str
    duration_hours: int = 24
    reason: Optional[str] = None


@app.post("/api/mute")
async def mute_error(request: MuteRequest):
    """
    Mute an error signature for a specified duration.
    
    Muted errors will be suppressed and not trigger alerts.
    """
    state = get_state_manager()
    state.add_mute(
        signature=request.signature,
        duration_hours=request.duration_hours,
        reason=request.reason,
    )
    
    return {
        "status": "muted",
        "signature": request.signature,
        "duration_hours": request.duration_hours,
    }


@app.delete("/api/mute/{signature:path}")
async def unmute_error(signature: str):
    """Remove a mute for an error signature."""
    state = get_state_manager()
    state.remove_mute(signature)
    
    return {
        "status": "unmuted",
        "signature": signature,
    }





class RepoAnalyzeRequest(BaseModel):
    repo_url: str
    local_path: str | None = None
    include_live_errors: bool = True


@app.post("/api/analyze-repository")
async def analyze_repository_endpoint(req: RepoAnalyzeRequest):
    """Start async repository analysis via UnifiedOrchestrator. Returns run_id."""
    run_id = create_run(req.repo_url)
    logger.info(f"[{run_id}] Analysis created for: {req.repo_url}")

    async def _bg():
        try:
            logger.info(f"[{run_id}] BG TASK STARTED")
            loop = asyncio.get_event_loop()

            def _sync():
                logger.info(f"[{run_id}] Running UnifiedOrchestrator...")

                # Map orchestrator steps → canonical stage IDs for SSE / partial state
                step_to_stage = {
                    'started':              'repository_ingestion',
                    'ingesting_errors':     'repository_ingestion',
                    'github_enriched':      'repository_ingestion',
                    'github_sample':        'repository_ingestion',
                    'scanning_repository':  'repository_ingestion',
                    'scanned_files':        'repository_ingestion',
                    'repository_classified':'workflow_discovery',
                    'enriching_context':    'workflow_discovery',
                    'workflows_extracted':  'workflow_discovery',
                    'deployments_correlated':'deployment_analysis',
                    'observability_checked': 'observability_analysis',
                    'topology':             'topology_inference',
                    'assessing_health':     'topology_propagation',
                    'scored':               'operational_scoring',
                    'temporal_analyzed':    'regression_risk_analysis',
                    'live_errors_ingested': 'confidence_calibration',
                    'generating_brief':     'final_operational_synthesis',
                    'synthesis_complete':   'final_operational_synthesis',
                    'completed':            'final_operational_synthesis',
                    'error':                'final_operational_synthesis',
                }

                def progress_callback(step: str, payload: dict):
                    logger.info(f"[{run_id}] PROGRESS: step={step}")
                    stage_id = step_to_stage.get(step, step)

                    # State machine transitions
                    try:
                        if step == 'started':
                            transition_run(run_id, 'INITIALIZING', 'Started')
                        elif step in ('github_sample', 'scanned_files', 'ingesting_errors',
                                      'github_enriched', 'scanning_repository'):
                            transition_run(run_id, 'INGESTING', f'Progress in {stage_id}')
                        elif step in ('topology', 'assessing_health', 'enriching_context',
                                      'repository_classified'):
                            transition_run(run_id, 'ANALYZING', f'Progress in {stage_id}')
                        elif step in ('scored', 'temporal_analyzed', 'live_errors_ingested'):
                            transition_run(run_id, 'SCORING', f'Progress in {stage_id}')
                        elif step in ('generating_brief', 'synthesis_complete', 'completed'):
                            transition_run(run_id, 'FINALIZING', f'Completed {stage_id}')
                        elif step == 'error':
                            transition_run(run_id, 'FAILED', f'Error in {stage_id}')
                    except Exception as exc:
                        logger.error(f"[{run_id}] State transition error at {step}: {exc}")

                    # Store partial update for progressive SSE rendering
                    try:
                        set_partial_update(run_id, stage_id, {
                            'stage': stage_id,
                            'step': step,
                            'evidence': payload,
                        })
                    except Exception as exc:
                        logger.error(f"[{run_id}] Partial update error at {stage_id}: {exc}")

                try:
                    from pipeline.unified_orchestrator import UnifiedOrchestrator
                    orch = UnifiedOrchestrator()
                    result = orch.run(
                        repo_url=req.repo_url,
                        run_id=run_id,
                        progress_callback=progress_callback,
                        local_path=req.local_path,
                    )
                    logger.info(f"[{run_id}] Orchestrator completed successfully.")
                    finalize_run(run_id, result)
                    logger.info(f"[{run_id}] Run finalized.")
                except Exception as exc:
                    logger.exception(f"[{run_id}] Orchestrator exception: {exc}")
                    raise

            await loop.run_in_executor(None, _sync)
            logger.info(f"[{run_id}] BG TASK COMPLETED SUCCESSFULLY")
        except Exception as exc:
            logger.error(f"[{run_id}] BG TASK FAILED: {exc}", exc_info=True)
            fail_run(run_id, str(exc))

    asyncio.create_task(_bg())
    return {"run_id": run_id, "status": "started"}


@app.get("/api/analyze-repository/{run_id}")
async def get_analysis(run_id: str):
    return get_run_snapshot(run_id)


@app.get("/api/analyze-repository")
async def get_recent_analyses(limit: int = 20):
    return {"runs": list_runs(limit=limit)}


@app.post("/api/analyze-repository/{run_id}/cancel")
async def cancel_analysis(run_id: str):
    snap = get_run_snapshot(run_id)
    if snap.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="run_id not found")
    try:
        cancel_run(run_id, "user_request")
    except Exception:
        # terminal states return current snapshot
        pass
    return get_run_snapshot(run_id)


@app.get("/api/analyze-repository/{run_id}/stream")
async def stream_analysis(run_id: str):
    """SSE stream for analysis run snapshots. Emits only on state changes."""

    async def event_generator():
        last_sig = None
        while True:
            snap = get_run_snapshot(run_id)
            if snap.get("status") == "not_found":
                yield "event: error\ndata: {\"error\":\"not_found\"}\n\n"
                break

            # Create signature including partial values to detect any changes
            partial_sigs = {}
            for stage_id, partial_data in (snap.get("partial") or {}).items():
                if isinstance(partial_data, dict):
                    # Include evidence/progress values to detect updates
                    partial_sigs[stage_id] = json.dumps({
                        'state': partial_data.get('state'),
                        'progress_keys': sorted(list((partial_data.get('progress') or {}).keys())) if partial_data.get('progress') else [],
                        'evidence_keys': sorted(list((partial_data.get('evidence') or {}).keys())) if partial_data.get('evidence') else [],
                    }, sort_keys=True)
            
            sig = json.dumps({
                "state": snap.get("state"),
                "transitions": len(snap.get("transitions", [])),
                "partial_keys": sorted(list((snap.get("partial") or {}).keys())),
                "partial_sigs": partial_sigs,
                "result": bool(snap.get("result_snapshot")),
            }, sort_keys=True)

            if sig != last_sig:
                payload = json.dumps(snap)
                yield f"event: update\ndata: {payload}\n\n"
                last_sig = sig

            if snap.get("state") in ("COMPLETED", "FAILED", "CANCELLED"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
