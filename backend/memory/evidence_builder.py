from typing import List, Dict, Any


class EvidenceBuilder:
    """Assemble retrieved pieces into a grounded evidence bundle."""

    def __init__(self):
        pass

    def build(
        self,
        evidences: List[Dict[str, Any]],
        correlation: Dict[str, Any],
        incident: Dict[str, Any],
        history: List[Dict[str, Any]] = None,
        deployments: List[Dict[str, Any]] = None,
        ownership: List[str] = None,
        rollback_candidates: List[Dict[str, Any]] = None,
        metrics_anomalies: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a structured evidence bundle for LLM reasoning.

        The returned dict aggregates:
        - evidences: list of evidence items with source and score
        - deployment events: recent deployments near incident
        - ownership: list of service owners
        - rollback_candidates: suggested rollbacks
        - metrics_anomalies: anomalies detected for the incident
        - deployment_correlation: correlation dict
        - incident: original incident summary
        - metadata: counts and confidence estimate
        """
        evidence_count = len(evidences)
        deployment_corr = bool(correlation.get("matched"))

        # Simple confidence heuristic: combine highest final_score and deployment match
        top_score = max((e.get("final_score", 0) for e in evidences), default=0)
        # Incorporate historical and ownership signals if present
        ownership_bonus = 0.1 if ownership else 0.0
        rollback_bonus = 0.05 if rollback_candidates else 0.0
        anomalies_bonus = 0.1 if metrics_anomalies else 0.0

        confidence = min(
            0.999,
            float(top_score * 0.6 + (0.25 if deployment_corr else 0.0) + ownership_bonus + rollback_bonus + anomalies_bonus),
        )

        bundle = {
            "evidences": evidences,
            "history": history or [],
            "deployment_events": deployments or [],
            "ownership": ownership or [],
            "rollback_candidates": rollback_candidates or [],
            "metrics_anomalies": metrics_anomalies or [],
            "deployment_correlation": correlation,
            "incident": incident,
            "metadata": {
                "confidence": confidence,
                "evidence_count": evidence_count,
                "deployment_correlated": deployment_corr,
            }
        }

        return bundle
