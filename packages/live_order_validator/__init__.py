"""
Order validation for live trading.

This module provides comprehensive validation for orders before
submission to live broker, including safety checks, symbol whitelist,
and order size limits.
"""

from decimal import Decimal
from typing import Optional

from packages.live_config import get_live_config_manager
from packages.safety_checks import get_safety_checker
from packages.schemas import OrderIntent
from packages.structured_logging import get_logger


logger = get_logger(__name__)


class OrderValidationError(Exception):
    """Raised when order validation fails."""
    pass


class LiveOrderValidator:
    """Validates orders for live trading submission.
    
    Performs comprehensive validation before allowing orders to be
    submitted to live broker:
    - Safety checks (infrastructure health)
    - Symbol whitelist
    - Order size limits
    - Order value limits
    - Pre-live readiness
    """
    
    def __init__(self):
        """Initialize live order validator."""
        self.config_manager = get_live_config_manager()
        self.safety_checker = get_safety_checker()
    
    def validate_order_for_live(
        self,
        intent: OrderIntent,
        estimated_price: Optional[Decimal] = None,
        skip_safety_checks: bool = False
    ) -> tuple[bool, str]:
        """Validate order for live trading submission.
        
        Runs all validation checks:
        1. Live trading enabled
        2. Safety checks pass (unless skipped)
        3. Symbol in whitelist
        4. Order size within limits
        5. Order value within limits
        
        Args:
            intent: OrderIntent to validate
            estimated_price: Estimated execution price (for value check)
            skip_safety_checks: Skip infrastructure safety checks (DANGEROUS)
        
        Returns:
            Tuple of (is_valid, reason)
            - is_valid: True if order passes all checks
            - reason: Human-readable explanation
        """
        # Check if live trading is enabled
        if not self.config_manager.is_live_enabled():
            logger.warning(
                "live_order_validation_failed",
                reason="live_trading_disabled",
                symbol=intent.instrument.symbol
            )
            return False, "Live trading is not enabled"
        
        # Run safety checks (unless explicitly skipped)
        if not skip_safety_checks:
            safety_valid, safety_reason = self._validate_safety_checks()
            if not safety_valid:
                logger.error(
                    "live_order_validation_failed",
                    reason="safety_checks_failed",
                    symbol=intent.instrument.symbol,
                    safety_reason=safety_reason
                )
                return False, safety_reason
        
        # Validate symbol whitelist
        symbol_valid, symbol_reason = self._validate_symbol(intent.instrument.symbol)
        if not symbol_valid:
            logger.warning(
                "live_order_validation_failed",
                reason="symbol_not_whitelisted",
                symbol=intent.instrument.symbol
            )
            return False, symbol_reason
        
        # Validate order size
        size_valid, size_reason = self._validate_order_size(intent.quantity)
        if not size_valid:
            logger.warning(
                "live_order_validation_failed",
                reason="order_size_exceeded",
                symbol=intent.instrument.symbol,
                quantity=intent.quantity
            )
            return False, size_reason
        
        # Validate order value (if price provided)
        if estimated_price is not None:
            value_valid, value_reason = self._validate_order_value(
                intent.quantity,
                estimated_price
            )
            if not value_valid:
                logger.warning(
                    "live_order_validation_failed",
                    reason="order_value_exceeded",
                    symbol=intent.instrument.symbol,
                    quantity=intent.quantity,
                    estimated_price=str(estimated_price)
                )
                return False, value_reason
        
        # All checks passed
        logger.info(
            "live_order_validation_passed",
            symbol=intent.instrument.symbol,
            quantity=intent.quantity,
            action=intent.action
        )
        
        return True, "Order passes live trading validation"
    
    def _validate_safety_checks(self) -> tuple[bool, str]:
        """Run safety checks to validate system readiness.
        
        Returns:
            Tuple of (is_valid, reason)
        """
        result = self.safety_checker.run_all_checks()
        
        if not result.ready_for_live:
            issues_str = "; ".join(result.blocking_issues)
            return False, f"Safety checks failed: {issues_str}"
        
        return True, "Safety checks passed"
    
    def _validate_symbol(self, symbol: str) -> tuple[bool, str]:
        """Validate symbol is in whitelist.
        
        Args:
            symbol: Instrument symbol
        
        Returns:
            Tuple of (is_valid, reason)
        """
        if not self.config_manager.validate_symbol(symbol):
            return False, f"Symbol {symbol} not in live trading whitelist"
        
        return True, "Symbol validated"
    
    def _validate_order_size(self, quantity: int) -> tuple[bool, str]:
        """Validate order size is within limits.
        
        Args:
            quantity: Order quantity
        
        Returns:
            Tuple of (is_valid, reason)
        """
        if not self.config_manager.validate_order_size(quantity):
            max_size = self.config_manager.max_order_size
            return False, f"Order size {quantity} exceeds limit {max_size}"
        
        return True, "Order size validated"
    
    def _validate_order_value(
        self,
        quantity: int,
        estimated_price: Decimal
    ) -> tuple[bool, str]:
        """Validate order value is within limits.
        
        Args:
            quantity: Order quantity
            estimated_price: Estimated execution price
        
        Returns:
            Tuple of (is_valid, reason)
        """
        estimated_value = Decimal(quantity) * estimated_price
        
        if not self.config_manager.validate_order_value(estimated_value):
            max_value = self.config_manager.max_order_value_usd
            return False, (
                f"Order value ${estimated_value:.2f} exceeds limit ${max_value:.2f}"
            )
        
        return True, "Order value validated"
    
    def get_validation_summary(self) -> dict:
        """Get summary of current validation configuration.
        
        Returns:
            Dictionary with validation configuration
        """
        config = self.config_manager.get_config()
        
        return {
            "live_enabled": config.enabled,
            "max_order_size": config.max_order_size,
            "max_order_value_usd": str(config.max_order_value_usd),
            "symbol_whitelist": sorted(config.symbol_whitelist),
            "require_safety_checks": config.require_safety_checks,
            "require_manual_approval": config.require_manual_approval,
        }


# Singleton instance
_order_validator: Optional[LiveOrderValidator] = None


def get_live_order_validator() -> LiveOrderValidator:
    """Get singleton live order validator.
    
    Returns:
        LiveOrderValidator instance
    """
    global _order_validator
    
    if _order_validator is None:
        _order_validator = LiveOrderValidator()
    
    return _order_validator


def validate_for_live_trading(
    intent: OrderIntent,
    estimated_price: Optional[Decimal] = None,
    skip_safety_checks: bool = False
) -> tuple[bool, str]:
    """Convenience function to validate order for live trading.
    
    Args:
        intent: OrderIntent to validate
        estimated_price: Estimated execution price
        skip_safety_checks: Skip safety checks (DANGEROUS - testing only)
    
    Returns:
        Tuple of (is_valid, reason)
    """
    validator = get_live_order_validator()
    return validator.validate_order_for_live(
        intent,
        estimated_price=estimated_price,
        skip_safety_checks=skip_safety_checks
    )
