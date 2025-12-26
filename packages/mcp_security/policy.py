"""Tool policy enforcement for MCP server.

Defines which tools are allowed, parameter constraints,
and session-based restrictions.
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from packages.structured_logging import get_logger

logger = get_logger(__name__)


class ToolAction(str, Enum):
    """Allowed actions for tools."""
    
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"  # Future: explicit user approval UI


@dataclass
class ToolPolicyRule:
    """Policy rule for a specific tool."""
    
    tool_name: str
    action: ToolAction
    allowed_sessions: Set[str] | None = None  # None = all sessions
    max_calls_per_session: int | None = None  # None = unlimited
    allowed_parameters: Set[str] | None = None  # None = all parameters
    denied_parameters: Set[str] | None = None  # Empty = allow all
    
    def is_allowed(self, session_id: str, call_count: int) -> tuple[bool, Optional[str]]:
        """Check if tool call is allowed under this rule.
        
        Args:
            session_id: Session identifier
            call_count: Number of calls already made in this session
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Check action
        if self.action == ToolAction.DENY:
            return False, f"Tool {self.tool_name} is denied by policy"
        
        # Check session allowlist
        if self.allowed_sessions is not None and session_id not in self.allowed_sessions:
            return False, f"Session {session_id} not allowed to use {self.tool_name}"
        
        # Check per-session call limit
        if self.max_calls_per_session is not None and call_count >= self.max_calls_per_session:
            return False, f"Max calls ({self.max_calls_per_session}) exceeded for {self.tool_name}"
        
        return True, None
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Check if parameters are allowed.
        
        Args:
            parameters: Tool parameters
        
        Returns:
            Tuple of (valid, reason)
        """
        param_keys = set(parameters.keys())
        
        # Check denied parameters (takes precedence)
        if self.denied_parameters:
            denied_present = param_keys & self.denied_parameters
            if denied_present:
                return False, f"Denied parameters: {denied_present}"
        
        # Check allowed parameters allowlist
        if self.allowed_parameters is not None:
            disallowed = param_keys - self.allowed_parameters
            if disallowed:
                return False, f"Parameters not allowed: {disallowed}"
        
        return True, None


class ToolPolicy:
    """Enforces tool access policies."""
    
    def __init__(self, rules: List[ToolPolicyRule] | None = None):
        """Initialize policy.
        
        Args:
            rules: List of policy rules (uses defaults if None)
        """
        self.rules = rules or self._get_default_rules()
        self._rule_map: Dict[str, ToolPolicyRule] = {
            rule.tool_name: rule for rule in self.rules
        }
        
        # Track per-session call counts
        self._session_call_counts: Dict[str, Dict[str, int]] = {}
        
        logger.info("tool_policy_initialized", rule_count=len(self.rules))
    
    def _get_default_rules(self) -> List[ToolPolicyRule]:
        """Get default policy rules (restrictive)."""
        
        # Read-only tools: ALLOW
        read_only_tools = [
            "get_portfolio",
            "get_positions",
            "get_cash",
            "get_open_orders",
            "simulate_order",
            "evaluate_risk",
            "get_market_snapshot",
            "get_market_bars",
            "instrument_search",
            "instrument_resolve",
            "list_flex_queries",
        ]
        
        rules = [
            ToolPolicyRule(tool_name=tool, action=ToolAction.ALLOW)
            for tool in read_only_tools
        ]
        
        # run_flex_query: ALLOW but limited (expensive operation)
        rules.append(ToolPolicyRule(
            tool_name="run_flex_query",
            action=ToolAction.ALLOW,
            max_calls_per_session=10,  # Limit expensive queries
        ))
        
        # Gated write tools: ALLOW (approval is gated by approval_service)
        rules.append(ToolPolicyRule(
            tool_name="request_approval",
            action=ToolAction.ALLOW,
            max_calls_per_session=50,  # Prevent spam
        ))
        
        rules.append(ToolPolicyRule(
            tool_name="request_cancel",
            action=ToolAction.ALLOW,
            max_calls_per_session=50,  # Prevent spam
        ))
        
        return rules
    
    def check_tool_allowed(
        self,
        tool_name: str,
        session_id: str,
        parameters: Dict[str, Any] | None = None
    ) -> tuple[bool, Optional[str]]:
        """Check if tool call is allowed under policy.
        
        Args:
            tool_name: Name of tool
            session_id: Session identifier
            parameters: Tool parameters (optional)
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Get rule for tool
        rule = self._rule_map.get(tool_name)
        
        if rule is None:
            # No explicit rule = DENY by default (fail-safe)
            logger.warning("tool_not_in_policy", tool_name=tool_name, session_id=session_id)
            return False, f"Tool {tool_name} not in policy (denied by default)"
        
        # Get current call count for this tool in this session
        session_counts = self._session_call_counts.setdefault(session_id, {})
        call_count = session_counts.get(tool_name, 0)
        
        # Check rule
        allowed, reason = rule.is_allowed(session_id, call_count)
        if not allowed:
            logger.info("tool_denied_by_policy",
                       tool_name=tool_name,
                       session_id=session_id,
                       reason=reason)
            return False, reason
        
        # Validate parameters if provided
        if parameters is not None:
            valid, reason = rule.validate_parameters(parameters)
            if not valid:
                logger.info("parameters_denied_by_policy",
                           tool_name=tool_name,
                           session_id=session_id,
                           reason=reason)
                return False, reason
        
        return True, None
    
    def record_tool_call(self, tool_name: str, session_id: str):
        """Record a successful tool call (increments counter)."""
        session_counts = self._session_call_counts.setdefault(session_id, {})
        session_counts[tool_name] = session_counts.get(tool_name, 0) + 1
    
    def reset_session(self, session_id: str):
        """Reset call counts for a session."""
        if session_id in self._session_call_counts:
            del self._session_call_counts[session_id]
            logger.info("session_policy_reset", session_id=session_id)
    
    def get_session_stats(self, session_id: str) -> Dict[str, int]:
        """Get call counts for a session."""
        return self._session_call_counts.get(session_id, {}).copy()
    
    @classmethod
    def from_json(cls, path: Path) -> "ToolPolicy":
        """Load policy from JSON file.
        
        Args:
            path: Path to JSON policy file
        
        Returns:
            ToolPolicy instance
        
        Example JSON format:
        {
            "rules": [
                {
                    "tool_name": "get_portfolio",
                    "action": "allow"
                },
                {
                    "tool_name": "request_approval",
                    "action": "allow",
                    "max_calls_per_session": 50,
                    "allowed_sessions": ["session_123"]
                }
            ]
        }
        """
        with open(path, "r") as f:
            data = json.load(f)
        
        rules = []
        for rule_data in data.get("rules", []):
            # Parse sets from lists
            allowed_sessions = rule_data.get("allowed_sessions")
            if allowed_sessions is not None:
                allowed_sessions = set(allowed_sessions)
            
            allowed_parameters = rule_data.get("allowed_parameters")
            if allowed_parameters is not None:
                allowed_parameters = set(allowed_parameters)
            
            denied_parameters = rule_data.get("denied_parameters")
            if denied_parameters is not None:
                denied_parameters = set(denied_parameters)
            
            rule = ToolPolicyRule(
                tool_name=rule_data["tool_name"],
                action=ToolAction(rule_data["action"]),
                allowed_sessions=allowed_sessions,
                max_calls_per_session=rule_data.get("max_calls_per_session"),
                allowed_parameters=allowed_parameters,
                denied_parameters=denied_parameters,
            )
            rules.append(rule)
        
        logger.info("policy_loaded_from_json", path=str(path), rule_count=len(rules))
        return cls(rules=rules)


# Global policy instance
_policy: ToolPolicy | None = None


def get_policy(policy_path: Path | None = None) -> ToolPolicy:
    """Get or create global policy instance.
    
    Args:
        policy_path: Optional path to JSON policy file
    """
    global _policy
    if _policy is None:
        if policy_path and policy_path.exists():
            _policy = ToolPolicy.from_json(policy_path)
        else:
            _policy = ToolPolicy()  # Use defaults
    return _policy
