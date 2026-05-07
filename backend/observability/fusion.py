from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from core.normalization import normalize_timestamp
from .traces import TraceIngestor, TraceSpan


class TemporalAlignmentEngine:
    """Align deployment, metric, trace, and outage timestamps into one causal order."""

    def __init__(self):
        self.trace_ingestor = TraceIngestor()

    def align(
        self,
        incident: Dict[str, Any],
        deployment_correlation: Optional[Dict[str, Any]] = None,
        metric_anomalies: Optional[Sequence[Dict[str, Any]]] = None,
        trace_spans: Optional[Sequence[TraceSpan | Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        deployment_correlation = deployment_correlation or {}
        metric_anomalies = list(metric_anomalies or [])
        trace_spans = list(trace_spans or [])

        trace_objects: List[TraceSpan] = []
        for span in trace_spans:
            if isinstance(span, TraceSpan):
                trace_objects.append(span)
            elif isinstance(span, dict):
                trace_objects.extend(self.trace_ingestor.ingest({"spans": [span]}))

        deployment_timestamp = self._deployment_timestamp(incident, deployment_correlation)
        metric_timestamp = self._first_timestamp(metric_anomalies, ["timestamp", "time"])
        trace_degradation = self.trace_ingestor.detect_degradation(trace_objects)
        trace_timestamp = normalize_timestamp(trace_degradation.get("timestamp")) if trace_degradation else self._first_trace_timestamp(trace_objects)
        outage_timestamp = normalize_timestamp(incident.get("outage_start") or incident.get("timestamp") or incident.get("occurred_at"))

        ordered_events = self._ordered_events(deployment_timestamp, metric_timestamp, trace_timestamp, outage_timestamp)
        propagation_chain = self._propagation_chain(incident, deployment_timestamp, metric_timestamp, trace_timestamp, outage_timestamp)
        alignment_score = self._alignment_score(ordered_events)

        return {
            "deployment_timestamp": deployment_timestamp.isoformat() if deployment_timestamp else None,
            "metric_spike_timestamp": metric_timestamp.isoformat() if metric_timestamp else None,
            "trace_degradation_timestamp": trace_timestamp.isoformat() if trace_timestamp else None,
            "outage_start_timestamp": outage_timestamp.isoformat() if outage_timestamp else None,
            "ordered_events": ordered_events,
            "propagation_chain": propagation_chain,
            "deployment_attribution": bool(deployment_correlation.get("matched")) or deployment_timestamp is not None,
            "alignment_score": alignment_score,
            "trace_degradation": trace_degradation,
            "metric_names": sorted({str(item.get("metric_name", "metric")) for item in metric_anomalies}),
        }

    def _deployment_timestamp(self, incident: Dict[str, Any], deployment_correlation: Dict[str, Any]) -> Optional[datetime]:
        if deployment_correlation.get("events"):
            first_event = deployment_correlation["events"][0]
            timestamp = first_event.get("time") or first_event.get("timestamp")
            parsed = normalize_timestamp(timestamp)
            if parsed is not None:
                return parsed
        return normalize_timestamp(incident.get("deployment_time") or incident.get("last_deploy_time"))

    def _first_timestamp(self, items: Sequence[Dict[str, Any]], keys: Sequence[str]) -> Optional[datetime]:
        for item in items:
            for key in keys:
                parsed = normalize_timestamp(item.get(key))
                if parsed is not None:
                    return parsed
        return None

    def _first_trace_timestamp(self, spans: Sequence[TraceSpan]) -> Optional[datetime]:
        if not spans:
            return None
        ordered = sorted(spans, key=lambda span: span.start_timestamp)
        return ordered[-1].start_timestamp if ordered else None

    def _ordered_events(
        self,
        deployment_timestamp: Optional[datetime],
        metric_timestamp: Optional[datetime],
        trace_timestamp: Optional[datetime],
        outage_timestamp: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for phase, timestamp in [
            ("deployment", deployment_timestamp),
            ("metric_spike", metric_timestamp),
            ("trace_degradation", trace_timestamp),
            ("outage_start", outage_timestamp),
        ]:
            if timestamp is not None:
                events.append({"phase": phase, "timestamp": timestamp.isoformat()})
        return sorted(events, key=lambda item: item["timestamp"])

    def _propagation_chain(
        self,
        incident: Dict[str, Any],
        deployment_timestamp: Optional[datetime],
        metric_timestamp: Optional[datetime],
        trace_timestamp: Optional[datetime],
        outage_timestamp: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        chain: List[Dict[str, Any]] = []
        if deployment_timestamp is not None:
            chain.append({
                "phase": "deployment",
                "description": f"Deployment {incident.get('deployment_id') or incident.get('commit_hash') or 'unknown'}",
                "timestamp": deployment_timestamp.isoformat(),
            })
        if metric_timestamp is not None:
            chain.append({
                "phase": "metric_spike",
                "description": "Observed latency/retry/saturation spike",
                "timestamp": metric_timestamp.isoformat(),
            })
        if trace_timestamp is not None:
            chain.append({
                "phase": "trace_degradation",
                "description": "Trace latency and timeout propagation",
                "timestamp": trace_timestamp.isoformat(),
            })
        if outage_timestamp is not None:
            chain.append({
                "phase": "outage_start",
                "description": "User-visible outage began",
                "timestamp": outage_timestamp.isoformat(),
            })
        return chain

    def _alignment_score(self, events: Sequence[Dict[str, Any]]) -> float:
        if not events:
            return 0.0
        return round(len(events) / 4.0, 2)