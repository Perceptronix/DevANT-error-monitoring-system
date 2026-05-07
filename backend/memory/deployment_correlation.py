import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any


class DeploymentCorrelator:
    """Correlate incidents with recent deployments, commits, and PR merges.

    This is a lightweight component that queries available metadata (via the
    provided incident payloads or external systems) and returns a correlation
    score. In production this should consult a CI/CD events datastore.
    """

    def __init__(self, window_minutes: int = 30):
        self.window = timedelta(minutes=window_minutes)

    async def correlate(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Return a correlation dict. Looks for recent deployment/commit timestamps
        in the incident metadata. The incident dict is expected to include
        optional `timestamp`, `deployment_time`, or `commit_time` fields.
        """
        # Best-effort parsing
        now = datetime.utcnow()
        ts = incident.get("timestamp") or incident.get("occurred_at")
        correlation = {"matched": False, "score": 0.0, "events": []}

        try:
            if ts:
                # Accept ISO strings
                t = datetime.fromisoformat(ts)
            else:
                t = now
        except Exception:
            t = now

        # If deployment_time present, compute delta
        dep_time = incident.get("deployment_time") or incident.get("last_deploy_time")
        if dep_time:
            try:
                d = datetime.fromisoformat(dep_time)
                delta = t - d
                if timedelta(0) <= delta <= self.window:
                    correlation["matched"] = True
                    correlation["score"] = max(correlation["score"], 1.0 - (delta / self.window))
                    correlation["events"].append({"type": "deployment", "time": dep_time})
            except Exception:
                pass

        # commit_time
        commit_time = incident.get("commit_time")
        if commit_time:
            try:
                c = datetime.fromisoformat(commit_time)
                delta = t - c
                if timedelta(0) <= delta <= self.window:
                    correlation["matched"] = True
                    correlation["score"] = max(correlation["score"], 0.8)
                    correlation["events"].append({"type": "commit", "time": commit_time, "hash": incident.get("commit_hash")})
            except Exception:
                pass

        # PR merges / config changes
        pr_time = incident.get("pr_merged_time")
        if pr_time:
            try:
                p = datetime.fromisoformat(pr_time)
                delta = t - p
                if timedelta(0) <= delta <= self.window:
                    correlation["matched"] = True
                    correlation["score"] = max(correlation["score"], 0.75)
                    correlation["events"].append({"type": "pr_merge", "time": pr_time})
            except Exception:
                pass

        # Async placeholder to simulate extra checks (e.g., CI/CD API)
        await asyncio.sleep(0)

        return correlation
