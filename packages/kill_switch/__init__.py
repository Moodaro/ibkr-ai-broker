"""
Kill switch module for emergency trading halt.

Provides global emergency stop mechanism that can be activated via:
- Environment variable (KILL_SWITCH_ENABLED=true)
- API call (POST /api/v1/kill-switch/activate)
- Dashboard button

When activated:
- All new proposals rejected
- Pending orders cancelled (if supported)
- Event logged to audit store
- State persisted to prevent accidental reactivation
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

try:
    from packages.structured_logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    # Fallback if structured_logging not available
    import logging
    logger = logging.getLogger(__name__)


from pydantic import BaseModel, Field


class KillSwitchState(BaseModel):
    """Kill switch state model."""
    
    enabled: bool = Field(default=False, description="Whether kill switch is active")
    activated_at: Optional[datetime] = Field(default=None, description="When kill switch was activated")
    activated_by: Optional[str] = Field(default=None, description="Who/what activated the kill switch")
    reason: Optional[str] = Field(default=None, description="Reason for activation")


class KillSwitch:
    """
    Global kill switch for emergency trading halt.
    
    Thread-safe singleton that manages emergency stop state.
    State persists across restarts via file storage.
    """
    
    _instance: Optional["KillSwitch"] = None
    _lock = Lock()
    
    def __new__(cls, state_file: str = ".kill_switch_state"):
        """Ensure singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, state_file: str = ".kill_switch_state"):
        """
        Initialize kill switch.
        
        Args:
            state_file: Path to state persistence file
        """
        if not hasattr(self, "_initialized"):
            self._state_file = Path(state_file)
            self._state = self._load_state()
            self._check_env_override()
            self._initialized = True
    
    def _load_state(self) -> KillSwitchState:
        """Load kill switch state from file."""
        if self._state_file.exists():
            try:
                import json
                with open(self._state_file, "r") as f:
                    data = json.load(f)
                    # Convert ISO datetime strings back to datetime objects
                    if data.get("activated_at"):
                        data["activated_at"] = datetime.fromisoformat(data["activated_at"])
                    return KillSwitchState(**data)
            except Exception:
                # If file is corrupted, start fresh
                return KillSwitchState()
        return KillSwitchState()
    
    def _save_state(self) -> None:
        """Save kill switch state to file."""
        try:
            import json
            with open(self._state_file, "w") as f:
                data = self._state.model_dump()
                # Convert datetime to ISO string for JSON serialization
                if data.get("activated_at"):
                    data["activated_at"] = data["activated_at"].isoformat()
                json.dump(data, f, indent=2)
        except Exception as e:
            # Log error but don't fail - kill switch state is in memory
            logger.warning("failed_to_save_kill_switch_state", error=str(e))
    
    def _check_env_override(self) -> None:
        """Check for environment variable override."""
        env_enabled = os.getenv("KILL_SWITCH_ENABLED", "").lower() in ("true", "1", "yes")
        if env_enabled and not self._state.enabled:
            self._state.enabled = True
            self._state.activated_at = datetime.now(timezone.utc)
            self._state.activated_by = "environment_variable"
            self._state.reason = "KILL_SWITCH_ENABLED environment variable set"
            self._save_state()
    
    def is_enabled(self) -> bool:
        """
        Check if kill switch is currently enabled.
        
        Returns:
            True if kill switch is active, False otherwise
        """
        # Always check environment variable for immediate override
        env_enabled = os.getenv("KILL_SWITCH_ENABLED", "").lower() in ("true", "1", "yes")
        if env_enabled:
            return True
        
        return self._state.enabled
    
    def activate(self, activated_by: str, reason: str = "Emergency stop") -> KillSwitchState:
        """
        Activate kill switch.
        
        Args:
            activated_by: Who/what is activating (e.g., "admin", "api", "dashboard")
            reason: Reason for activation
            
        Returns:
            Current kill switch state
        """
        with self._lock:
            if not self._state.enabled:
                self._state.enabled = True
                self._state.activated_at = datetime.now(timezone.utc)
                self._state.activated_by = activated_by
                self._state.reason = reason
                self._save_state()
            
            return self._state.model_copy(deep=True)
    
    def deactivate(self, deactivated_by: str) -> KillSwitchState:
        """
        Deactivate kill switch.
        
        WARNING: Only use after verifying system is safe to resume trading.
        
        Args:
            deactivated_by: Who is deactivating (requires admin privileges)
            
        Returns:
            Current kill switch state
        """
        with self._lock:
            # Check environment variable - cannot deactivate if set via env
            env_enabled = os.getenv("KILL_SWITCH_ENABLED", "").lower() in ("true", "1", "yes")
            if env_enabled:
                raise RuntimeError(
                    "Cannot deactivate kill switch: KILL_SWITCH_ENABLED environment variable is set. "
                    "Remove environment variable and restart service to deactivate."
                )
            
            if self._state.enabled:
                self._state.enabled = False
                # Keep history of last activation
                self._save_state()
            
            return self._state.model_copy(deep=True)
    
    def get_state(self) -> KillSwitchState:
        """
        Get current kill switch state.
        
        Returns:
            Current state (copy)
        """
        return self._state.model_copy(deep=True)
    
    def check_or_raise(self, operation: str = "operation") -> None:
        """
        Check kill switch and raise exception if enabled.
        
        Args:
            operation: Name of operation being attempted
            
        Raises:
            RuntimeError: If kill switch is enabled
        """
        if self.is_enabled():
            state = self.get_state()
            raise RuntimeError(
                f"Kill switch is active - {operation} blocked. "
                f"Activated at: {state.activated_at}, "
                f"By: {state.activated_by}, "
                f"Reason: {state.reason}"
            )


# Global singleton instance
_kill_switch: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    """
    Get global kill switch instance.
    
    Returns:
        KillSwitch singleton
    """
    global _kill_switch
    if _kill_switch is None:
        _kill_switch = KillSwitch()
    return _kill_switch


__all__ = [
    "KillSwitch",
    "KillSwitchState",
    "get_kill_switch",
]
