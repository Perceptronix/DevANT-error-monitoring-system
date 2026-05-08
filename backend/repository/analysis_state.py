"""
Simple in-memory analysis run state store. Not persistent. Suitable for demo/testing.
"""
from typing import Dict, Any
import uuid
import threading
import asyncio
import copy
from .job_state_machine import initial_job_record, transition, finalize_with_result, fail_with_error, cancel


_runs: Dict[str, Dict[str, Any]] = {}
_runs_lock = threading.Lock()
_async_lock = asyncio.Lock()


def create_run(repo_url: str) -> str:
    run_id = str(uuid.uuid4())
    rec = initial_job_record(run_id, repo_url)
    with _runs_lock:
        _runs[run_id] = rec
    return run_id


def _atomic_update(run_id: str, updater):
    """Thread-safe atomic update: updater takes old record and returns new record."""
    with _runs_lock:
        if run_id not in _runs:
            raise KeyError('run_id not found')
        old = _runs[run_id]
        new = updater(old)
        # store new record immutably (copy)
        _runs[run_id] = copy.deepcopy(new)
        return copy.deepcopy(new)


async def async_atomic_update(run_id: str, updater):
    async with _async_lock:
        # reuse thread lock to protect underlying dict
        def _up(old):
            return updater(old)
        return _atomic_update(run_id, _up)


def transition_run(run_id: str, target: str, note: str | None = None) -> Dict[str, Any]:
    def _up(old):
        return transition(old, target, note)
    return _atomic_update(run_id, _up)


def finalize_run(run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    def _up(old):
        return finalize_with_result(old, result)
    return _atomic_update(run_id, _up)


def fail_run(run_id: str, error: str) -> Dict[str, Any]:
    def _up(old):
        return fail_with_error(old, error)
    return _atomic_update(run_id, _up)


def cancel_run(run_id: str, reason: str | None = None) -> Dict[str, Any]:
    def _up(old):
        return cancel(old, reason)
    return _atomic_update(run_id, _up)


def get_run_snapshot(run_id: str) -> Dict[str, Any]:
    with _runs_lock:
        rec = _runs.get(run_id)
        if rec is None:
            return {'status': 'not_found'}
        return copy.deepcopy(rec)


def set_partial_update(run_id: str, step: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Atomic partial update for progressive UI rendering."""
    def _up(old):
        new = copy.deepcopy(old)
        partial = copy.deepcopy(new.get('partial', {}))
        partial[step] = copy.deepcopy(payload)
        new['partial'] = partial
        return new
    return _atomic_update(run_id, _up)


def list_runs(limit: int = 20):
    with _runs_lock:
        items = list(_runs.values())
        items.sort(key=lambda item: item.get('transitions', [{}])[-1].get('at', ''), reverse=True)
        return copy.deepcopy(items[:limit])
