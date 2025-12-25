"""
Tests for broker factory.
"""

import pytest
import os
from unittest.mock import patch

from packages.broker_ibkr.factory import (
    create_broker_adapter,
    get_broker_adapter,
    BrokerType,
)
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.real import IBKRBrokerAdapter
from packages.ibkr_config import IBKRConfig


def test_create_fake_adapter():
    """Test creating fake adapter explicitly."""
    adapter = create_broker_adapter(broker_type=BrokerType.FAKE)
    
    assert isinstance(adapter, FakeBrokerAdapter)


def test_create_ibkr_adapter_with_fallback():
    """Test creating IBKR adapter with fallback to fake."""
    # This will likely fail to connect and fall back to Fake
    # (unless IBKR Gateway is running)
    adapter = create_broker_adapter(
        broker_type=BrokerType.AUTO,
        fallback_to_fake=True
    )
    
    # Should get either IBKR or Fake (depends on Gateway availability)
    assert isinstance(adapter, (IBKRBrokerAdapter, FakeBrokerAdapter))


def test_create_ibkr_adapter_no_fallback():
    """Test creating IBKR adapter without fallback."""
    config = IBKRConfig(
        host="127.0.0.1",
        port=9999,  # Invalid port to force failure
        client_id=1,
        mode="paper"
    )
    
    # Should raise ConnectionError if Gateway not running
    with pytest.raises(ConnectionError, match="IBKR connection failed"):
        create_broker_adapter(
            broker_type=BrokerType.IBKR,
            config=config,
            fallback_to_fake=False
        )


def test_invalid_broker_type():
    """Test invalid broker type."""
    with pytest.raises(ValueError, match="Invalid broker_type"):
        create_broker_adapter(broker_type="invalid")


def test_get_broker_adapter_default():
    """Test get_broker_adapter with defaults."""
    adapter = get_broker_adapter()
    
    # Should return some adapter
    assert adapter is not None
    assert isinstance(adapter, (IBKRBrokerAdapter, FakeBrokerAdapter))


def test_get_broker_adapter_explicit_fake():
    """Test get_broker_adapter with explicit fake."""
    adapter = get_broker_adapter(broker_type=BrokerType.FAKE)
    
    assert isinstance(adapter, FakeBrokerAdapter)


def test_get_broker_adapter_env_variable():
    """Test get_broker_adapter respects BROKER_TYPE env var."""
    with patch.dict(os.environ, {"BROKER_TYPE": "fake"}):
        adapter = get_broker_adapter()
        assert isinstance(adapter, FakeBrokerAdapter)


def test_broker_type_constants():
    """Test broker type constants."""
    assert BrokerType.IBKR == "ibkr"
    assert BrokerType.FAKE == "fake"
    assert BrokerType.AUTO == "auto"
