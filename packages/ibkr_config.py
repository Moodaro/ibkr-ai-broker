"""
IBKR Connection Configuration.

Manages connection settings for Interactive Brokers API (TWS/Gateway).
Supports both paper and live trading modes with environment variable overrides.
"""

from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IBKRConfig(BaseSettings):
    """
    IBKR connection configuration from environment variables.
    
    Environment Variables:
        IBKR_HOST: Gateway/TWS host (default: 127.0.0.1)
        IBKR_PORT: Gateway/TWS port (default: 7497 for paper, 7496 for live)
        IBKR_CLIENT_ID: Client ID for connection (default: 1)
        IBKR_MODE: Trading mode - 'paper' or 'live' (default: paper)
        IBKR_CONNECT_TIMEOUT: Connection timeout in seconds (default: 10)
        IBKR_READ_TIMEOUT: Read timeout in seconds (default: 60)
        IBKR_RECONNECT_ENABLED: Enable automatic reconnection (default: True)
        IBKR_RECONNECT_MAX_RETRIES: Max reconnection attempts (default: 5)
        IBKR_RECONNECT_DELAY_BASE: Base delay for exponential backoff (default: 2)
        IBKR_READONLY_MODE: Force read-only mode (no order submissions) (default: False)
    
    Usage:
        config = IBKRConfig()
        print(f"Connecting to {config.host}:{config.port} (mode={config.mode})")
    """
    
    model_config = SettingsConfigDict(
        env_prefix="IBKR_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # Connection settings
    host: str = Field(default="127.0.0.1", description="IBKR Gateway/TWS host")
    port: int = Field(default=7497, description="IBKR Gateway/TWS port (7497=paper, 7496=live)")
    client_id: int = Field(default=1, ge=1, le=32, description="Client ID (1-32)")
    
    # Trading mode
    mode: Literal["paper", "live"] = Field(default="paper", description="Trading mode")
    
    # Timeouts
    connect_timeout: int = Field(default=10, ge=1, le=60, description="Connection timeout (seconds)")
    read_timeout: int = Field(default=60, ge=10, le=300, description="Read timeout (seconds)")
    
    # Reconnection settings
    reconnect_enabled: bool = Field(default=True, description="Enable automatic reconnection")
    reconnect_max_retries: int = Field(default=5, ge=0, le=20, description="Max reconnection attempts")
    reconnect_delay_base: float = Field(default=2.0, ge=0.5, le=10.0, description="Base delay for exponential backoff")
    
    # Safety settings
    readonly_mode: bool = Field(default=False, description="Force read-only mode (no order submissions)")
    
    def __init__(self, **kwargs):
        """Initialize config with auto port selection based on mode."""
        super().__init__(**kwargs)
        
        # Auto-select port if not explicitly set
        if "port" not in kwargs:
            self.port = 7497 if self.mode == "paper" else 7496
    
    @property
    def is_paper(self) -> bool:
        """Check if running in paper trading mode."""
        return self.mode == "paper"
    
    @property
    def is_live(self) -> bool:
        """Check if running in live trading mode."""
        return self.mode == "live"
    
    @property
    def can_write(self) -> bool:
        """Check if order submissions are allowed."""
        return not self.readonly_mode
    
    def get_connection_string(self) -> str:
        """Get human-readable connection string."""
        mode_str = "PAPER" if self.is_paper else "LIVE"
        readonly_str = " (READ-ONLY)" if self.readonly_mode else ""
        return f"{self.host}:{self.port} [{mode_str}]{readonly_str}"
    
    def to_dict(self) -> dict:
        """Export config as dictionary (safe for logging)."""
        return {
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "mode": self.mode,
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "reconnect_enabled": self.reconnect_enabled,
            "reconnect_max_retries": self.reconnect_max_retries,
            "reconnect_delay_base": self.reconnect_delay_base,
            "readonly_mode": self.readonly_mode,
        }


# Global config instance (singleton pattern)
_config_instance: IBKRConfig | None = None


def get_ibkr_config(force_reload: bool = False) -> IBKRConfig:
    """
    Get global IBKR configuration singleton.
    
    Args:
        force_reload: Force reload from environment (useful for testing)
    
    Returns:
        IBKRConfig instance
    """
    global _config_instance
    
    if _config_instance is None or force_reload:
        _config_instance = IBKRConfig()
    
    return _config_instance


def reset_ibkr_config():
    """Reset global config instance (for testing)."""
    global _config_instance
    _config_instance = None
