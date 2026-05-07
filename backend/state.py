"""
JSON-based state management for error tracking.

Provides persistence for error signatures and mutes without requiring
a database. State is stored in JSON files in the data/ directory.

Uses file locking to handle concurrent access safely.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

try:
    from filelock import FileLock
except ImportError:
    # Fallback if filelock not installed
    class FileLock:
        def __init__(self, path):
            self.path = path
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

from schemas import PreviousErrorState

logger = logging.getLogger(__name__)

# Default data directory
DATA_DIR = Path(__file__).parent / "data"


class StateManager:
    """
    JSON-based state persistence for error monitoring.
    
    Manages two files:
    - error_signatures.json: Tracks error patterns and their history
    - mutes.json: Tracks active mutes
    
    Thread-safe through file locking.
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize state manager.
        
        Args:
            data_dir: Directory to store state files (defaults to backend/data/)
        """
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.signatures_file = self.data_dir / "error_signatures.json"
        self.mutes_file = self.data_dir / "mutes.json"
        self.kv_file = self.data_dir / "kv_store.json"
        
        self._ensure_files()
        logger.info(f"State manager initialized with data dir: {self.data_dir}")
    
    def _ensure_files(self):
        """Ensure state files exist with valid JSON."""
        for file_path in [self.signatures_file, self.mutes_file]:
            if not file_path.exists():
                file_path.write_text("{}")
                logger.info(f"Created state file: {file_path}")
        if not self.kv_file.exists():
            self.kv_file.write_text("{}")
            logger.info(f"Created kv store file: {self.kv_file}")
    
    def _read_json(self, path: Path) -> dict:
        """Read JSON file with locking."""
        lock_path = f"{path}.lock"
        with FileLock(lock_path):
            try:
                content = path.read_text()
                return json.loads(content) if content.strip() else {}
            except (json.JSONDecodeError, FileNotFoundError) as e:
                logger.warning(f"Error reading {path}: {e}, attempting recovery")
                # Backup corrupted file
                try:
                    bak = path.with_suffix(path.suffix + f".bak.{datetime.utcnow().timestamp()}")
                    path.replace(bak)
                    logger.warning(f"Backed up corrupted state to {bak}")
                except Exception:
                    logger.exception("Failed to backup corrupted state file")
                # Create a fresh empty file
                try:
                    path.write_text("{}")
                except Exception:
                    logger.exception("Failed to create fresh state file after corruption")
                return {}
    
    def _write_json(self, path: Path, data: dict):
        """Write JSON file with locking."""
        lock_path = f"{path}.lock"
        with FileLock(lock_path):
            # Atomic write: write to temp file then replace
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            try:
                tmp.replace(path)
            except Exception:
                # Fallback to overwrite
                path.write_text(json.dumps(data, indent=2, default=str))

    # =========================================================================
    # Generic KV store helpers (for tests/compatibility)
    # =========================================================================

    def update(self, key: str, value: Dict[str, Any]):
        """Generic key/value update persisted to kv_store.json."""
        data = self._read_json(self.kv_file)
        data[key] = value
        self._write_json(self.kv_file, data)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        data = self._read_json(self.kv_file)
        return data.get(key)

    def persist(self):
        """Ensure all state files are flushed and consistent (noop for JSON store)."""
        # Files are written synchronously; this is a semantic hook for interfaces
        for p in [self.signatures_file, self.mutes_file, self.kv_file]:
            if not p.exists():
                p.write_text("{}")
    
    # =========================================================================
    # Error Signatures
    # =========================================================================
    
    def get_signature(self, signature: str) -> Optional[PreviousErrorState]:
        """
        Get previous state for an error signature.
        
        Args:
            signature: The error signature to look up
            
        Returns:
            PreviousErrorState or None if not found
        """
        data = self._read_json(self.signatures_file)
        
        if signature not in data:
            return None
        
        try:
            entry = data[signature]
            return PreviousErrorState(
                signature=signature,
                first_seen=self._parse_datetime(entry.get("first_seen")),
                last_seen=self._parse_datetime(entry.get("last_seen")),
                last_alerted=self._parse_datetime(entry.get("last_alerted")),
                times_seen=entry.get("times_seen", 0),
                linear_issue_id=entry.get("linear_issue_id"),
                linear_issue_status=entry.get("linear_issue_status"),
                linear_issue_url=entry.get("linear_issue_url"),
                slack_thread_ts=entry.get("slack_thread_ts"),
                muted_until=self._parse_datetime(entry.get("muted_until")),
                muted_by=entry.get("muted_by"),
                mute_reason=entry.get("mute_reason"),
                last_severity=entry.get("last_severity"),
                last_summary=entry.get("last_summary"),
            )
        except Exception as e:
            logger.error(f"Error parsing signature state: {e}")
            return None
    
    def upsert_signature(self, signature: str, updates: Dict[str, Any]):
        """
        Create or update an error signature.
        
        Args:
            signature: The error signature
            updates: Fields to update
        """
        data = self._read_json(self.signatures_file)
        now = datetime.utcnow().isoformat()
        
        if signature not in data:
            data[signature] = {
                "signature": signature,
                "first_seen": now,
                "times_seen": 0,
            }
            logger.debug(f"Created new signature: {signature[:50]}...")
        
        # Update fields
        data[signature].update(updates)
        data[signature]["last_seen"] = now
        data[signature]["times_seen"] = data[signature].get("times_seen", 0) + 1
        
        self._write_json(self.signatures_file, data)
        logger.debug(f"Updated signature: {signature[:50]}...")
    
    def record_alert(self, signature: str, severity: str, summary: Dict[str, Any] = None):
        """
        Record that an alert was sent for this signature.
        
        Args:
            signature: The error signature
            severity: Severity level
            summary: Analysis summary
        """
        self.upsert_signature(signature, {
            "last_alerted": datetime.utcnow().isoformat(),
            "last_severity": severity,
            "last_summary": summary,
        })
    
    def update_linear_ticket(
        self, 
        signature: str, 
        issue_id: str, 
        status: str,
        url: Optional[str] = None
    ):
        """
        Update Linear ticket tracking for a signature.
        
        Args:
            signature: The error signature
            issue_id: Linear issue ID
            status: Ticket status
            url: Ticket URL
        """
        updates = {
            "linear_issue_id": issue_id,
            "linear_issue_status": status,
        }
        if url:
            updates["linear_issue_url"] = url
        
        self.upsert_signature(signature, updates)
        logger.info(f"Updated Linear ticket for {signature[:30]}...: {issue_id} ({status})")
    
    def update_slack_thread(self, signature: str, thread_ts: str):
        """
        Update Slack thread tracking for a signature.
        
        Args:
            signature: The error signature
            thread_ts: Slack thread timestamp
        """
        self.upsert_signature(signature, {"slack_thread_ts": thread_ts})
    
    def get_all_signatures(self) -> Dict[str, Dict[str, Any]]:
        """Get all stored signatures (for debugging/admin)."""
        return self._read_json(self.signatures_file)
    
    # =========================================================================
    # Mutes
    # =========================================================================
    
    def get_active_mutes(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all currently active mutes.
        
        Returns:
            Dict mapping signature patterns to mute info
        """
        data = self._read_json(self.mutes_file)
        now = datetime.utcnow()
        
        active = {}
        for sig, mute_info in data.items():
            muted_until = self._parse_datetime(mute_info.get("muted_until"))
            if muted_until and muted_until > now:
                active[sig] = mute_info
        
        return active
    
    def add_mute(
        self, 
        signature: str, 
        duration_hours: int, 
        muted_by: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """
        Mute an error signature for a duration.
        
        Args:
            signature: The error signature (or pattern) to mute
            duration_hours: How long to mute
            muted_by: Who initiated the mute
            reason: Why it was muted
        """
        data = self._read_json(self.mutes_file)
        
        muted_until = datetime.utcnow() + timedelta(hours=duration_hours)
        
        data[signature] = {
            "signature": signature,
            "muted_until": muted_until.isoformat(),
            "muted_at": datetime.utcnow().isoformat(),
            "muted_by": muted_by,
            "reason": reason,
            "duration_hours": duration_hours,
        }
        
        self._write_json(self.mutes_file, data)
        logger.info(f"Muted error for {duration_hours}h: {signature[:50]}...")
        
        # Also update the signature record
        self.upsert_signature(signature, {
            "muted_until": muted_until.isoformat(),
            "muted_by": muted_by,
            "mute_reason": reason,
        })
    
    def remove_mute(self, signature: str):
        """
        Remove a mute for a signature.
        
        Args:
            signature: The error signature to unmute
        """
        data = self._read_json(self.mutes_file)
        
        if signature in data:
            del data[signature]
            self._write_json(self.mutes_file, data)
            logger.info(f"Removed mute: {signature[:50]}...")
        
        # Also update signature record
        self.upsert_signature(signature, {
            "muted_until": None,
            "muted_by": None,
            "mute_reason": None,
        })
    
    def is_muted(self, signature: str) -> bool:
        """
        Check if a signature is currently muted.
        
        Note: This is an exact match. For semantic matching,
        use the semantic_matcher module.
        
        Args:
            signature: The error signature to check
            
        Returns:
            True if muted
        """
        active_mutes = self.get_active_mutes()
        return signature in active_mutes
    
    def get_mute_info(self, signature: str) -> Optional[Dict[str, Any]]:
        """
        Get mute information for a signature.
        
        Args:
            signature: The error signature
            
        Returns:
            Mute info dict or None
        """
        active_mutes = self.get_active_mutes()
        return active_mutes.get(signature)
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from string or return None."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            # Handle ISO format with or without timezone
            if isinstance(value, str):
                # Remove 'Z' suffix if present
                value = value.replace('Z', '+00:00')
                # Try parsing
                if '+' in value or value.endswith('Z'):
                    return datetime.fromisoformat(value.replace('+00:00', ''))
                return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
        return None
    
    def clear_all(self):
        """Clear all state (for testing)."""
        self._write_json(self.signatures_file, {})
        self._write_json(self.mutes_file, {})
        logger.warning("Cleared all state data")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored state."""
        signatures = self._read_json(self.signatures_file)
        mutes = self.get_active_mutes()
        
        return {
            "total_signatures": len(signatures),
            "active_mutes": len(mutes),
            "signatures_with_tickets": sum(
                1 for s in signatures.values() 
                if s.get("linear_issue_id")
            ),
            "data_dir": str(self.data_dir),
        }


# Singleton instance for easy access
_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Get the singleton state manager instance."""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager
