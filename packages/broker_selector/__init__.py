"""
Broker adapter selection for paper vs live trading.

This module provides factory functions to select the appropriate
broker adapter based on live trading configuration and safety checks.
"""

from typing import Protocol

from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.live_config import get_live_config_manager
from packages.safety_checks import get_safety_checker
from packages.structured_logging import get_logger


logger = get_logger(__name__)


class BrokerAdapter(Protocol):
    """Protocol for broker adapters (paper and live)."""
    
    def get_account_id(self) -> str:
        """Get current account ID."""
        ...
    
    def submit_order(self, intent, token) -> str:
        """Submit order to broker."""
        ...


class BrokerSelectionError(Exception):
    """Raised when broker adapter selection fails."""
    pass


class BrokerAdapterFactory:
    """Factory for selecting appropriate broker adapter.
    
    Selects FakeBrokerAdapter for paper trading or real IBKR adapter
    for live trading based on configuration and safety checks.
    """
    
    def __init__(self):
        """Initialize broker adapter factory."""
        self._paper_adapter: FakeBrokerAdapter | None = None
        self._live_adapter: BrokerAdapter | None = None
    
    def get_adapter(
        self,
        force_paper: bool = False,
        skip_safety_checks: bool = False
    ) -> BrokerAdapter:
        """Get appropriate broker adapter based on configuration.
        
        Selection logic:
        1. If force_paper=True, always return paper adapter
        2. If live trading disabled, return paper adapter
        3. If live trading enabled and safety checks pass, return live adapter
        4. If safety checks fail, raise error (or return paper if skip_safety_checks)
        
        Args:
            force_paper: Force paper trading adapter regardless of config
            skip_safety_checks: Skip safety checks validation (DANGEROUS - testing only)
        
        Returns:
            BrokerAdapter (either FakeBrokerAdapter or real IBKR adapter)
        
        Raises:
            BrokerSelectionError: If live trading requested but unsafe
        """
        # Force paper trading (e.g., for testing)
        if force_paper:
            logger.info("broker_adapter_selection", mode="paper", reason="forced")
            return self._get_paper_adapter()
        
        # Check if live trading is enabled
        config_manager = get_live_config_manager()
        live_enabled = config_manager.is_live_enabled()
        
        if not live_enabled:
            logger.info(
                "broker_adapter_selection",
                mode="paper",
                reason="live_trading_disabled"
            )
            return self._get_paper_adapter()
        
        # Live trading enabled - run safety checks
        if not skip_safety_checks:
            safety_result = self._run_safety_checks()
            
            if not safety_result.ready_for_live:
                error_msg = (
                    f"Cannot enable live trading: {safety_result.blocking_issues}"
                )
                logger.error(
                    "broker_adapter_selection_failed",
                    mode="live",
                    reason="safety_checks_failed",
                    blocking_issues=safety_result.blocking_issues
                )
                raise BrokerSelectionError(error_msg)
        
        # Safety checks passed - return live adapter
        logger.info(
            "broker_adapter_selection",
            mode="live",
            safety_checks_passed=True
        )
        
        return self._get_live_adapter()
    
    def _get_paper_adapter(self) -> FakeBrokerAdapter:
        """Get or create paper trading adapter.
        
        Returns:
            FakeBrokerAdapter instance
        """
        if self._paper_adapter is None:
            self._paper_adapter = FakeBrokerAdapter()
            logger.info("paper_adapter_initialized")
        
        return self._paper_adapter
    
    def _get_live_adapter(self) -> BrokerAdapter:
        """Get or create live trading adapter.
        
        Returns:
            Real IBKR adapter instance
        
        Raises:
            BrokerSelectionError: If live adapter not available
        """
        if self._live_adapter is None:
            # TODO: Initialize real IBKR adapter
            # For now, raise error - live adapter not yet implemented
            error_msg = (
                "Live IBKR adapter not yet implemented. "
                "Use FakeBrokerAdapter for paper trading."
            )
            logger.error("live_adapter_not_implemented")
            raise BrokerSelectionError(error_msg)
        
        return self._live_adapter
    
    def _run_safety_checks(self):
        """Run safety checks to validate system readiness.
        
        Returns:
            SafetyCheckResult from safety checker
        """
        checker = get_safety_checker()
        result = checker.run_all_checks()
        
        logger.info(
            "safety_checks_executed",
            ready_for_live=result.ready_for_live,
            checks_passed=result.checks_passed,
            checks_total=result.checks_total,
            blocking_issues_count=len(result.blocking_issues)
        )
        
        return result
    
    def set_live_adapter(self, adapter: BrokerAdapter) -> None:
        """Set live trading adapter (for testing or custom implementations).
        
        Args:
            adapter: BrokerAdapter instance to use for live trading
        """
        self._live_adapter = adapter
        logger.info("live_adapter_set", adapter_type=type(adapter).__name__)
    
    def reset(self) -> None:
        """Reset adapters (for testing)."""
        self._paper_adapter = None
        self._live_adapter = None
        logger.info("broker_adapters_reset")


# Singleton instance
_broker_factory: BrokerAdapterFactory | None = None


def get_broker_factory() -> BrokerAdapterFactory:
    """Get singleton broker adapter factory.
    
    Returns:
        BrokerAdapterFactory instance
    """
    global _broker_factory
    
    if _broker_factory is None:
        _broker_factory = BrokerAdapterFactory()
    
    return _broker_factory


def get_broker_adapter(
    force_paper: bool = False,
    skip_safety_checks: bool = False
) -> BrokerAdapter:
    """Convenience function to get broker adapter.
    
    Args:
        force_paper: Force paper trading adapter
        skip_safety_checks: Skip safety checks (DANGEROUS - testing only)
    
    Returns:
        BrokerAdapter (paper or live based on configuration)
    
    Raises:
        BrokerSelectionError: If live trading requested but unsafe
    """
    factory = get_broker_factory()
    return factory.get_adapter(
        force_paper=force_paper,
        skip_safety_checks=skip_safety_checks
    )
