"""
Live trading configuration and validation.

This module manages configuration for live trading mode, including:
- Order size limits
- Symbol whitelist
- Daily loss limits
- Live mode enablement

Safety-first design: strict validation before allowing live orders.
"""

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Set

from packages.feature_flags import get_feature_flags


@dataclass
class LiveTradingConfig:
    """Configuration for live trading mode.
    
    Attributes:
        enabled: Whether live trading is enabled (from feature flag)
        max_order_size: Maximum order quantity for live orders
        max_order_value_usd: Maximum order value in USD
        symbol_whitelist: Set of allowed symbols for live trading
        daily_loss_limit_usd: Maximum daily loss before halting (None = no limit)
        require_safety_checks: Whether to require safety checks before live orders
        require_manual_approval: Whether to require manual approval for live orders
    """
    enabled: bool
    max_order_size: int
    max_order_value_usd: Decimal
    symbol_whitelist: Set[str]
    daily_loss_limit_usd: Optional[Decimal]
    require_safety_checks: bool
    require_manual_approval: bool


class LiveConfigError(Exception):
    """Raised when live trading configuration is invalid."""
    pass


class LiveConfigManager:
    """Manages live trading configuration.
    
    Loads configuration from environment variables and feature flags.
    Provides validation for live trading operations.
    """
    
    def __init__(self):
        """Initialize live config manager."""
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from environment and feature flags."""
        # Check if live trading is enabled via feature flag
        try:
            flags = get_feature_flags()
            self.enabled = flags.is_enabled("live_trading_mode")
        except Exception:
            # If feature flags not available, default to disabled
            self.enabled = False
        
        # Load configuration from environment variables
        self.max_order_size = int(
            os.getenv("LIVE_MAX_ORDER_SIZE", "100")
        )
        
        self.max_order_value_usd = Decimal(
            os.getenv("LIVE_MAX_ORDER_VALUE_USD", "10000")
        )
        
        # Symbol whitelist (comma-separated)
        whitelist_str = os.getenv("LIVE_SYMBOL_WHITELIST", "")
        if whitelist_str:
            self.symbol_whitelist = set(
                s.strip().upper() for s in whitelist_str.split(",")
            )
        else:
            # Default whitelist for initial live trading
            self.symbol_whitelist = {
                "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
                "SPY", "QQQ", "IWM", "DIA"
            }
        
        # Daily loss limit (None = no limit)
        loss_limit_str = os.getenv("LIVE_DAILY_LOSS_LIMIT_USD")
        if loss_limit_str:
            self.daily_loss_limit_usd = Decimal(loss_limit_str)
        else:
            self.daily_loss_limit_usd = None
        
        # Safety requirements
        self.require_safety_checks = os.getenv(
            "LIVE_REQUIRE_SAFETY_CHECKS", "true"
        ).lower() == "true"
        
        self.require_manual_approval = os.getenv(
            "LIVE_REQUIRE_MANUAL_APPROVAL", "true"
        ).lower() == "true"
    
    def get_config(self) -> LiveTradingConfig:
        """Get current live trading configuration.
        
        Returns:
            LiveTradingConfig with current settings
        """
        return LiveTradingConfig(
            enabled=self.enabled,
            max_order_size=self.max_order_size,
            max_order_value_usd=self.max_order_value_usd,
            symbol_whitelist=self.symbol_whitelist,
            daily_loss_limit_usd=self.daily_loss_limit_usd,
            require_safety_checks=self.require_safety_checks,
            require_manual_approval=self.require_manual_approval,
        )
    
    def is_live_enabled(self) -> bool:
        """Check if live trading is currently enabled.
        
        Returns:
            True if live trading is enabled, False otherwise
        """
        # Reload feature flag state
        try:
            flags = get_feature_flags()
            return flags.is_enabled("live_trading_mode")
        except Exception:
            return False
    
    def validate_symbol(self, symbol: str) -> bool:
        """Check if symbol is allowed for live trading.
        
        Args:
            symbol: Instrument symbol to validate
        
        Returns:
            True if symbol is in whitelist, False otherwise
        """
        return symbol.upper() in self.symbol_whitelist
    
    def validate_order_size(self, quantity: int) -> bool:
        """Check if order size is within limits.
        
        Args:
            quantity: Order quantity to validate
        
        Returns:
            True if quantity is within limits, False otherwise
        """
        return 0 < quantity <= self.max_order_size
    
    def validate_order_value(self, value_usd: Decimal) -> bool:
        """Check if order value is within limits.
        
        Args:
            value_usd: Order value in USD to validate
        
        Returns:
            True if value is within limits, False otherwise
        """
        return Decimal("0") < value_usd <= self.max_order_value_usd
    
    def can_submit_live_order(
        self,
        symbol: str,
        quantity: int,
        estimated_value_usd: Decimal
    ) -> tuple[bool, str]:
        """Check if order can be submitted to live broker.
        
        Validates all live trading constraints:
        - Live mode enabled
        - Symbol in whitelist
        - Order size within limits
        - Order value within limits
        
        Args:
            symbol: Instrument symbol
            quantity: Order quantity
            estimated_value_usd: Estimated order value in USD
        
        Returns:
            Tuple of (can_submit, reason)
            - can_submit: True if order passes all checks
            - reason: Human-readable reason if rejected
        """
        # Check if live trading is enabled
        if not self.is_live_enabled():
            return False, "Live trading is not enabled"
        
        # Validate symbol
        if not self.validate_symbol(symbol):
            return False, f"Symbol {symbol} not in live trading whitelist"
        
        # Validate order size
        if not self.validate_order_size(quantity):
            return False, (
                f"Order size {quantity} exceeds limit {self.max_order_size}"
            )
        
        # Validate order value
        if not self.validate_order_value(estimated_value_usd):
            return False, (
                f"Order value ${estimated_value_usd} exceeds limit "
                f"${self.max_order_value_usd}"
            )
        
        return True, "Order passes live trading validation"
    
    def add_symbol_to_whitelist(self, symbol: str) -> None:
        """Add symbol to live trading whitelist.
        
        Args:
            symbol: Symbol to add
        """
        self.symbol_whitelist.add(symbol.upper())
    
    def remove_symbol_from_whitelist(self, symbol: str) -> None:
        """Remove symbol from live trading whitelist.
        
        Args:
            symbol: Symbol to remove
        """
        self.symbol_whitelist.discard(symbol.upper())
    
    def set_max_order_size(self, size: int) -> None:
        """Update maximum order size for live trading.
        
        Args:
            size: New maximum order size
        
        Raises:
            ValueError: If size is not positive
        """
        if size <= 0:
            raise ValueError("Max order size must be positive")
        self.max_order_size = size
    
    def set_max_order_value(self, value_usd: Decimal) -> None:
        """Update maximum order value for live trading.
        
        Args:
            value_usd: New maximum order value in USD
        
        Raises:
            ValueError: If value is not positive
        """
        if value_usd <= 0:
            raise ValueError("Max order value must be positive")
        self.max_order_value_usd = value_usd


# Singleton instance
_live_config_manager: Optional[LiveConfigManager] = None


def get_live_config_manager() -> LiveConfigManager:
    """Get singleton live config manager instance.
    
    Returns:
        LiveConfigManager instance
    """
    global _live_config_manager
    
    if _live_config_manager is None:
        _live_config_manager = LiveConfigManager()
    
    return _live_config_manager


def is_live_trading_enabled() -> bool:
    """Quick check if live trading is currently enabled.
    
    Returns:
        True if live trading is enabled, False otherwise
    """
    manager = get_live_config_manager()
    return manager.is_live_enabled()
