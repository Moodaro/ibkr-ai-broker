"""Structured logging module with JSON output and correlation ID support.

This module provides a centralized logging configuration using structlog for
structured JSON logging with automatic correlation ID injection.
"""

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from packages.audit_store import get_correlation_id


def add_correlation_id(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add correlation ID to log entries if available.
    
    Args:
        logger: The wrapped logger instance
        method_name: The name of the method being called
        event_dict: The event dictionary to modify
        
    Returns:
        Modified event dictionary with correlation_id if available
    """
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_output: bool = True,
) -> None:
    """Configure structured logging for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output (in addition to console)
        json_output: If True, output JSON format; if False, use human-readable format
    """
    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure Python's logging module
    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
        stream=sys.stdout,
    )
    
    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        add_correlation_id,  # Add correlation ID from context
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    
    # Add appropriate renderer based on json_output
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Setup file handler if log_file specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(numeric_level)
        
        # Use JSON format for file output
        file_handler.setFormatter(
            logging.Formatter("%(message)s")
        )
        
        # Add to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name (typically __name__ of the module)
        
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


# Convenience functions for backward compatibility
def setup_dev_logging() -> None:
    """Setup logging for development (human-readable output)."""
    setup_logging(level="DEBUG", json_output=False)


def setup_prod_logging(log_file: str = "logs/app.log") -> None:
    """Setup logging for production (JSON output with file)."""
    setup_logging(level="INFO", log_file=log_file, json_output=True)


__all__ = [
    "setup_logging",
    "get_logger",
    "setup_dev_logging",
    "setup_prod_logging",
]
