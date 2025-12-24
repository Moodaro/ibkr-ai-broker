"""Tests for correlation ID middleware.

This module contains tests for the FastAPI middleware that injects
correlation IDs into requests and context.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from packages.audit_store.middleware import (
    CorrelationIdMiddleware,
    get_correlation_id,
    set_correlation_id,
)


@pytest.fixture
def app() -> FastAPI:
    """Create test FastAPI app with middleware."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/test")
    async def test_endpoint() -> dict:
        """Test endpoint that returns correlation ID."""
        return {"correlation_id": get_correlation_id()}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestCorrelationIdMiddleware:
    """Tests for CorrelationIdMiddleware."""

    def test_generates_correlation_id_when_not_provided(
        self, client: TestClient
    ) -> None:
        """Test middleware generates correlation ID when not provided."""
        response = client.get("/test")
        assert response.status_code == 200

        # Response should have correlation ID header
        assert "x-correlation-id" in response.headers
        correlation_id = response.headers["x-correlation-id"]

        # Should be valid UUID
        assert len(correlation_id) == 36  # UUID format
        assert correlation_id.count("-") == 4

        # Endpoint should receive same correlation ID
        assert response.json()["correlation_id"] == correlation_id

    def test_uses_provided_correlation_id(self, client: TestClient) -> None:
        """Test middleware uses correlation ID from header."""
        custom_id = "test-correlation-id-12345"
        response = client.get(
            "/test",
            headers={"X-Correlation-ID": custom_id}
        )
        assert response.status_code == 200

        # Response should have same correlation ID
        assert response.headers["x-correlation-id"] == custom_id

        # Endpoint should receive same correlation ID
        assert response.json()["correlation_id"] == custom_id

    def test_correlation_id_isolated_per_request(
        self, client: TestClient
    ) -> None:
        """Test correlation IDs are isolated between requests."""
        # Make first request
        response1 = client.get("/test")
        id1 = response1.headers["x-correlation-id"]

        # Make second request
        response2 = client.get("/test")
        id2 = response2.headers["x-correlation-id"]

        # IDs should be different
        assert id1 != id2


class TestCorrelationIdContext:
    """Tests for correlation ID context functions."""

    def test_set_and_get_correlation_id(self) -> None:
        """Test setting and getting correlation ID."""
        test_id = "test-correlation-id"
        set_correlation_id(test_id)
        assert get_correlation_id() == test_id

    def test_get_correlation_id_returns_empty_when_not_set(self) -> None:
        """Test get returns empty string when not set."""
        # Reset context
        set_correlation_id("")
        assert get_correlation_id() == ""
