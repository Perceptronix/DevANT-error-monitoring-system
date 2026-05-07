"""
FastAPI backend for the Error Monitoring Agent demo.

This demo showcases how to build intelligent error monitoring with Airweave.
It features:
- Pluggable data sources (sample data by default, Sentry/Azure optional)
- LLM-powered semantic clustering
- Airweave context search for related code and tickets
- Smart suppression logic (NEW/REGRESSION/ONGOING)
- Optional Linear and Slack integrations with preview fallbacks
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables first
load_dotenv()

# Import our modules
from config import get_config
from state import get_state_manager
from sources import get_data_source, get_available_sources
from samples import get_sample_errors
from pipeline import ErrorClusterer, ContextSearcher, ErrorAnalyzer, get_action_executor
from core.scoring import severity_priority

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Pydantic Models ---

class PipelineConfig(BaseModel):
    """Configuration for running the pipeline."""
    use_sample_data: bool = True
    custom_errors: Optional[List[Dict[str, Any]]] = None
    include_extended_samples: bool = False


class PipelineStep(BaseModel):
    """Represents a single step in the pipeline."""
    id: str
    name: str
    status: str  # "pending", "running", "completed", "error"
    data: Optional[Dict[str, Any]] = None
    reasoning: Optional[str] = None
    duration_ms: Optional[int] = None


class PipelineState(BaseModel):
    """Current state of the pipeline."""
    run_id: str
    status: str  # "idle", "running", "completed", "error"
    current_step: int
    steps: List[PipelineStep]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# --- WebSocket Connection Manager ---

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message: {e}")


manager = ConnectionManager()


# --- Pipeline Execution ---

async def run_pipeline(config: PipelineConfig) -> PipelineState:
    """
    Run the error monitoring pipeline with real-time updates.
    """
    run_id = f"run-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    
    # Initialize pipeline state
    steps = [
        PipelineStep(id="raw-errors", name="Raw Errors", status="pending"),
        PipelineStep(id="clustering", name="Semantic Clustering", status="pending"),
        PipelineStep(id="context-search", name="Context Search", status="pending"),
        PipelineStep(id="analysis", name="Severity Analysis", status="pending"),
        PipelineStep(id="alert-preview", name="Alert Preview", status="pending"),
    ]
    
    state = PipelineState(
        run_id=run_id,
        status="running",
        current_step=0,
        steps=steps,
        started_at=datetime.utcnow().isoformat()
    )
    
    # Broadcast initial state
    await manager.broadcast({"type": "pipeline_started", "state": state.model_dump()})
    
    try:
        # Initialize pipeline components
        clusterer = ErrorClusterer()
        searcher = ContextSearcher()
        analyzer = ErrorAnalyzer()
        
        # Step 1: Raw Errors
        state.current_step = 0
        state.steps[0].status = "running"
        await manager.broadcast({"type": "step_started", "step_id": "raw-errors", "state": state.model_dump()})
        
        start_time = datetime.utcnow()
        
        if config.use_sample_data:
            errors = get_sample_errors(include_extended=config.include_extended_samples)
        else:
            errors = config.custom_errors or []
        
        # Set data while still running so UI can show it expanding
        state.steps[0].data = {
            "error_count": len(errors),
            "errors": errors,
            "orgs_affected": list(set(e.get("org_name", "Unknown") for e in errors))
        }
        await manager.broadcast({"type": "step_data_ready", "step_id": "raw-errors", "state": state.model_dump()})
        await asyncio.sleep(1.5)  # Pause so users can see the data
        
        state.steps[0].status = "completed"
        state.steps[0].duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        
        await manager.broadcast({"type": "step_completed", "step_id": "raw-errors", "state": state.model_dump()})
        await asyncio.sleep(0.3)  # Brief pause before next step
        
        # Step 2: Semantic Clustering
        state.current_step = 1
        state.steps[1].status = "running"
        await manager.broadcast({"type": "step_started", "step_id": "clustering", "state": state.model_dump()})
        
        start_time = datetime.utcnow()
        clusters = await clusterer.cluster_errors(errors)
        
        # Set data while still running so UI can show it expanding
        state.steps[1].data = {
            "cluster_count": len(clusters),
            "clusters": clusters,
            "reduction": f"{len(errors)} errors → {len(clusters)} clusters"
        }
        state.steps[1].reasoning = clusterer.last_reasoning
        await manager.broadcast({"type": "step_data_ready", "step_id": "clustering", "state": state.model_dump()})
        await asyncio.sleep(1.5)  # Pause so users can see the data
        
        state.steps[1].status = "completed"
        state.steps[1].duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        
        await manager.broadcast({"type": "step_completed", "step_id": "clustering", "state": state.model_dump()})
        await asyncio.sleep(0.3)
        
        # Step 3: Context Search (Airweave)
        state.current_step = 2
        state.steps[2].status = "running"
        await manager.broadcast({"type": "step_started", "step_id": "context-search", "state": state.model_dump()})
        
        start_time = datetime.utcnow()
        context_results = await searcher.search_context(clusters)
        
        # Set data while still running so UI can show it expanding
        state.steps[2].data = {
            "results": context_results,
            "sources_searched": ["GitHub", "Linear", "Slack"]
        }
        await manager.broadcast({"type": "step_data_ready", "step_id": "context-search", "state": state.model_dump()})
        await asyncio.sleep(1.5)  # Pause so users can see the data
        
        state.steps[2].status = "completed"
        state.steps[2].duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        
        await manager.broadcast({"type": "step_completed", "step_id": "context-search", "state": state.model_dump()})
        await asyncio.sleep(0.3)
        
        # Step 4: Severity Analysis
        state.current_step = 3
        state.steps[3].status = "running"
        await manager.broadcast({"type": "step_started", "step_id": "analysis", "state": state.model_dump()})
        
        start_time = datetime.utcnow()
        analysis_results = await analyzer.analyze_errors(clusters, context_results)
        
        # Set data while still running so UI can show it expanding
        state.steps[3].data = {
            "analyses": analysis_results
        }
        state.steps[3].reasoning = analyzer.last_reasoning
        await manager.broadcast({"type": "step_data_ready", "step_id": "analysis", "state": state.model_dump()})
        await asyncio.sleep(1.5)  # Pause so users can see the data
        
        state.steps[3].status = "completed"
        state.steps[3].duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        
        await manager.broadcast({"type": "step_completed", "step_id": "analysis", "state": state.model_dump()})
        await asyncio.sleep(0.3)
        
        # Step 5: Alert Preview
        state.current_step = 4
        state.steps[4].status = "running"
        await manager.broadcast({"type": "step_started", "step_id": "alert-preview", "state": state.model_dump()})
        
        start_time = datetime.utcnow()
        
        # Generate alert previews
        alerts = []
        for analysis in analysis_results:
            actionable_title = _generate_actionable_title(analysis)
            alert = {
                "signature": analysis["signature"],
                "severity": analysis["severity"],
                "title": actionable_title,
                "description": analysis.get("root_cause", ""),
                "affected_orgs": analysis.get("affected_orgs", []),
                "slack_preview": _generate_slack_preview(analysis),
                "linear_preview": _generate_linear_preview(analysis),
            }
            alerts.append(alert)
        
        # Set data while still running so UI can show it expanding
        state.steps[4].data = {
            "alerts": alerts,
            "total_alerts": len(alerts)
        }
        await manager.broadcast({"type": "step_data_ready", "step_id": "alert-preview", "state": state.model_dump()})
        await asyncio.sleep(0.5)  # Brief pause before completing (this stays open)
        
        state.steps[4].status = "completed"
        state.steps[4].duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        
        await manager.broadcast({"type": "step_completed", "step_id": "alert-preview", "state": state.model_dump()})
        
        # Pipeline complete
        state.status = "completed"
        state.completed_at = datetime.utcnow().isoformat()
        await manager.broadcast({"type": "pipeline_completed", "state": state.model_dump()})
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        state.status = "error"
        if state.current_step < len(state.steps):
            state.steps[state.current_step].status = "error"
        await manager.broadcast({"type": "pipeline_error", "error": str(e), "state": state.model_dump()})
    
    return state


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


def _generate_linear_preview(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Linear ticket preview."""
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
    - Integration status (Linear, Slack)
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
            "linear": {
                "enabled": config.linear.enabled,
                "configured": config.linear.is_configured,
                "mode": "live" if config.linear.is_configured else "preview",
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


@app.post("/api/run")
async def run_demo(config: PipelineConfig):
    """
    Start a pipeline run.
    The actual execution happens via WebSocket for real-time updates.
    """
    # Run pipeline in background task
    asyncio.create_task(run_pipeline(config))
    return {"status": "started", "message": "Pipeline started. Connect to WebSocket for updates."}


@app.websocket("/ws/pipeline")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time pipeline updates.
    
    Messages sent:
    - pipeline_started: Pipeline execution has begun
    - step_started: A step has started processing
    - step_completed: A step has finished
    - pipeline_completed: All steps finished successfully
    - pipeline_error: An error occurred
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "run":
                # Client requested to run the pipeline
                config = PipelineConfig(**message.get("config", {}))
                asyncio.create_task(run_pipeline(config))
            elif message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
