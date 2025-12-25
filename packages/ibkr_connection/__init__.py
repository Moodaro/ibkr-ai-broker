"""
IBKR Connection Manager.

Manages connection lifecycle to Interactive Brokers Gateway/TWS with:
- Automatic connection/reconnection with exponential backoff
- Circuit breaker pattern for fault tolerance
- Health checks and connection status monitoring
- Thread-safe operations
"""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import structlog
from ib_insync import IB, util
from packages.ibkr_config import IBKRConfig, get_ibkr_config


logger = structlog.get_logger(__name__)


class ConnectionState(str, Enum):
    """Connection state enumeration."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"


class CircuitBreaker:
    """
    Circuit breaker for connection failures.
    
    States:
    - CLOSED: Normal operation, requests allowed
    - OPEN: Too many failures, requests blocked
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            success_threshold: Successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "CLOSED"
    
    def record_success(self):
        """Record successful operation."""
        self.failure_count = 0
        
        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._close()
    
    def record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.success_count = 0
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self._open()
    
    def can_attempt(self) -> bool:
        """Check if operation attempt is allowed."""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self._half_open()
                return True
            return False
        
        # HALF_OPEN
        return True
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        
        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout
    
    def _close(self):
        """Close circuit (normal operation)."""
        self.state = "CLOSED"
        self.failure_count = 0
        self.success_count = 0
        logger.info("circuit_breaker_closed")
    
    def _open(self):
        """Open circuit (block requests)."""
        self.state = "OPEN"
        logger.warning("circuit_breaker_opened", failure_count=self.failure_count)
    
    def _half_open(self):
        """Half-open circuit (testing recovery)."""
        self.state = "HALF_OPEN"
        self.success_count = 0
        logger.info("circuit_breaker_half_open")
    
    def reset(self):
        """Reset circuit breaker to initial state."""
        self.state = "CLOSED"
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None


class ConnectionManager:
    """
    Manages IBKR connection lifecycle with resilience patterns.
    
    Features:
    - Automatic reconnection with exponential backoff
    - Circuit breaker for fault tolerance
    - Connection health monitoring
    - Thread-safe operations
    """
    
    def __init__(self, config: Optional[IBKRConfig] = None):
        """
        Initialize connection manager.
        
        Args:
            config: IBKR configuration (uses global if None)
        """
        self.config = config or get_ibkr_config()
        self.ib = IB()
        self.state = ConnectionState.DISCONNECTED
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=2
        )
        
        self.retry_count = 0
        self.last_connect_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        
        # Setup event handlers
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error
    
    async def connect(self) -> bool:
        """
        Connect to IBKR Gateway/TWS.
        
        Returns:
            True if connected successfully
        
        Raises:
            ConnectionError: If connection fails after retries
        """
        if self.is_connected():
            logger.info("already_connected")
            return True
        
        if not self.circuit_breaker.can_attempt():
            raise ConnectionError("Circuit breaker OPEN - too many connection failures")
        
        self.state = ConnectionState.CONNECTING
        logger.info(
            "connecting_to_ibkr",
            host=self.config.host,
            port=self.config.port,
            client_id=self.config.client_id,
            mode=self.config.mode
        )
        
        try:
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.connect_timeout,
                readonly=self.config.readonly_mode
            )
            
            self.state = ConnectionState.CONNECTED
            self.last_connect_time = datetime.utcnow()
            self.retry_count = 0
            self.circuit_breaker.record_success()
            
            logger.info(
                "connected_to_ibkr",
                connection_string=self.config.get_connection_string(),
                server_version=self.ib.serverVersion() if hasattr(self.ib, 'serverVersion') else None
            )
            
            return True
        
        except Exception as e:
            self.state = ConnectionState.FAILED
            self.last_error = str(e)
            self.circuit_breaker.record_failure()
            
            logger.error(
                "connection_failed",
                error=str(e),
                host=self.config.host,
                port=self.config.port,
                retry_count=self.retry_count
            )
            
            if self.config.reconnect_enabled and self.retry_count < self.config.reconnect_max_retries:
                return await self._retry_connect()
            
            raise ConnectionError(f"Failed to connect to IBKR: {e}")
    
    async def _retry_connect(self) -> bool:
        """Retry connection with exponential backoff."""
        self.retry_count += 1
        delay = self.config.reconnect_delay_base ** self.retry_count
        
        logger.info(
            "retrying_connection",
            retry=self.retry_count,
            max_retries=self.config.reconnect_max_retries,
            delay_seconds=delay
        )
        
        await asyncio.sleep(delay)
        return await self.connect()
    
    async def disconnect(self):
        """Disconnect from IBKR."""
        if not self.is_connected():
            return
        
        logger.info("disconnecting_from_ibkr")
        self.ib.disconnect()
        self.state = ConnectionState.DISCONNECTED
    
    async def reconnect(self) -> bool:
        """
        Force reconnection.
        
        Returns:
            True if reconnected successfully
        """
        logger.info("forcing_reconnect")
        await self.disconnect()
        self.retry_count = 0
        return await self.connect()
    
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self.ib.isConnected() and self.state == ConnectionState.CONNECTED
    
    def get_status(self) -> dict:
        """
        Get connection status details.
        
        Returns:
            Status dictionary with connection info
        """
        return {
            "state": self.state.value,
            "connected": self.is_connected(),
            "config": self.config.get_connection_string(),
            "retry_count": self.retry_count,
            "last_connect_time": self.last_connect_time.isoformat() if self.last_connect_time else None,
            "last_error": self.last_error,
            "circuit_breaker_state": self.circuit_breaker.state,
            "circuit_breaker_failures": self.circuit_breaker.failure_count,
            "readonly_mode": self.config.readonly_mode
        }
    
    async def health_check(self) -> dict:
        """
        Perform health check.
        
        Returns:
            Health check result with latency metrics
        """
        if not self.is_connected():
            return {
                "healthy": False,
                "connected": False,
                "error": "Not connected to IBKR"
            }
        
        try:
            # Test connection with simple request
            start_time = time.time()
            await self.ib.reqCurrentTimeAsync()
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                "healthy": True,
                "connected": True,
                "latency_ms": round(latency_ms, 2),
                "server_time": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return {
                "healthy": False,
                "connected": self.is_connected(),
                "error": str(e)
            }
    
    @asynccontextmanager
    async def ensure_connected(self):
        """
        Context manager ensuring connection is active.
        
        Usage:
            async with conn_manager.ensure_connected():
                # Do operations requiring connection
                pass
        """
        if not self.is_connected():
            await self.connect()
        
        try:
            yield self.ib
        except Exception as e:
            logger.error("operation_failed_in_connected_context", error=str(e))
            raise
    
    def _on_connected(self):
        """Handle connected event."""
        logger.info("ibkr_connected_event")
    
    def _on_disconnected(self):
        """Handle disconnected event."""
        logger.warning("ibkr_disconnected_event")
        self.state = ConnectionState.DISCONNECTED
    
    def _on_error(self, reqId, errorCode, errorString, contract):
        """Handle error event."""
        logger.error(
            "ibkr_error_event",
            req_id=reqId,
            error_code=errorCode,
            error_string=errorString,
            contract=str(contract) if contract else None
        )
        self.last_error = f"[{errorCode}] {errorString}"


# Global connection manager instance
_connection_manager_instance: Optional[ConnectionManager] = None


def get_connection_manager(config: Optional[IBKRConfig] = None) -> ConnectionManager:
    """
    Get global connection manager singleton.
    
    Args:
        config: IBKR configuration (uses global if None)
    
    Returns:
        ConnectionManager instance
    """
    global _connection_manager_instance
    
    if _connection_manager_instance is None:
        _connection_manager_instance = ConnectionManager(config)
    
    return _connection_manager_instance


def reset_connection_manager():
    """Reset global connection manager (for testing)."""
    global _connection_manager_instance
    if _connection_manager_instance:
        asyncio.run(_connection_manager_instance.disconnect())
    _connection_manager_instance = None
