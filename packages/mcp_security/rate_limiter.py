"""Rate limiter for MCP tool calls.

Prevents abuse and DoS attacks by limiting:
- Tool calls per session
- Tool calls per tool per session  
- Global rate across all sessions
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

from packages.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    
    # Per-tool limits (calls per window)
    tool_calls_per_minute: int = 60
    tool_calls_per_hour: int = 500
    
    # Per-session limits
    session_calls_per_minute: int = 100
    session_calls_per_hour: int = 1000
    
    # Global limits (all sessions)
    global_calls_per_minute: int = 1000
    global_calls_per_hour: int = 10000
    
    # Circuit breaker
    enable_circuit_breaker: bool = True
    circuit_breaker_threshold: int = 100  # consecutive rejections
    circuit_breaker_timeout: int = 300  # seconds


@dataclass
class RateLimitState:
    """Tracks rate limit state for a key."""
    
    calls_minute: list[float] = field(default_factory=list)
    calls_hour: list[float] = field(default_factory=list)
    consecutive_rejections: int = 0
    circuit_breaker_until: Optional[float] = None


class RateLimiter:
    """Rate limiter with per-tool, per-session, and global limits."""
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        """Initialize rate limiter.
        
        Args:
            config: Rate limit configuration (uses defaults if None)
        """
        self.config = config or RateLimitConfig()
        
        # State tracking: key -> RateLimitState
        # Keys: "tool:{tool_name}", "session:{session_id}", "global"
        self._state: Dict[str, RateLimitState] = defaultdict(RateLimitState)
        
        logger.info("rate_limiter_initialized",
                   tool_limit_minute=self.config.tool_calls_per_minute,
                   session_limit_minute=self.config.session_calls_per_minute,
                   circuit_breaker=self.config.enable_circuit_breaker)
    
    def check_rate_limit(
        self,
        tool_name: str,
        session_id: str,
    ) -> tuple[bool, Optional[str]]:
        """Check if request is allowed under rate limits.
        
        Args:
            tool_name: Name of the tool being called
            session_id: Session identifier
        
        Returns:
            Tuple of (allowed: bool, reason: Optional[str])
            If not allowed, reason explains which limit was exceeded
        """
        now = time.time()
        
        # Check circuit breaker
        if self.config.enable_circuit_breaker:
            for key in [f"tool:{tool_name}", f"session:{session_id}", "global"]:
                state = self._state[key]
                if state.circuit_breaker_until and now < state.circuit_breaker_until:
                    remaining = int(state.circuit_breaker_until - now)
                    logger.warning("rate_limit_circuit_breaker_active",
                                 key=key,
                                 remaining_seconds=remaining)
                    return False, f"Circuit breaker active for {key} ({remaining}s remaining)"
        
        # Clean old entries and check limits
        checks = [
            (f"tool:{tool_name}", self.config.tool_calls_per_minute, self.config.tool_calls_per_hour),
            (f"session:{session_id}", self.config.session_calls_per_minute, self.config.session_calls_per_hour),
            ("global", self.config.global_calls_per_minute, self.config.global_calls_per_hour),
        ]
        
        for key, limit_minute, limit_hour in checks:
            state = self._state[key]
            
            # Clean old entries
            state.calls_minute = [t for t in state.calls_minute if now - t < 60]
            state.calls_hour = [t for t in state.calls_hour if now - t < 3600]
            
            # Check minute limit
            if len(state.calls_minute) >= limit_minute:
                self._handle_rejection(key, state)
                logger.warning("rate_limit_exceeded",
                             key=key,
                             limit="per_minute",
                             count=len(state.calls_minute),
                             max=limit_minute)
                return False, f"Rate limit exceeded for {key}: {len(state.calls_minute)}/{limit_minute} per minute"
            
            # Check hour limit
            if len(state.calls_hour) >= limit_hour:
                self._handle_rejection(key, state)
                logger.warning("rate_limit_exceeded",
                             key=key,
                             limit="per_hour",
                             count=len(state.calls_hour),
                             max=limit_hour)
                return False, f"Rate limit exceeded for {key}: {len(state.calls_hour)}/{limit_hour} per hour"
        
        # All checks passed - record call
        for key, _, _ in checks:
            state = self._state[key]
            state.calls_minute.append(now)
            state.calls_hour.append(now)
            state.consecutive_rejections = 0  # Reset on success
        
        return True, None
    
    def _handle_rejection(self, key: str, state: RateLimitState) -> None:
        """Handle rate limit rejection and possibly activate circuit breaker."""
        state.consecutive_rejections += 1
        
        if (self.config.enable_circuit_breaker and 
            state.consecutive_rejections >= self.config.circuit_breaker_threshold):
            
            state.circuit_breaker_until = time.time() + self.config.circuit_breaker_timeout
            
            logger.error("rate_limit_circuit_breaker_activated",
                        key=key,
                        consecutive_rejections=state.consecutive_rejections,
                        timeout_seconds=self.config.circuit_breaker_timeout)
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        now = time.time()
        stats = {}
        
        for key, state in self._state.items():
            # Clean old entries for accurate counts
            calls_minute = [t for t in state.calls_minute if now - t < 60]
            calls_hour = [t for t in state.calls_hour if now - t < 3600]
            
            stats[key] = {
                "calls_last_minute": len(calls_minute),
                "calls_last_hour": len(calls_hour),
                "consecutive_rejections": state.consecutive_rejections,
                "circuit_breaker_active": (
                    state.circuit_breaker_until is not None and 
                    now < state.circuit_breaker_until
                ),
            }
        
        return stats
    
    def reset(self, key: Optional[str] = None) -> None:
        """Reset rate limiter state.
        
        Args:
            key: Specific key to reset (resets all if None)
        """
        if key:
            if key in self._state:
                del self._state[key]
                logger.info("rate_limiter_reset", key=key)
        else:
            self._state.clear()
            logger.info("rate_limiter_reset_all")


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(config)
    return _rate_limiter
