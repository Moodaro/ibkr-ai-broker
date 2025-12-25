"""Feature Flags for IBKR AI Broker.

This module provides runtime feature flag management with environment variable overrides.

Usage:
    from packages.feature_flags import get_feature_flags, FeatureFlags
    
    flags = get_feature_flags()
    
    if flags.is_enabled("live_trading_mode"):
        # Use real broker
    else:
        # Use fake broker
    
    if flags.is_enabled("auto_approval"):
        # Auto-approve low-risk orders
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional

__all__ = ["FeatureFlags", "get_feature_flags", "set_feature_flags"]


@dataclass
class FeatureFlags:
    """Feature flags configuration with environment variable overrides."""
    
    # Trading mode
    live_trading_mode: bool = False  # Use real broker (default: fake)
    
    # Approval workflow
    auto_approval: bool = False  # Auto-approve orders below threshold
    auto_approval_max_notional: float = 1000.0  # Max notional for auto-approval
    
    # Risk engine
    new_risk_rules: bool = False  # Enable experimental risk rules
    strict_validation: bool = True  # Strict schema validation
    
    # Feature toggles
    enable_dashboard: bool = True  # Enable approval dashboard
    enable_mcp_server: bool = True  # Enable MCP server
    
    # Lock for thread safety
    _lock: Lock = field(default_factory=Lock)
    
    @classmethod
    def from_config_file(cls, config_path: str = "feature_flags.json") -> "FeatureFlags":
        """Load feature flags from JSON config file.
        
        Args:
            config_path: Path to JSON config file
            
        Returns:
            FeatureFlags instance with values from file
        """
        path = Path(config_path)
        
        if not path.exists():
            return cls()
        
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            return cls(
                live_trading_mode=data.get("live_trading_mode", False),
                auto_approval=data.get("auto_approval", False),
                auto_approval_max_notional=data.get("auto_approval_max_notional", 1000.0),
                new_risk_rules=data.get("new_risk_rules", False),
                strict_validation=data.get("strict_validation", True),
                enable_dashboard=data.get("enable_dashboard", True),
                enable_mcp_server=data.get("enable_mcp_server", True),
            )
        except Exception:
            # If config load fails, return defaults
            return cls()
    
    @classmethod
    def from_env(cls) -> "FeatureFlags":
        """Load feature flags from environment variables.
        
        Environment variables override config file values.
        
        Env vars:
            LIVE_TRADING_MODE: "true" or "false"
            AUTO_APPROVAL: "true" or "false"
            AUTO_APPROVAL_MAX_NOTIONAL: float value
            NEW_RISK_RULES: "true" or "false"
            STRICT_VALIDATION: "true" or "false"
            ENABLE_DASHBOARD: "true" or "false"
            ENABLE_MCP_SERVER: "true" or "false"
            
        Returns:
            FeatureFlags instance with values from env vars
        """
        def parse_bool(value: Optional[str], default: bool) -> bool:
            if value is None:
                return default
            return value.lower() in ("true", "1", "yes", "on")
        
        def parse_float(value: Optional[str], default: float) -> float:
            if value is None:
                return default
            try:
                return float(value)
            except ValueError:
                return default
        
        return cls(
            live_trading_mode=parse_bool(os.getenv("LIVE_TRADING_MODE"), False),
            auto_approval=parse_bool(os.getenv("AUTO_APPROVAL"), False),
            auto_approval_max_notional=parse_float(os.getenv("AUTO_APPROVAL_MAX_NOTIONAL"), 1000.0),
            new_risk_rules=parse_bool(os.getenv("NEW_RISK_RULES"), False),
            strict_validation=parse_bool(os.getenv("STRICT_VALIDATION"), True),
            enable_dashboard=parse_bool(os.getenv("ENABLE_DASHBOARD"), True),
            enable_mcp_server=parse_bool(os.getenv("ENABLE_MCP_SERVER"), True),
        )
    
    @classmethod
    def load(cls, config_path: str = "feature_flags.json") -> "FeatureFlags":
        """Load feature flags from config file with env var overrides.
        
        Priority: env vars > config file > defaults
        
        Args:
            config_path: Path to JSON config file
            
        Returns:
            FeatureFlags instance
        """
        # Start with config file
        flags = cls.from_config_file(config_path)
        
        # Override with env vars
        env_flags = cls.from_env()
        
        # Apply env var overrides (only if env var is set)
        if os.getenv("LIVE_TRADING_MODE") is not None:
            flags.live_trading_mode = env_flags.live_trading_mode
        if os.getenv("AUTO_APPROVAL") is not None:
            flags.auto_approval = env_flags.auto_approval
        if os.getenv("AUTO_APPROVAL_MAX_NOTIONAL") is not None:
            flags.auto_approval_max_notional = env_flags.auto_approval_max_notional
        if os.getenv("NEW_RISK_RULES") is not None:
            flags.new_risk_rules = env_flags.new_risk_rules
        if os.getenv("STRICT_VALIDATION") is not None:
            flags.strict_validation = env_flags.strict_validation
        if os.getenv("ENABLE_DASHBOARD") is not None:
            flags.enable_dashboard = env_flags.enable_dashboard
        if os.getenv("ENABLE_MCP_SERVER") is not None:
            flags.enable_mcp_server = env_flags.enable_mcp_server
        
        return flags
    
    def is_enabled(self, flag_name: str) -> bool:
        """Check if a feature flag is enabled.
        
        Args:
            flag_name: Name of flag (e.g., "live_trading_mode")
            
        Returns:
            True if flag is enabled, False otherwise
        """
        with self._lock:
            return getattr(self, flag_name, False)
    
    def set_flag(self, flag_name: str, value: bool) -> None:
        """Set a feature flag value at runtime.
        
        Args:
            flag_name: Name of flag
            value: New value
        """
        with self._lock:
            if hasattr(self, flag_name):
                setattr(self, flag_name, value)
    
    def to_dict(self) -> dict:
        """Export flags to dictionary.
        
        Returns:
            Dictionary with all flag values
        """
        with self._lock:
            return {
                "live_trading_mode": self.live_trading_mode,
                "auto_approval": self.auto_approval,
                "auto_approval_max_notional": self.auto_approval_max_notional,
                "new_risk_rules": self.new_risk_rules,
                "strict_validation": self.strict_validation,
                "enable_dashboard": self.enable_dashboard,
                "enable_mcp_server": self.enable_mcp_server,
            }


# Global feature flags instance
_feature_flags: Optional[FeatureFlags] = None
_flags_lock = Lock()


def get_feature_flags() -> FeatureFlags:
    """Get global feature flags instance.
    
    Loads from config file with env var overrides on first call.
    
    Returns:
        Global FeatureFlags instance
    """
    global _feature_flags
    
    if _feature_flags is None:
        with _flags_lock:
            if _feature_flags is None:
                _feature_flags = FeatureFlags.load()
    
    return _feature_flags


def set_feature_flags(flags: FeatureFlags) -> None:
    """Set global feature flags (for testing).
    
    Args:
        flags: FeatureFlags instance to use
    """
    global _feature_flags
    
    with _flags_lock:
        _feature_flags = flags
