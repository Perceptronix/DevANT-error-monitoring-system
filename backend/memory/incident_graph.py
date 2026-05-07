from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from core.identity import same_incident


@dataclass
class IncidentMemory:
    incident_id: str
    error_signature: str
    service: str
    stack_trace: str
    deployment_id: Optional[str] = None
    commit_hash: Optional[str] = None
    owner: Optional[str] = None
    severity: str = "unknown"
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "open"
    historical_matches: List[str] = field(default_factory=list)


class IncidentGraph:
    """In-memory regression and incident timeline store.

    This is a small, index-like structure used to store resolved incidents
    and query for historical matches. It is intentionally lightweight and
    designed to be replaced by a durable store if needed.
    """

    def __init__(self):
        self.incidents: List[IncidentMemory] = []

    def add_resolved(self, incident: IncidentMemory):
        self.incidents.append(incident)

    def find_similar(self, signature: str, threshold: float = 0.6) -> List[IncidentMemory]:
        # Normalize identity matching through the shared core helper
        query = {"signature": signature}
        out = []
        for inc in self.incidents:
            if same_incident(query, {"signature": inc.error_signature, "service": inc.service}):
                out.append(inc)
        return out


# Singleton
_graph: Optional[IncidentGraph] = None


def get_incident_graph() -> IncidentGraph:
    global _graph
    if _graph is None:
        _graph = IncidentGraph()
    return _graph
