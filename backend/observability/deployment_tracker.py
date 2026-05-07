import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from .github_actions import GitHubActionsIngest


class DeploymentTracker:
    """Track and correlate deployments from multiple providers.

    Minimal implementation supporting GitHub Actions; placeholder hooks for
    Vercel, Railway, and Docker.
    """

    def __init__(self, github_token: Optional[str] = None):
        self.github = GitHubActionsIngest(token=github_token)

    async def fetch_recent_deployments(self, repo: str, limit: int = 50) -> List[Dict[str, Any]]:
        runs = await self.github.fetch_runs(repo, per_page=limit)
        # Normalize to deployment event format
        events = []
        for r in runs:
            events.append({
                "provider": "github_actions",
                "workflow": r.get("workflow"),
                "commit_sha": r.get("commit_sha"),
                "actor": r.get("actor"),
                "status": r.get("conclusion") or r.get("status"),
                "timestamp": r.get("updated_at") or r.get("created_at"),
                "url": r.get("html_url"),
            })
        return events

    async def correlate_with_incident(self, incident: Dict[str, Any], repo: str) -> Dict[str, Any]:
        # Fetch recent deployments and find ones within timeframe
        events = await self.fetch_recent_deployments(repo)
        t = incident.get("timestamp")
        matched = []
        for e in events:
            if e.get("commit_sha") and incident.get("commit_hash"):
                if e.get("commit_sha") == incident.get("commit_hash"):
                    matched.append(e)
        return {"matched": bool(matched), "events": matched}
