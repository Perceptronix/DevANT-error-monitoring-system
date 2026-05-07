from typing import List, Dict, Any


class AnomalyDetector:
    """Detect metric anomalies and correlate with deployments.

    Simple heuristics-based detector: spike detection and baseline deviation.
    """

    def __init__(self):
        pass

    def detect_spikes(self, series: List[Dict[str, Any]], factor: float = 3.0) -> List[Dict[str, Any]]:
        """Return list of detected spike events given a metric time series.

        series: list of {"time": ..., "value": ...}
        """
        if not series:
            return []
        values = [s.get("value", 0) for s in series]
        avg = sum(values) / len(values)
        spikes = []
        for s in series:
            if s.get("value", 0) > avg * factor:
                spikes.append({"time": s.get("time"), "value": s.get("value")})
        return spikes
