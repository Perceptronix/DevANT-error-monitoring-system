from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class IncidentMemory:
    error_signature: str
    service: str
    stack_trace: str
    deployment_id: str
    commit_hash: str
    owner: str
    severity: str
    historical_matches: List[str]
    root_cause: str
    resolution: str
    timestamp: str


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
        # Very lightweight similarity: substring match on signatures or service
        sig = signature.lower()
        out = []
        for inc in self.incidents:
            if sig in inc.error_signature.lower() or sig in inc.service.lower():
                out.append(inc)
        return out


# Singleton
_graph: Optional[IncidentGraph] = None


def get_incident_graph() -> IncidentGraph:
    global _graph
    if _graph is None:
        _graph = IncidentGraph()
    return _graph
