"""
Context Enrichment Engine — dynamically attach operational context to error clusters.

For each error cluster, searches and attaches:
- Related GitHub code and commits
- Related GitHub issues and discussions
- Pull requests that touched affected services
- Slack thread discussions
- Historical incident context
- Known mitigations and fixes

All lookups are async, non-blocking, and gracefully degrade when integrations
are unavailable.

Concurrency is limited with a semaphore to prevent:
- Connection pool exhaustion
- API rate limit violations
- Unbounded memory growth
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from connectors.github_connector import GitHubConnector
from connectors.slack_connector import SlackConnector

logger = logging.getLogger(__name__)

# Concurrency limit: max 10 parallel enrichment tasks per orchestrator instance
_ENRICHMENT_SEMAPHORE_LIMIT = 10


@dataclass
class ContextAttachment:
    """A single piece of enrichment context."""
    type: str  # "commit", "issue", "pr", "slack", "historical"
    source: str  # "github", "slack", "incident_graph"
    title: str
    url: Optional[str] = None
    timestamp: Optional[str] = None
    author: Optional[str] = None
    relevance_score: float = 0.0
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrichedCluster:
    """An error cluster augmented with context."""
    cluster_id: str
    root_cause: str
    affected_services: List[str]
    severity: str
    error_count: int
    confidence: float
    context_attachments: List[ContextAttachment] = field(default_factory=list)
    suggested_action: Optional[str] = None
    deployment_related: bool = False
    regression_probability: float = 0.0


class ContextEnricher:
    """
    Async context enrichment engine.
    
    Attaches operational context to error clusters by querying:
    - GitHub API (commits, issues, PRs)
    - Slack API (thread search, channel history)
    - Historical incident database
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        slack_token: Optional[str] = None,
        incident_graph: Optional[Dict[str, Any]] = None,
    ):
        self.github = GitHubConnector(token=github_token)
        self.slack = SlackConnector(token=slack_token)
        self.incident_graph = incident_graph or {}
        self._cache: Dict[str, List[ContextAttachment]] = {}
        # Limit concurrent enrichment tasks to prevent resource exhaustion
        self._semaphore = asyncio.Semaphore(_ENRICHMENT_SEMAPHORE_LIMIT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enrich_cluster(
        self,
        cluster: Dict[str, Any],
        repo_url: Optional[str] = None,
        services: Optional[List[str]] = None,
    ) -> EnrichedCluster:
        """
        Enrich a cluster with con with concurrency limit:
        1. GitHub commits
        2. GitHub issues
        3. GitHub PRs
        4. Slack discussions
        5. Historical incidents
        
        Uses semaphore to prevent unbounded concurrency.
        """
        enriched = EnrichedCluster(
            cluster_id=cluster.get("cluster_id", "unknown"),
            root_cause=cluster.get("root_cause", ""),
            affected_services=cluster.get("affected_services", []),
            severity=cluster.get("severity", "S4"),
            error_count=cluster.get("error_count", 0),
            confidence=cluster.get("confidence", 0.0),
            deployment_related=cluster.get("deployment_related", False),
            regression_probability=cluster.get("regression_probability", 0.0),
        )
        
        # Wrap all enrichment tasks with semaphore
        async def bounded_enrich(coro):
            async with self._semaphore:
                return await coro
        
        # Run all enrichment tasks in parallel with concurrency limit
        tasks = []
        
        if repo_url:
            tasks.append(
                bounded_enrich(
                    self._enrich_github_context(enriched, repo_url, services or [])
                )
            )
        
        if self.slack.is_configured:
            tasks.append(
                bounded_enrich(
                    self._enrich_slack_context(enriched, cluster.get("root_cause", ""))
                )
            )
        
        if self.incident_graph:
            tasks.append(
                bounded_enrich(
                    self._enrich_historical_context(enriched, cluster)
                
            tasks.append(
                self._enrich_historical_context(enriched, cluster)
            )
        
        if 
        Enrich multiple clusters in parallel.
        
        Uses semaphore internally to prevent unbounded concurrency.
        
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Suggest action based on context
        enriched.suggested_action = self._suggest_action(enriched)
        
        return enriched

    async def enrich_batch(
        self,
        clusters: List[Dict[str, Any]],
        repo_url: Optional[str] = None,
    ) -> List[EnrichedCluster]:
        """Enrich multiple clusters in parallel."""
        tasks = [
            self.enrich_cluster(c, repo_url=repo_url)
            for c in clusters
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        enriched = [r for r in results if isinstance(r, EnrichedCluster)]
        
        return enriched

    # ------------------------------------------------------------------
    # Enrichment strategies
    # ------------------------------------------------------------------

    async def _enrich_github_context(
        self,
        enriched: EnrichedCluster,
        repo_url: str,
        services: List[str],
    ):
        """Search GitHub for related commits, issues, and PRs."""
        if not self.github.is_configured:
            return
        
        try:
            # Parallel GitHub searches with timeouts
            commits_task = asyncio.wait_for(
                asyncio.to_thread(
                    self.github.get_recent_commits,
                    repo_url,
                    since_hours=24,
                    max_commits=10,
                ),
                timeout=10.0,  # ← TIMEOUT ADDED
            )
            
            issues_task = asyncio.wait_for(
                asyncio.to_thread(
                    self.github.search_related_issues,
                    repo_url,
                    enriched.root_cause,
                    max_issues=5,
                ),
                timeout=10.0,  # ← TIMEOUT ADDED
            )
            
            prs_task = asyncio.wait_for(
                asyncio.to_thread(
                    self.github.search_prs_by_service,
                    repo_url,
                    services,
                    since_hours=24,
                    max_prs=5,
                ),
                timeout=10.0,  # ← TIMEOUT ADDED
            )
            
            commits, issues, prs = await asyncio.gather(
                commits_task,
                issues_task,
                prs_task,
                return_exceptions=True,
            )
            
            # Attach commits
            if isinstance(commits, list):
                for commit in commits:
                    enriched.context_attachments.append(
                        ContextAttachment(
                            type="commit",
                            source="github",
                            title=commit.get("message", "Unnamed commit"),
                            url=commit.get("url", ""),
                            timestamp=commit.get("date", ""),
                            author=commit.get("author", ""),
                            relevance_score=0.6,
                            snippet=commit.get("sha", "")[:12],
                        )
                    )
            
            # Attach issues
            if isinstance(issues, list):
                for issue in issues:
                    enriched.context_attachments.append(
                        ContextAttachment(
                            type="issue",
                            source="github",
                            title=issue.get("title", "Unnamed issue"),
                            url=issue.get("url", ""),
                            timestamp=issue.get("updated_at", ""),
                            author=issue.get("author", ""),
                            relevance_score=0.7,
                            snippet=issue.get("body", "")[:200],
                        )
                    )
            
            # Attach PRs
            if isinstance(prs, list):
                for pr in prs:
                    enriched.context_attachments.append(
                        ContextAttachment(
                            type="pr",
                            source="github",
                            title=pr.get("title", "Unnamed PR"),
                            url=pr.get("url", ""),
                            timestamp=pr.get("created_at", ""),
                            author=pr.get("author", ""),
                            relevance_score=0.5,
                            snippet=pr.get("files_changed", 0),
                        )
                    )
        
        except Exception as e:
            logger.warning(f"GitHub enrichment failed: {e}")

    async def _enrich_slack_context(
        self,
        enriched: EnrichedCluster,
        query: str,
    ):
        """Search Slack for related discussions."""
        if not self.slack.is_configured:
            return
        
        try:
            # Search Slack with timeout
            messages = await asyncio.wait_for(
                asyncio.to_thread(
                    self.slack.search_messages,
                    query,
                    since_minutes=1440,
                    limit=5,
                ),
                timeout=8.0,  # ← TIMEOUT ADDED
            )
            
            for msg in messages or []:
                enriched.context_attachments.append(
                    ContextAttachment(
                        type="slack",
                        source="slack",
                        title=f"Discussion: {msg.get('text', '')[:100]}",
                        timestamp=msg.get("ts", ""),
                        author=msg.get("user", ""),
                        relevance_score=0.5,
                        snippet=msg.get("text", "")[:200],
                        metadata={
                            "channel": msg.get("channel"),
                            "thread_ts": msg.get("thread_ts"),
                        },
                    )
                )
        except asyncio.TimeoutError:
            logger.warning("Slack enrichment timed out")
        except Exception as e:
            logger.warning(f"Slack enrichment failed: {e}")

    async def _enrich_historical_context(
        self,
        enriched: EnrichedCluster,
        cluster: Dict[str, Any],
    ):
        """Attach historical incident context."""
        try:
            # Search incident graph for similar incidents
            signatures = cluster.get("error_signatures", [])
            
            # Find matching historical incidents
            for incident_id, incident in self.incident_graph.items():
                incident_sigs = set(incident.get("signatures", []))
                current_sigs = set(signatures)
                
                if incident_sigs & current_sigs:  # Signature overlap
                    enriched.context_attachments.append(
                        ContextAttachment(
                            type="historical",
                            source="incident_graph",
                            title=f"Historical: {incident.get('root_cause', 'Previous incident')}",
                            timestamp=incident.get("timestamp", ""),
                            author=incident.get("owner", ""),
                            relevance_score=0.8,
                            snippet=incident.get("resolution", "Unresolved"),
                            metadata={
                                "incident_id": incident_id,
                                "resolution": incident.get("resolution"),
                                "mttr_minutes": incident.get("mttr_minutes"),
                            },
                        )
                    )
        
        except Exception as e:
            logger.warning(f"Historical enrichment failed: {e}")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _suggest_action(self, enriched: EnrichedCluster) -> str:
        """Generate a suggested action based on enriched context."""
        # Look for prior resolutions in context
        historical_attachments = [
            a for a in enriched.context_attachments
            if a.type == "historical"
        ]
        
        if historical_attachments:
            resolution = historical_attachments[0].metadata.get("resolution")
            if resolution:
                return f"Apply prior fix: {resolution}"
        
        # Default suggestion based on severity
        if enriched.severity == "S1":
            return "Escalate immediately. Investigate root cause and rollback if needed."
        elif enriched.severity == "S2":
            return "Page on-call engineer. Begin incident investigation."
        elif enriched.severity == "S3":
            return "Create incident ticket. Schedule investigation."
        else:
            return "Monitor trend. Investigate if error count increases."
    
    def _cache_key(self, cluster_id: str) -> str:
        """Generate cache key for enrichment."""
        return f"enrichment:{cluster_id}:{datetime.now(timezone.utc).date()}"
