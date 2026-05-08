"""
Lightweight repository analyzer focused on operational metadata extraction.
- Designed for local-path scans (fast filesystem checks)
- For remote GitHub URLs, returns pending requiring local path or allowlist for clone
- Emits progress via progress_callback(step_name, partial_result)
"""
from typing import Callable, Dict, Any, List, Optional
import os
import json
from pathlib import Path
import logging
from .topology_extractor import TopologyExtractor
from .operational_scoring import OperationalScoringEngine
from .github_ingestor import GitHubIngestor
from .evidence_engine import EvidenceEngine
from .analysis_state import transition_run, finalize_run, fail_run, get_run_snapshot, set_partial_update

logger = logging.getLogger(__name__)


def _read_file_safe(path: Path, max_bytes: int = 16_384) -> str:
    try:
        with path.open('rb') as f:
            data = f.read(max_bytes)
            return data.decode(errors='replace')
    except Exception:
        return ''


def analyze_repository(repo_url: str, local_path: Optional[str] = None, progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Analyze repository for operational metadata.

    Args:
        repo_url: user-provided repo URL (https or local path)
        local_path: optional explicit local path to analyze (preferred)
        progress_callback: optional callback(step_name, partial_result) used to stream progress

    Returns:
        result dict with evidence and flags
    """
    result: Dict[str, Any] = {
        'repo_url': repo_url,
        'scanned': False,
        'error': None,
        'evidence': {},
        'topology': {},
        'scores': {},
    }

    def progress(step: str, payload: Dict[str, Any]):
        # cancellation safety: no processing after cancel
        if run_id:
            snap = get_run_snapshot(run_id)
            if snap.get('state') == 'CANCELLED':
                raise RuntimeError('cancelled')

        if progress_callback:
            try:
                progress_callback(step, payload)
            except Exception:
                logger.exception('progress callback failed')
        if run_id:
            try:
                set_partial_update(run_id, step, payload)
            except Exception:
                pass
        # also update run state transitions for deterministic lifecycle
        if run_id:
            try:
                if step == 'started':
                    transition_run(run_id, 'INITIALIZING')
                elif step == 'github_sample' or step == 'scanned_files':
                    transition_run(run_id, 'INGESTING')
                elif step == 'topology':
                    transition_run(run_id, 'ANALYZING')
                elif step == 'scored':
                    transition_run(run_id, 'SCORING')
                elif step == 'completed':
                    transition_run(run_id, 'FINALIZING')
            except Exception:
                # avoid raising from progress reporting
                pass

    # Determine local path to scan
    path = None
    if local_path:
        path = Path(local_path)
    else:
        # If repo_url looks like local path
        if repo_url.startswith('file://'):
            path = Path(repo_url[len('file://'):])
        elif os.path.exists(repo_url):
            path = Path(repo_url)

    # If remote GitHub URL, perform metadata-first ingestion via API
    if path is None and repo_url.startswith('https://github.com'):
        # Use GitHubIngestor to sample operational files
        gh = GitHubIngestor()
        try:
            progress('started', {'status': 'github_ingest_started'})
            sample = gh.sample_operational_files(repo_url, max_paths=200)
            evidence = {
                'files_present': [],
                'workflows': [],
                'dockerfiles': [],
                'kubernetes_manifests': [],
                'helm_charts': [],
                'terraform': [],
                'prometheus': False,
                'otel': False,
                'package_managers': [],
                'services': [],
            }
            evidence.update(sample)
            progress('github_sample', {'sample_counts': {k: (len(v) if isinstance(v, list) else int(bool(v))) for k, v in sample.items()}})
            # Build topology from sampled manifests minimal
            topology = TopologyExtractor().extract_from_local_path(path) if path else {'services': [], 'edges': []}
            # Evidence engine deeper evaluation
            ee = EvidenceEngine()
            _ = ee.evaluate(evidence, topology)
            scoring_engine = OperationalScoringEngine()
            scores = scoring_engine.score_from_evidence(evidence, topology)
            progress('scored', {'scores': scores})
            result.update({'scanned': True, 'evidence': evidence, 'topology': topology, 'scores': scores})
            progress('completed', {'result_summary': {'services': len(evidence.get('services', [])), 'scores': scores}})
            # finalize run deterministically
            try:
                if run_id:
                    finalize_run(run_id, result)
            except Exception:
                pass
            # return immutable snapshot
            return json.loads(json.dumps(result))
        except Exception as e:
            if str(e) == 'cancelled':
                result['error'] = 'cancelled'
                return json.loads(json.dumps(result))
            result['error'] = f'github_ingest_failed: {e}'
            progress('error', {'error': result['error']})
            return result

    if path is None:
        # Remote repository: do not clone by default
        result['error'] = 'remote_repo_requires_clone_or_local_path'
        progress('started', {'status': 'remote_pending', 'message': 'remote repo requires local path or clone permission'})
        try:
            if run_id:
                fail_run(run_id, result['error'])
        except Exception:
            pass
        return json.loads(json.dumps(result))

    if not path.exists():
        result['error'] = 'path_not_found'
        progress('error', {'status': 'path_not_found', 'path': str(path)})
        try:
            if run_id:
                fail_run(run_id, result['error'])
        except Exception:
            pass
        return json.loads(json.dumps(result))

    # Start scanning
    progress('started', {'status': 'scanning_local_path', 'path': str(path)})
    evidence: Dict[str, Any] = {
        'files_present': [],
        'workflows': [],
        'dockerfiles': [],
        'kubernetes_manifests': [],
        'helm_charts': [],
        'terraform': [],
        'prometheus': False,
        'otel': False,
        'package_managers': [],
        'services': [],
    }

    # Walk limited depth to avoid expensive operations
    max_entries = 10000
    entries_seen = 0
    for root, dirs, files in os.walk(path):
        entries_seen += len(files) + len(dirs)
        if entries_seen > max_entries:
            logger.warning('scan truncated: too many entries')
            break

        relroot = os.path.relpath(root, path)
        for f in files:
            fp = Path(root) / f
            nf = f.lower()
            evidence['files_present'].append(os.path.join(relroot, f))

            # Detect workflows
            if relroot.startswith('.github') and nf.endswith('.yml') or nf.endswith('.yaml'):
                if '.github/workflows' in os.path.join(relroot, f).replace('\\', '/'):
                    content = _read_file_safe(fp)
                    evidence['workflows'].append({'path': os.path.join(relroot, f), 'content_preview': content[:1024]})

            # Dockerfile
            if nf == 'dockerfile' or nf.startswith('dockerfile') or f.lower().endswith('.dockerfile'):
                evidence['dockerfiles'].append(os.path.join(relroot, f))

            # Kubernetes manifests: simple YAML files containing 'kind: Deployment' or 'apiVersion'
            if nf.endswith('.yaml') or nf.endswith('.yml'):
                content = _read_file_safe(fp)
                lc = content.lower()
                if 'kind: deployment' in lc or 'kind: service' in lc or 'apiVersion:' in content:
                    evidence['kubernetes_manifests'].append({'path': os.path.join(relroot, f), 'preview': content[:1024]})

            # Helm charts
            if f.lower() == 'chart.yaml' and 'charts' in relroot:
                evidence['helm_charts'].append(os.path.join(relroot, f))

            # Terraform
            if f.endswith('.tf'):
                evidence['terraform'].append(os.path.join(relroot, f))

            # Prometheus or OTEL config detection
            if 'prometheus' in nf or 'prometheus.yml' in nf:
                evidence['prometheus'] = True
            if 'otel' in nf or 'opentelemetry' in nf or 'collector' in nf:
                evidence['otel'] = True

            # Package managers
            if nf in ('package.json', 'pyproject.toml', 'requirements.txt', 'setup.py'):
                evidence['package_managers'].append(os.path.join(relroot, f))

            # Heuristic: service directories (presence of Dockerfile, package.json, requirements)
            if nf in ('package.json', 'requirements.txt', 'pyproject.toml'):
                # mark service at directory
                service_dir = relroot if relroot != '.' else '/'
                evidence['services'].append({'path': service_dir, 'marker': nf})

        # Limit depth to avoid recursion into node_modules, .venv
        if any(p in root for p in ['node_modules', '.venv', 'venv', '__pycache__']):
            dirs[:] = []

    # Normalize dedupe lists
    for k in ('dockerfiles', 'workflows', 'helm_charts', 'terraform', 'kubernetes_manifests'):
        evidence[k] = list({json.dumps(e) if isinstance(e, dict) else e for e in evidence.get(k, [])})

    # safe counts: if value is list/dict count elements, if bool use int, else 1/0
    counts = {}
    for k, v in evidence.items():
        if isinstance(v, (list, dict)):
            counts[k] = len(v)
        elif isinstance(v, bool):
            counts[k] = int(v)
        elif v is None:
            counts[k] = 0
        else:
            counts[k] = 1
    progress('scanned_files', {'counts': counts})

    # Topology extraction
    topology = TopologyExtractor().extract_from_local_path(path)
    progress('topology', {'topology': topology})

    # Scoring
    scoring_engine = OperationalScoringEngine()
    scores = scoring_engine.score_from_evidence(evidence, topology)
    progress('scored', {'scores': scores})

    result['scanned'] = True
    result['evidence'] = evidence
    result['topology'] = topology
    result['scores'] = scores

    progress('completed', {'result_summary': {'services': len(evidence['services']), 'scores': scores}})
    try:
        if run_id:
            finalize_run(run_id, result)
    except Exception:
        pass
    return json.loads(json.dumps(result))
