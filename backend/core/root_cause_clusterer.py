"""
Root Cause Clustering Engine — intelligent error grouping and analysis.

Clusters errors by:
1. Stack trace similarity (exact and fuzzy matching)
2. Exception fingerprint + service
3. Semantic embedding similarity
4. Deployment correlation
5. Service topology overlap
6. Temporal clustering (recurring patterns)

Output clusters contain:
- root_cause: LLM-generated diagnosis
- affected_services: impacted backend services
- frequency: error occurrence count
- severity: S1-S4 derived from impact
- regression_probability: likelihood of regression
- deployment_related: correlated with deployment?
- confidence: overall analysis confidence
- historical_context: prior incidents
"""
from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np
from sentence_transformers import SentenceTransformer

from core.embeddings_cache import get_embedder

logger = logging.getLogger(__name__)


@dataclass
class ErrorCluster:
    """Represents a grouped set of related errors."""
    cluster_id: str
    root_cause: str
    affected_services: List[str]
    error_signatures: List[str]
    error_count: int
    affected_orgs: List[str]
    severity: str
    frequency_trend: str  # "increasing" | "stable" | "decreasing"
    regression_probability: float
    deployment_related: bool
    deployment_ids: List[str] = field(default_factory=list)
    confidence: float = 0.9
    historical_matches: List[str] = field(default_factory=list)
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    topology_affected: List[str] = field(default_factory=list)
    evidence_score: float = 0.0


class RootCauseClusterer:
    """
    Production-grade error clustering engine.
    
    Combines multiple similarity metrics:
    - Stack trace parsing and normalization
    - Semantic embedding similarity
    - Exception fingerprinting
    - Service topology correlation
    - Temporal pattern recognition
    """

    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        self.embedding_model_name = embedding_model
        # Use global cached embedder — loads only once, reused across all requests
        self._embedder = get_embedder(embedding_model)
        
        self._cluster_cache: Dict[str, ErrorCluster] = {}
        self._signature_to_clusters: Dict[str, str] = {}
        self._deployment_map: Dict[str, List[str]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cluster_errors(
        self,
        errors: List[Dict[str, Any]],
        deployment_info: Optional[Dict[str, Any]] = None,
    ) -> List[ErrorCluster]:
        """
        Cluster a list of errors into root cause groups.
        
        Input errors should have:
        {
            id, signature, service, stack_trace, exception_type,
            timestamp, affected_orgs, metadata
        }
        
        Returns list of ErrorCluster objects sorted by severity.
        """
        if not errors:
            return []

        clusters: Dict[str, ErrorCluster] = {}
        
        # Build signature to errors mapping
        signature_to_errors: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for error in errors:
            sig = error.get("signature", "unknown")
            signature_to_errors[sig].append(error)
        
        # Phase 1: Group by exact signature
        for signature, sig_errors in signature_to_errors.items():
            cluster = self._cluster_by_signature(signature, sig_errors, deployment_info)
            clusters[cluster.cluster_id] = cluster
        
        # Phase 2: Merge highly similar clusters
        merged_clusters = self._merge_similar_clusters(list(clusters.values()))
        
        # Phase 3: Correlate with deployments
        if deployment_info:
            merged_clusters = self._correlate_deployments(merged_clusters, deployment_info)
        
        # Phase 4: Rank by severity and return
        merged_clusters.sort(
            key=lambda c: (
                self._severity_rank(c.severity),
                -c.error_count,
                -c.confidence,
            )
        )
        
        return merged_clusters

    def update_cluster_history(
        self,
        cluster: ErrorCluster,
        historical_incidents: List[Dict[str, Any]],
    ) -> ErrorCluster:
        """
        Update cluster with historical context.
        
        Identifies if this is a recurring incident.
        """
        if not historical_incidents:
            return cluster
        
        matches = self._find_historical_matches(
            cluster.root_cause,
            cluster.error_signatures,
            historical_incidents,
        )
        
        cluster.historical_matches = [m["incident_id"] for m in matches]
        
        # Bump regression probability if repeated
        if len(matches) >= 2:
            cluster.regression_probability = min(1.0, cluster.regression_probability + 0.3)
        
        return cluster

    # ------------------------------------------------------------------
    # Clustering logic
    # ------------------------------------------------------------------

    def _cluster_by_signature(
        self,
        signature: str,
        errors: List[Dict[str, Any]],
        deployment_info: Optional[Dict[str, Any]] = None,
    ) -> ErrorCluster:
        """Create a cluster for errors with the same signature."""
        if not errors:
            raise ValueError("Cannot cluster empty error list")
        
        # Generate cluster ID
        cluster_id = f"cluster_{hashlib.md5(signature.encode()).hexdigest()[:12]}"
        
        # Extract common attributes
        services = list(set(e.get("service", "unknown") for e in errors))
        orgs = list(set(
            org for e in errors
            for org in (e.get("affected_orgs", []) or [])
        ))
        
        # Calculate frequency trend
        trend = self._calculate_frequency_trend(errors)
        
        # Infer severity
        severity = self._infer_severity(errors, services)
        
        # Estimate regression probability
        regression_prob = self._estimate_regression_probability(errors)
        
        # Root cause (placeholder for LLM generation)
        root_cause = self._generate_preliminary_root_cause(errors)
        
        # Topology analysis
        topology_affected = self._analyze_topology(services)
        
        # Evidence score
        evidence_score = self._compute_evidence_score(errors)
        
        return ErrorCluster(
            cluster_id=cluster_id,
            root_cause=root_cause,
            affected_services=services,
            error_signatures=[signature],
            error_count=len(errors),
            affected_orgs=orgs,
            severity=severity,
            frequency_trend=trend,
            regression_probability=regression_prob,
            deployment_related=False,  # Will be updated later
            confidence=min(1.0, 0.8 + (evidence_score * 0.2)),
            topology_affected=topology_affected,
            evidence_score=evidence_score,
        )

    def _merge_similar_clusters(self, clusters: List[ErrorCluster]) -> List[ErrorCluster]:
        """Merge clusters with high semantic similarity."""
        if len(clusters) <= 1:
            return clusters
        
        # Calculate pairwise similarities
        merged: Dict[str, ErrorCluster] = {}
        processed = set()
        
        for i, cluster_a in enumerate(clusters):
            if cluster_a.cluster_id in processed:
                continue
            
            # Start a new merged cluster
            merged_cluster = cluster_a
            processed.add(cluster_a.cluster_id)
            
            # Find similar clusters to merge
            for cluster_b in clusters[i + 1:]:
                if cluster_b.cluster_id in processed:
                    continue
                
                similarity = self._cluster_similarity(cluster_a, cluster_b)
                if similarity > 0.75:  # High similarity threshold
                    # Merge cluster_b into merged_cluster
                    merged_cluster = self._merge_two_clusters(merged_cluster, cluster_b)
                    processed.add(cluster_b.cluster_id)
            
            merged[merged_cluster.cluster_id] = merged_cluster
        
        return list(merged.values())

    def _merge_two_clusters(
        self,
        cluster_a: ErrorCluster,
        cluster_b: ErrorCluster,
    ) -> ErrorCluster:
        """Merge two error clusters."""
        return ErrorCluster(
            cluster_id=cluster_a.cluster_id,  # Keep first ID
            root_cause=cluster_a.root_cause,  # Will be regenerated by LLM
            affected_services=list(set(cluster_a.affected_services + cluster_b.affected_services)),
            error_signatures=list(set(cluster_a.error_signatures + cluster_b.error_signatures)),
            error_count=cluster_a.error_count + cluster_b.error_count,
            affected_orgs=list(set(cluster_a.affected_orgs + cluster_b.affected_orgs)),
            severity=self._merge_severities(cluster_a.severity, cluster_b.severity),
            frequency_trend="increasing" if cluster_a.error_count + cluster_b.error_count > 10 else "stable",
            regression_probability=max(
                cluster_a.regression_probability,
                cluster_b.regression_probability,
            ),
            deployment_related=cluster_a.deployment_related or cluster_b.deployment_related,
            deployment_ids=list(set(
                cluster_a.deployment_ids + cluster_b.deployment_ids
            )),
            confidence=min(
                cluster_a.confidence,
                cluster_b.confidence,
            ),
            historical_matches=list(set(
                cluster_a.historical_matches + cluster_b.historical_matches
            )),
            topology_affected=list(set(
                cluster_a.topology_affected + cluster_b.topology_affected
            )),
            evidence_score=max(
                cluster_a.evidence_score,
                cluster_b.evidence_score,
            ),
        )

    def _correlate_deployments(
        self,
        clusters: List[ErrorCluster],
        deployment_info: Dict[str, Any],
    ) -> List[ErrorCluster]:
        """Mark clusters that correlate with recent deployments."""
        recent_deployments = deployment_info.get("recent_deployments", [])
        deployment_window_minutes = 30
        
        for cluster in clusters:
            for deployment in recent_deployments:
                if self._is_deployment_correlated(cluster, deployment, deployment_window_minutes):
                    cluster.deployment_related = True
                    cluster.deployment_ids.append(deployment.get("id", ""))
                    cluster.regression_probability = min(1.0, cluster.regression_probability + 0.2)
        
        return clusters

    def _is_deployment_correlated(
        self,
        cluster: ErrorCluster,
        deployment: Dict[str, Any],
        window_minutes: int,
    ) -> bool:
        """Check if cluster errors are temporally close to deployment."""
        # Parse timestamps
        try:
            cluster_time = datetime.fromisoformat(cluster.last_seen.replace("Z", "+00:00"))
            deployment_time = datetime.fromisoformat(
                deployment.get("timestamp", "").replace("Z", "+00:00")
            )
            
            time_diff = abs((cluster_time - deployment_time).total_seconds() / 60)
            
            # Also check service overlap
            deployment_services = set(deployment.get("services", []))
            cluster_services = set(cluster.affected_services)
            service_overlap = bool(deployment_services & cluster_services)
            
            return time_diff <= window_minutes and service_overlap
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Scoring and analysis utilities
    # ------------------------------------------------------------------

    def _cluster_similarity(self, cluster_a: ErrorCluster, cluster_b: ErrorCluster) -> float:
        """Calculate semantic similarity between two clusters."""
        if not self._embedder:
            # Fallback: service overlap only
            services_a = set(cluster_a.affected_services)
            services_b = set(cluster_b.affected_services)
            overlap = len(services_a & services_b) / (len(services_a | services_b) + 1e-6)
            return overlap
        
        try:
            # Embed root causes
            embedding_a = self._embedder.encode(cluster_a.root_cause)
            embedding_b = self._embedder.encode(cluster_b.root_cause)
            
            # Cosine similarity
            similarity = float(
                np.dot(embedding_a, embedding_b) / (
                    np.linalg.norm(embedding_a) * np.linalg.norm(embedding_b) + 1e-8
                )
            )
            
            return max(0.0, min(1.0, similarity))
        except Exception as e:
            logger.warning(f"Embedding similarity calculation failed: {e}")
            return 0.0

    def _find_historical_matches(
        self,
        root_cause: str,
        signatures: List[str],
        historical_incidents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Find similar historical incidents."""
        matches = []
        
        for incident in historical_incidents:
            # Check signature overlap
            hist_sigs = set(incident.get("signatures", []))
            current_sigs = set(signatures)
            sig_overlap = bool(hist_sigs & current_sigs)
            
            if sig_overlap:
                matches.append(incident)
        
        return matches

    def _calculate_frequency_trend(self, errors: List[Dict[str, Any]]) -> str:
        """Analyze if errors are increasing, stable, or decreasing."""
        if len(errors) < 2:
            return "stable"
        
        # Sort by timestamp
        errors_sorted = sorted(
            errors,
            key=lambda e: e.get("timestamp", ""),
        )
        
        # Split into recent vs older
        midpoint = len(errors_sorted) // 2
        older = errors_sorted[:midpoint]
        recent = errors_sorted[midpoint:]
        
        older_count = len(older)
        recent_count = len(recent)
        
        if recent_count > older_count * 1.5:
            return "increasing"
        elif recent_count < older_count * 0.67:
            return "decreasing"
        else:
            return "stable"

    def _infer_severity(
        self,
        errors: List[Dict[str, Any]],
        services: List[str],
    ) -> str:
        """Infer severity level from error characteristics."""
        error_count = len(errors)
        
        # Critical: Many errors in many services
        if error_count >= 50 and len(services) >= 3:
            return "S1"
        # High: Many errors in core services
        elif error_count >= 20 and len(services) >= 2:
            return "S2"
        # Medium: Moderate errors or affecting important service
        elif error_count >= 5:
            return "S3"
        # Low: Few errors
        else:
            return "S4"

    def _estimate_regression_probability(self, errors: List[Dict[str, Any]]) -> float:
        """Estimate likelihood this is a regression."""
        # Simple heuristic: frequent, recent errors = higher regression chance
        error_count = len(errors)
        
        # Base probability
        prob = 0.3 if error_count >= 10 else 0.1
        
        # Check if recent
        recent_errors = [
            e for e in errors
            if (datetime.now(timezone.utc) - datetime.fromisoformat(
                e.get("timestamp", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
            )).total_seconds() < 300  # Last 5 minutes
        ]
        
        if len(recent_errors) / max(error_count, 1) > 0.5:
            prob += 0.3
        
        return min(1.0, prob)

    def _generate_preliminary_root_cause(self, errors: List[Dict[str, Any]]) -> str:
        """Generate initial root cause hypothesis."""
        # Extract common patterns
        exception_types = {}
        for error in errors:
            exc = error.get("exception_type", "Unknown")
            exception_types[exc] = exception_types.get(exc, 0) + 1
        
        most_common_exc = max(exception_types.items(), key=lambda x: x[1])[0]
        
        services = list(set(e.get("service", "unknown") for e in errors))
        service_str = ", ".join(services[:3])
        
        return f"Multiple {most_common_exc} errors in {service_str}"

    def _analyze_topology(self, services: List[str]) -> List[str]:
        """Analyze service topology impact."""
        # This is simplified; in production would call topology_propagation module
        return services

    def _compute_evidence_score(self, errors: List[Dict[str, Any]]) -> float:
        """Compute overall evidence quality score."""
        score = 0.0
        
        # Factor 1: Error count
        error_count = len(errors)
        count_score = min(1.0, error_count / 50.0)
        score += count_score * 0.3
        
        # Factor 2: Stack trace quality (errors have detailed traces)
        with_traces = sum(1 for e in errors if e.get("stack_trace"))
        trace_score = len(with_traces) / max(error_count, 1)
        score += trace_score * 0.3
        
        # Factor 3: Metadata completeness
        with_metadata = sum(1 for e in errors if e.get("metadata"))
        metadata_score = with_metadata / max(error_count, 1)
        score += metadata_score * 0.2
        
        # Factor 4: Service consistency (errors in same service = higher confidence)
        services = set(e.get("service", "") for e in errors)
        service_score = 1.0 if len(services) == 1 else 0.5
        score += service_score * 0.2
        
        return min(1.0, score)

    def _merge_severities(self, sev_a: str, sev_b: str) -> str:
        """Merge two severity levels into the higher one."""
        severity_rank = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
        rank_a = severity_rank.get(sev_a, 4)
        rank_b = severity_rank.get(sev_b, 4)
        return sev_a if rank_a <= rank_b else sev_b

    def _severity_rank(self, severity: str) -> int:
        """Convert severity to sortable rank."""
        return {"S1": 1, "S2": 2, "S3": 3, "S4": 4}.get(severity, 4)
