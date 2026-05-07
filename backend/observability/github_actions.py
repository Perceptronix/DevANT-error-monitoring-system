import os
from typing import List, Dict, Any, Optional
import httpx


class GitHubActionsIngest:
    """Fetch GitHub Actions workflow runs for a repository."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.base = "https://api.github.com"

    async def fetch_runs(self, repo: str, per_page: int = 50) -> List[Dict[str, Any]]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        url = f"{self.base}/repos/{repo}/actions/runs?per_page={per_page}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            runs = data.get("workflow_runs", [])
            out = []
            for r in runs:
                out.append({
                    "workflow": r.get("name"),
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "conclusion": r.get("conclusion"),
                    "event": r.get("event"),
                    "actor": r.get("actor", {}).get("login"),
                    "commit_sha": r.get("head_sha"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                    "html_url": r.get("html_url"),
                })
            return out
