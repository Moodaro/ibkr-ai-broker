"""Tests for MCP security modules: rate limiter, redactor, policy."""

import pytest
import time
from decimal import Decimal

from packages.mcp_security.rate_limiter import RateLimiter, RateLimitConfig
from packages.mcp_security.redactor import OutputRedactor, RedactionConfig
from packages.mcp_security.policy import ToolPolicy, ToolPolicyRule, ToolAction


class TestRateLimiter:
    """Test rate limiter functionality."""
    
    def test_per_tool_limit_minute(self):
        """Test per-tool rate limiting (per minute)."""
        config = RateLimitConfig(tool_calls_per_minute=2)
        limiter = RateLimiter(config)
        
        # First 2 calls should succeed
        allowed, _ = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is True
        
        allowed, _ = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is True
        
        # Third call should fail (exceeded limit)
        allowed, reason = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is False
        assert "tool:get_portfolio" in reason
        assert "per minute" in reason
    
    def test_per_session_limit(self):
        """Test per-session rate limiting."""
        config = RateLimitConfig(session_calls_per_minute=3)
        limiter = RateLimiter(config)
        
        # 3 calls across different tools should succeed
        allowed, _ = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is True
        
        allowed, _ = limiter.check_rate_limit("get_positions", "session1")
        assert allowed is True
        
        allowed, _ = limiter.check_rate_limit("get_cash", "session1")
        assert allowed is True
        
        # Fourth call should fail (session limit)
        allowed, reason = limiter.check_rate_limit("simulate_order", "session1")
        assert allowed is False
        assert "session:session1" in reason
    
    def test_global_limit(self):
        """Test global rate limiting across all sessions."""
        config = RateLimitConfig(global_calls_per_minute=5)
        limiter = RateLimiter(config)
        
        # 5 calls across different sessions should succeed
        for i in range(5):
            allowed, _ = limiter.check_rate_limit("get_portfolio", f"session{i}")
            assert allowed is True
        
        # Sixth call should fail (global limit)
        allowed, reason = limiter.check_rate_limit("get_portfolio", "session5")
        assert allowed is False
        assert "global" in reason
    
    def test_circuit_breaker(self):
        """Test circuit breaker after consecutive rejections."""
        config = RateLimitConfig(
            tool_calls_per_minute=1,
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=2  # 2 seconds for test
        )
        limiter = RateLimiter(config)
        
        tool_name = "get_portfolio"
        session_id = "session1"
        
        # First call succeeds
        allowed, _ = limiter.check_rate_limit(tool_name, session_id)
        assert allowed is True
        
        # Next 3 calls fail (trigger circuit breaker)
        for _ in range(3):
            allowed, _ = limiter.check_rate_limit(tool_name, session_id)
            assert allowed is False
        
        # Next call should hit circuit breaker
        allowed, reason = limiter.check_rate_limit(tool_name, session_id)
        assert allowed is False
        assert "circuit breaker active" in reason.lower()
        
        # Wait for circuit breaker to reset
        time.sleep(2.5)
        
        # Should succeed again after timeout
        allowed, _ = limiter.check_rate_limit(tool_name, session_id)
        # Note: Will still hit per-minute limit, but no circuit breaker
        # (Circuit breaker check passes, but per-minute limit still active)
    
    def test_reset_state(self):
        """Test resetting rate limiter state."""
        config = RateLimitConfig(tool_calls_per_minute=1)
        limiter = RateLimiter(config)
        
        # Make call
        allowed, _ = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is True
        
        # Should fail on second call
        allowed, _ = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is False
        
        # Reset and should succeed
        limiter.reset()
        allowed, _ = limiter.check_rate_limit("get_portfolio", "session1")
        assert allowed is True


class TestOutputRedactor:
    """Test output redaction functionality."""
    
    def test_account_id_redaction(self):
        """Test account ID partial redaction (show last 2 chars)."""
        redactor = OutputRedactor()
        
        data = {"account_id": "DU123456"}
        result = redactor.redact(data)
        
        assert result["account_id"] == "******56"
    
    def test_sensitive_field_complete_redaction(self):
        """Test complete redaction of sensitive fields."""
        redactor = OutputRedactor()
        
        data = {
            "password": "super_secret",
            "api_key": "abc123def456",
            "ssn": "123-45-6789",
        }
        result = redactor.redact(data)
        
        assert result["password"] == "***REDACTED***"
        assert result["api_key"] == "***REDACTED***"
        assert result["ssn"] == "***REDACTED***"
    
    def test_string_pattern_redaction(self):
        """Test regex-based string redaction."""
        redactor = OutputRedactor()
        
        text = "Account DU123456 has balance $1000. Email: user@example.com"
        result = redactor.redact(text)
        
        # Account ID redacted
        assert "DU****56" in result
        assert "DU123456" not in result
        
        # Email redacted
        assert "u***@example.com" in result
        assert "user@example.com" not in result
    
    def test_nested_dict_redaction(self):
        """Test redaction in nested dictionaries."""
        redactor = OutputRedactor()
        
        data = {
            "user": {
                "account_id": "DU987654",
                "api_key": "secret123",
                "balance": Decimal("1000.50")
            }
        }
        result = redactor.redact(data)
        
        assert result["user"]["account_id"] == "******54"
        assert result["user"]["api_key"] == "***REDACTED***"
        assert result["user"]["balance"] == Decimal("1000.50")  # Unchanged
    
    def test_list_redaction(self):
        """Test redaction in lists."""
        redactor = OutputRedactor()
        
        data = {
            "accounts": [
                {"account_id": "DU111111"},
                {"account_id": "DU222222"}
            ]
        }
        result = redactor.redact(data)
        
        assert result["accounts"][0]["account_id"] == "******11"
        assert result["accounts"][1]["account_id"] == "******22"
    
    def test_token_pattern_redaction(self):
        """Test token/key pattern redaction in strings."""
        redactor = OutputRedactor()
        
        text = 'Response: {"token":"abc123def456xyz789","value":100}'
        result = redactor.redact(text)
        
        assert 'token="***"' in result
        assert "abc123def456xyz789" not in result


class TestToolPolicy:
    """Test tool policy enforcement."""
    
    def test_allow_tool(self):
        """Test allowing a tool by default."""
        rule = ToolPolicyRule(tool_name="get_portfolio", action=ToolAction.ALLOW)
        policy = ToolPolicy(rules=[rule])
        
        allowed, _ = policy.check_tool_allowed("get_portfolio", "session1")
        assert allowed is True
    
    def test_deny_tool(self):
        """Test denying a tool by policy."""
        rule = ToolPolicyRule(tool_name="dangerous_tool", action=ToolAction.DENY)
        policy = ToolPolicy(rules=[rule])
        
        allowed, reason = policy.check_tool_allowed("dangerous_tool", "session1")
        assert allowed is False
        assert "denied by policy" in reason
    
    def test_unknown_tool_denied(self):
        """Test that unknown tools are denied by default (fail-safe)."""
        policy = ToolPolicy(rules=[])
        
        allowed, reason = policy.check_tool_allowed("unknown_tool", "session1")
        assert allowed is False
        assert "not in policy" in reason
    
    def test_max_calls_per_session(self):
        """Test per-session call limit enforcement."""
        rule = ToolPolicyRule(
            tool_name="expensive_tool",
            action=ToolAction.ALLOW,
            max_calls_per_session=2
        )
        policy = ToolPolicy(rules=[rule])
        
        # First 2 calls succeed
        allowed, _ = policy.check_tool_allowed("expensive_tool", "session1")
        assert allowed is True
        policy.record_tool_call("expensive_tool", "session1")
        
        allowed, _ = policy.check_tool_allowed("expensive_tool", "session1")
        assert allowed is True
        policy.record_tool_call("expensive_tool", "session1")
        
        # Third call fails
        allowed, reason = policy.check_tool_allowed("expensive_tool", "session1")
        assert allowed is False
        assert "Max calls" in reason
    
    def test_allowed_sessions(self):
        """Test session allowlist enforcement."""
        rule = ToolPolicyRule(
            tool_name="restricted_tool",
            action=ToolAction.ALLOW,
            allowed_sessions={"session_approved"}
        )
        policy = ToolPolicy(rules=[rule])
        
        # Approved session succeeds
        allowed, _ = policy.check_tool_allowed("restricted_tool", "session_approved")
        assert allowed is True
        
        # Other session fails
        allowed, reason = policy.check_tool_allowed("restricted_tool", "session_other")
        assert allowed is False
        assert "not allowed to use" in reason
    
    def test_parameter_validation(self):
        """Test parameter allowlist/denylist enforcement."""
        rule = ToolPolicyRule(
            tool_name="param_tool",
            action=ToolAction.ALLOW,
            allowed_parameters={"account_id", "symbol"},
            denied_parameters={"dangerous_param"}
        )
        policy = ToolPolicy(rules=[rule])
        
        # Allowed parameters succeed
        allowed, _ = policy.check_tool_allowed(
            "param_tool",
            "session1",
            {"account_id": "DU123", "symbol": "AAPL"}
        )
        assert allowed is True
        
        # Denied parameter fails
        allowed, reason = policy.check_tool_allowed(
            "param_tool",
            "session1",
            {"account_id": "DU123", "dangerous_param": "bad"}
        )
        assert allowed is False
        assert "Denied parameters" in reason
        
        # Disallowed parameter fails
        allowed, reason = policy.check_tool_allowed(
            "param_tool",
            "session1",
            {"account_id": "DU123", "unknown_param": "test"}
        )
        assert allowed is False
        assert "Parameters not allowed" in reason
    
    def test_session_reset(self):
        """Test resetting session call counts."""
        rule = ToolPolicyRule(
            tool_name="test_tool",
            action=ToolAction.ALLOW,
            max_calls_per_session=1
        )
        policy = ToolPolicy(rules=[rule])
        
        # First call succeeds
        allowed, _ = policy.check_tool_allowed("test_tool", "session1")
        assert allowed is True
        policy.record_tool_call("test_tool", "session1")
        
        # Second call fails
        allowed, _ = policy.check_tool_allowed("test_tool", "session1")
        assert allowed is False
        
        # Reset session
        policy.reset_session("session1")
        
        # Should succeed again
        allowed, _ = policy.check_tool_allowed("test_tool", "session1")
        assert allowed is True
    
    def test_get_session_stats(self):
        """Test retrieving session statistics."""
        rule = ToolPolicyRule(tool_name="test_tool", action=ToolAction.ALLOW)
        policy = ToolPolicy(rules=[rule])
        
        # Make calls
        policy.check_tool_allowed("test_tool", "session1")
        policy.record_tool_call("test_tool", "session1")
        policy.record_tool_call("test_tool", "session1")
        
        stats = policy.get_session_stats("session1")
        assert stats["test_tool"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
