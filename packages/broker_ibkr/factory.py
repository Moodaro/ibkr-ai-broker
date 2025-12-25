"""
Broker factory for selecting adapter implementation.

Provides automatic selection between real IBKR adapter and fake adapter
based on configuration and availability.
"""

import structlog
from typing import Optional

from packages.broker_ibkr.adapter import BrokerAdapter
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.real import IBKRBrokerAdapter
from packages.ibkr_config import IBKRConfig, get_ibkr_config


logger = structlog.get_logger(__name__)


class BrokerType:
    """Broker type constants."""
    IBKR = "ibkr"
    FAKE = "fake"
    AUTO = "auto"


def create_broker_adapter(
    broker_type: str = "auto",
    config: Optional[IBKRConfig] = None,
    fallback_to_fake: bool = True,
) -> BrokerAdapter:
    """
    Create broker adapter instance.
    
    Args:
        broker_type: Type of broker ("ibkr", "fake", or "auto")
        config: IBKR configuration (uses global if None)
        fallback_to_fake: If True, fall back to Fake adapter on connection error
    
    Returns:
        BrokerAdapter instance
    
    Raises:
        ValueError: If broker_type is invalid
        ConnectionError: If IBKR connection fails and fallback disabled
    """
    if broker_type == BrokerType.FAKE:
        logger.info("broker_selected", type="fake", reason="explicit")
        return FakeBrokerAdapter()
    
    if broker_type == BrokerType.IBKR:
        logger.info("broker_selected", type="ibkr", reason="explicit")
        return _create_ibkr_adapter(config, fallback_to_fake=False)
    
    if broker_type == BrokerType.AUTO:
        # Try IBKR first, fallback to Fake if needed
        return _create_ibkr_adapter(config, fallback_to_fake=fallback_to_fake)
    
    raise ValueError(f"Invalid broker_type: {broker_type}. Use 'ibkr', 'fake', or 'auto'")


def _create_ibkr_adapter(
    config: Optional[IBKRConfig] = None,
    fallback_to_fake: bool = True,
) -> BrokerAdapter:
    """
    Create IBKR adapter with optional fallback.
    
    Args:
        config: IBKR configuration
        fallback_to_fake: If True, return Fake adapter on connection error
    
    Returns:
        BrokerAdapter instance (IBKR or Fake)
    
    Raises:
        ConnectionError: If IBKR connection fails and fallback disabled
    """
    config = config or get_ibkr_config()
    
    try:
        adapter = IBKRBrokerAdapter(config=config)
        adapter.connect()
        
        if adapter.is_connected():
            logger.info(
                "broker_selected",
                type="ibkr",
                reason="auto",
                host=config.host,
                port=config.port,
                mode=config.mode
            )
            return adapter
        
        raise ConnectionError("Failed to connect to IBKR")
    
    except Exception as e:
        logger.warning(
            "ibkr_connection_failed",
            error=str(e),
            fallback_enabled=fallback_to_fake
        )
        
        if not fallback_to_fake:
            raise ConnectionError(f"IBKR connection failed: {e}")
        
        logger.info("broker_selected", type="fake", reason="fallback")
        return FakeBrokerAdapter()


def get_broker_adapter(
    broker_type: Optional[str] = None,
    config: Optional[IBKRConfig] = None,
) -> BrokerAdapter:
    """
    Get broker adapter with environment variable support.
    
    Checks BROKER_TYPE environment variable if broker_type not provided.
    
    Args:
        broker_type: Type of broker ("ibkr", "fake", or "auto")
        config: IBKR configuration
    
    Returns:
        BrokerAdapter instance
    """
    import os
    
    # Use provided type or check environment variable
    if broker_type is None:
        broker_type = os.getenv("BROKER_TYPE", "auto")
    
    return create_broker_adapter(
        broker_type=broker_type,
        config=config,
        fallback_to_fake=True,
    )
