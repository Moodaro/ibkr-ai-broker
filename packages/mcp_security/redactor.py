"""Output redaction for PII and sensitive data.

Prevents leakage of:
- Full account IDs (show partial)
- API tokens/keys
- Personal information
- Internal system details
"""

import re
from typing import Any, Dict, List, Pattern

from packages.structured_logging import get_logger

logger = get_logger(__name__)


class RedactionConfig:
    """Configuration for output redaction."""
    
    def __init__(self):
        """Initialize redaction patterns."""
        
        # Patterns to redact
        self.patterns: List[tuple[Pattern, str]] = [
            # Account IDs: DU123456 -> DU****56
            (re.compile(r'\b(DU|U)(\d{4})(\d{2})\b'), r'\1****\3'),
            
            # Token/API keys: "token_abc123def456" -> "token_***"
            (re.compile(r'(token|key|secret|password|api_key)["\s:=]+([a-zA-Z0-9+/]{8,})', re.IGNORECASE), 
             r'\1="***"'),
            
            # Email addresses: user@example.com -> u***@example.com
            (re.compile(r'\b([a-zA-Z0-9])([a-zA-Z0-9._+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'),
             r'\1***@\3'),
            
            # Credit card-like numbers: 1234-5678-9012-3456 -> ****-****-****-3456
            (re.compile(r'\b(\d{4})-(\d{4})-(\d{4})-(\d{4})\b'),
             r'****-****-****-\4'),
            
            # SSN-like patterns: 123-45-6789 -> ***-**-6789
            (re.compile(r'\b(\d{3})-(\d{2})-(\d{4})\b'),
             r'***-**-\3'),
        ]
        
        # Fields to always redact completely
        self.sensitive_fields = {
            "password",
            "secret",
            "api_key",
            "access_token",
            "refresh_token",
            "private_key",
            "ssn",
            "tax_id",
        }
        
        # Fields to partially redact (show last N chars)
        self.partial_redact_fields = {
            "account_id": 2,  # Show last 2 chars
            "broker_order_id": 4,  # Show last 4 chars
            "proposal_id": 8,  # Show last 8 chars (UUID)
        }


class OutputRedactor:
    """Redacts sensitive information from output."""
    
    def __init__(self, config: RedactionConfig | None = None):
        """Initialize redactor.
        
        Args:
            config: Redaction configuration (uses defaults if None)
        """
        self.config = config or RedactionConfig()
        logger.info("output_redactor_initialized",
                   pattern_count=len(self.config.patterns),
                   sensitive_fields=len(self.config.sensitive_fields))
    
    def redact(self, data: Any) -> Any:
        """Redact sensitive information from data.
        
        Args:
            data: Data to redact (str, dict, list, or primitive)
        
        Returns:
            Redacted copy of data
        """
        if isinstance(data, str):
            return self._redact_string(data)
        elif isinstance(data, dict):
            return self._redact_dict(data)
        elif isinstance(data, list):
            return [self.redact(item) for item in data]
        else:
            # Primitive types (int, float, bool, None)
            return data
    
    def _redact_string(self, text: str) -> str:
        """Apply regex patterns to redact string."""
        result = text
        
        for pattern, replacement in self.config.patterns:
            result = pattern.sub(replacement, result)
        
        return result
    
    def _redact_dict(self, data: dict) -> dict:
        """Redact dictionary recursively."""
        result = {}
        
        for key, value in data.items():
            key_lower = key.lower()
            
            # Complete redaction for sensitive fields
            if key_lower in self.config.sensitive_fields:
                result[key] = "***REDACTED***"
                logger.debug("field_redacted", field=key)
                continue
            
            # Partial redaction for certain fields
            if key_lower in self.config.partial_redact_fields and isinstance(value, str):
                show_chars = self.config.partial_redact_fields[key_lower]
                if len(value) > show_chars:
                    result[key] = "*" * (len(value) - show_chars) + value[-show_chars:]
                else:
                    result[key] = value
                continue
            
            # Recursive redaction
            if isinstance(value, (dict, list, str)):
                result[key] = self.redact(value)
            else:
                result[key] = value
        
        return result
    
    def redact_json_string(self, json_str: str) -> str:
        """Redact JSON string directly (without parsing).
        
        Useful for large JSON where parsing would be expensive.
        
        Args:
            json_str: JSON string to redact
        
        Returns:
            Redacted JSON string
        """
        return self._redact_string(json_str)


# Global redactor instance
_redactor: OutputRedactor | None = None


def get_redactor(config: RedactionConfig | None = None) -> OutputRedactor:
    """Get or create global redactor instance."""
    global _redactor
    if _redactor is None:
        _redactor = OutputRedactor(config)
    return _redactor


def redact_output(data: Any) -> Any:
    """Convenience function to redact data using global redactor."""
    return get_redactor().redact(data)
