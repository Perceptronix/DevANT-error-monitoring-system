from typing import List, Dict, Any, Optional


class MetricsAdapter:
    """Adapter interface for metrics backends (Prometheus, Grafana, OTEL).

    Minimal methods for retrieving series and simple aggregations.
    """

    def __init__(self):
        pass

    async def query_series(self, query: str, start: str, end: str) -> List[Dict[str, Any]]:
        # Placeholder - implement per-backend adapters
        return []

    async def get_metric_value(self, metric: str, at_time: str) -> Optional[float]:
        return None
