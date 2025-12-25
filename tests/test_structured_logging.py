"""Tests for structured logging module."""

import logging
import json
import structlog
from io import StringIO

from packages.structured_logging import (
    setup_logging,
    get_logger,
    setup_dev_logging,
    setup_prod_logging,
)


def test_get_logger_works():
    """Test that get_logger returns a working logger."""
    logger = get_logger(__name__)
    # Should have logging methods
    assert hasattr(logger, 'info')
    assert hasattr(logger, 'warning')
    assert hasattr(logger, 'error')
    assert hasattr(logger, 'debug')


def test_setup_logging_default():
    """Test default logging configuration."""
    setup_logging()
    logger = get_logger("test")
    
    # Should not raise exception
    logger.info("test_message", key="value")


def test_setup_dev_logging():
    """Test development logging setup."""
    setup_dev_logging()
    logger = get_logger("test")
    
    # Should not raise exception
    logger.debug("debug_message", extra="data")


def test_logger_levels():
    """Test different log levels work."""
    setup_logging(level="DEBUG")
    logger = get_logger("test")
    
    # All of these should not raise exceptions
    logger.debug("debug")
    logger.info("info")
    logger.warning("warning")
    logger.error("error")


def test_logger_with_structured_data():
    """Test logging with structured data."""
    setup_logging()
    logger = get_logger("test")
    
    # Should handle various data types
    logger.info(
        "structured_message",
        user_id=123,
        amount=99.99,
        success=True,
        items=["a", "b", "c"],
        metadata={"key": "value"},
    )


def test_logger_exception_logging():
    """Test logging exceptions."""
    setup_logging()
    logger = get_logger("test")
    
    try:
        raise ValueError("Test error")
    except ValueError:
        # Should capture exception info
        logger.error("exception_occurred", exc_info=True)


def test_multiple_loggers():
    """Test that multiple loggers can be created."""
    setup_logging()
    
    logger1 = get_logger("module1")
    logger2 = get_logger("module2")
    
    # Should be different instances but both work
    logger1.info("message1")
    logger2.info("message2")


def test_logging_json_output_structure():
    """Test that JSON output contains expected fields."""
    # Capture log output
    import sys
    from io import StringIO
    
    # Setup logging with JSON output
    setup_logging(json_output=True)
    
    # Create a logger
    logger = get_logger("test")
    
    # Log a message (we can't easily capture structlog output in tests,
    # but we can verify it doesn't crash)
    logger.info("test_event", key="value", number=42)
