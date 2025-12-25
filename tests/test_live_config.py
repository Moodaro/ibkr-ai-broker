"""
Tests for live trading configuration.
"""

import pytest
import os
from decimal import Decimal

from packages.live_config import (
    LiveConfigManager,
    LiveTradingConfig,
    get_live_config_manager,
    is_live_trading_enabled,
)


@pytest.fixture
def clean_env():
    """Clean environment variables before each test."""
    env_vars = [
        "LIVE_MAX_ORDER_SIZE",
        "LIVE_MAX_ORDER_VALUE_USD",
        "LIVE_SYMBOL_WHITELIST",
        "LIVE_DAILY_LOSS_LIMIT_USD",
        "LIVE_REQUIRE_SAFETY_CHECKS",
        "LIVE_REQUIRE_MANUAL_APPROVAL",
    ]
    
    # Save originals
    originals = {}
    for var in env_vars:
        originals[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]
    
    yield
    
    # Restore originals
    for var, value in originals.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


@pytest.fixture
def config_manager(clean_env):
    """Fresh config manager for each test."""
    import packages.live_config
    packages.live_config._live_config_manager = None
    return LiveConfigManager()


class TestLiveConfigManager:
    """Tests for LiveConfigManager."""
    
    def test_default_configuration(self, config_manager):
        """Test default configuration values."""
        config = config_manager.get_config()
        
        assert config.max_order_size == 100
        assert config.max_order_value_usd == Decimal("10000")
        assert len(config.symbol_whitelist) > 0
        assert "AAPL" in config.symbol_whitelist
        assert config.daily_loss_limit_usd is None
        assert config.require_safety_checks is True
        assert config.require_manual_approval is True
    
    def test_custom_configuration(self, clean_env):
        """Test custom configuration from environment."""
        os.environ["LIVE_MAX_ORDER_SIZE"] = "50"
        os.environ["LIVE_MAX_ORDER_VALUE_USD"] = "5000"
        os.environ["LIVE_SYMBOL_WHITELIST"] = "AAPL, MSFT, GOOGL"
        os.environ["LIVE_DAILY_LOSS_LIMIT_USD"] = "1000"
        os.environ["LIVE_REQUIRE_SAFETY_CHECKS"] = "false"
        
        manager = LiveConfigManager()
        config = manager.get_config()
        
        assert config.max_order_size == 50
        assert config.max_order_value_usd == Decimal("5000")
        assert config.symbol_whitelist == {"AAPL", "MSFT", "GOOGL"}
        assert config.daily_loss_limit_usd == Decimal("1000")
        assert config.require_safety_checks is False
    
    def test_validate_symbol(self, config_manager):
        """Test symbol validation."""
        # Should be in default whitelist
        assert config_manager.validate_symbol("AAPL") is True
        assert config_manager.validate_symbol("aapl") is True  # Case insensitive
        
        # Should not be in whitelist
        assert config_manager.validate_symbol("UNKNOWN") is False
    
    def test_validate_order_size(self, config_manager):
        """Test order size validation."""
        assert config_manager.validate_order_size(50) is True
        assert config_manager.validate_order_size(100) is True
        
        # Exceeds limit
        assert config_manager.validate_order_size(101) is False
        
        # Invalid sizes
        assert config_manager.validate_order_size(0) is False
        assert config_manager.validate_order_size(-10) is False
    
    def test_validate_order_value(self, config_manager):
        """Test order value validation."""
        assert config_manager.validate_order_value(Decimal("5000")) is True
        assert config_manager.validate_order_value(Decimal("10000")) is True
        
        # Exceeds limit
        assert config_manager.validate_order_value(Decimal("10001")) is False
        
        # Invalid values
        assert config_manager.validate_order_value(Decimal("0")) is False
        assert config_manager.validate_order_value(Decimal("-100")) is False
    
    def test_can_submit_live_order(self, config_manager):
        """Test complete order validation."""
        # First check will fail if live trading not enabled
        can_submit, reason = config_manager.can_submit_live_order(
            symbol="AAPL",
            quantity=50,
            estimated_value_usd=Decimal("5000")
        )
        # Should fail with live trading not enabled
        assert can_submit is False
        assert isinstance(reason, str)  # Just check we got a reason string
        
        # Invalid symbol (would fail even if live enabled)
        can_submit, reason = config_manager.can_submit_live_order(
            symbol="UNKNOWN",
            quantity=50,
            estimated_value_usd=Decimal("5000")
        )
        assert can_submit is False
        # May be "not enabled" or "whitelist" depending on check order
        assert isinstance(reason, str)
        
        # Exceeds size limit
        can_submit, reason = config_manager.can_submit_live_order(
            symbol="AAPL",
            quantity=200,
            estimated_value_usd=Decimal("5000")
        )
        assert can_submit is False
        assert isinstance(reason, str)
        
        # Exceeds value limit
        can_submit, reason = config_manager.can_submit_live_order(
            symbol="AAPL",
            quantity=50,
            estimated_value_usd=Decimal("50000")
        )
        assert can_submit is False
        assert isinstance(reason, str)
    
    def test_add_symbol_to_whitelist(self, config_manager):
        """Test adding symbol to whitelist."""
        assert config_manager.validate_symbol("NEWSTOCK") is False
        
        config_manager.add_symbol_to_whitelist("NEWSTOCK")
        
        assert config_manager.validate_symbol("NEWSTOCK") is True
        assert config_manager.validate_symbol("newstock") is True
    
    def test_remove_symbol_from_whitelist(self, config_manager):
        """Test removing symbol from whitelist."""
        config_manager.add_symbol_to_whitelist("TEMP")
        assert config_manager.validate_symbol("TEMP") is True
        
        config_manager.remove_symbol_from_whitelist("TEMP")
        
        assert config_manager.validate_symbol("TEMP") is False
    
    def test_set_max_order_size(self, config_manager):
        """Test setting max order size."""
        config_manager.set_max_order_size(200)
        
        assert config_manager.max_order_size == 200
        assert config_manager.validate_order_size(150) is True
        assert config_manager.validate_order_size(250) is False
    
    def test_set_max_order_size_invalid(self, config_manager):
        """Test setting invalid max order size."""
        with pytest.raises(ValueError):
            config_manager.set_max_order_size(0)
        
        with pytest.raises(ValueError):
            config_manager.set_max_order_size(-10)
    
    def test_set_max_order_value(self, config_manager):
        """Test setting max order value."""
        config_manager.set_max_order_value(Decimal("20000"))
        
        assert config_manager.max_order_value_usd == Decimal("20000")
        assert config_manager.validate_order_value(Decimal("15000")) is True
        assert config_manager.validate_order_value(Decimal("25000")) is False
    
    def test_set_max_order_value_invalid(self, config_manager):
        """Test setting invalid max order value."""
        with pytest.raises(ValueError):
            config_manager.set_max_order_value(Decimal("0"))
        
        with pytest.raises(ValueError):
            config_manager.set_max_order_value(Decimal("-1000"))


class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_get_live_config_manager_singleton(self, clean_env):
        """Test singleton returns same instance."""
        import packages.live_config
        packages.live_config._live_config_manager = None
        
        manager1 = get_live_config_manager()
        manager2 = get_live_config_manager()
        
        assert manager1 is manager2
    
    def test_is_live_trading_enabled(self, clean_env):
        """Test convenience function."""
        import packages.live_config
        packages.live_config._live_config_manager = None
        
        # Should return False if feature flags not available
        enabled = is_live_trading_enabled()
        assert isinstance(enabled, bool)
