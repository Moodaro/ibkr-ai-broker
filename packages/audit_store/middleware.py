"""Correlation ID middleware for FastAPI.

This module provides middleware to inject correlation IDs into requests,
enabling distributed tracing and audit logging.
"""

import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable to store correlation ID for current request
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get current request correlation ID.

    Returns:
        Current correlation ID or empty string if not set.
    """
    return correlation_id_ctx.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID for current request.

    Args:
        correlation_id: Correlation ID to set.
    """
    correlation_id_ctx.set(correlation_id)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to inject correlation ID into requests.

    Checks for X-Correlation-ID header and injects into context.
    If header is not present, generates a new UUID.
    Adds X-Correlation-ID header to response.
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        """Process request and inject correlation ID.

        Args:
            request: Incoming request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response with X-Correlation-ID header.
        """
        # Get or generate correlation ID
        correlation_id = request.headers.get(
            "x-correlation-id",
            str(uuid.uuid4())
        )

        # Set in context for current request
        set_correlation_id(correlation_id)

        # Process request
        response = await call_next(request)

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id

        return response
