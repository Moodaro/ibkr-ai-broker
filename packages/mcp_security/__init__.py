"""
MCP Tool validation and security utilities.

Provides decorators and utilities for strict parameter validation,
rate limiting, and output redaction.
"""

import functools
import json
import logging
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


def validate_schema(schema_class: type[BaseModel]) -> Callable[[F], F]:
    """
    Decorator to validate MCP tool arguments against a Pydantic schema.
    
    Rejects any extra parameters not defined in the schema (strict validation).
    Returns an error TextContent if validation fails.
    
    Usage:
        @validate_schema(MyToolSchema)
        async def handle_my_tool(arguments: dict[str, Any]) -> list[TextContent]:
            # arguments are validated here
            validated = MyToolSchema(**arguments)
            ...
    
    Args:
        schema_class: Pydantic model class for validation
        
    Returns:
        Decorated function with validation
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(arguments: dict[str, Any], *args, **kwargs):
            try:
                # Validate with Pydantic (extra='forbid' prevents unknown fields)
                validated = schema_class.model_validate(arguments, strict=True)
                
                logger.debug(
                    f"Tool {func.__name__} validation passed",
                    extra={
                        "tool": func.__name__,
                        "schema": schema_class.__name__,
                        "arguments": arguments
                    }
                )
                
                # Call original function with validated arguments
                return await func(arguments, *args, **kwargs)
                
            except ValidationError as e:
                # Format validation errors
                errors = []
                for error in e.errors():
                    field = ".".join(str(x) for x in error["loc"])
                    msg = error["msg"]
                    errors.append(f"{field}: {msg}")
                
                error_msg = "Parameter validation failed: " + "; ".join(errors)
                
                logger.warning(
                    f"Tool {func.__name__} validation failed",
                    extra={
                        "tool": func.__name__,
                        "schema": schema_class.__name__,
                        "errors": errors,
                        "arguments": arguments
                    }
                )
                
                # Return error response in MCP format
                from mcp.types import TextContent
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": error_msg,
                        "validation_errors": errors,
                        "status": "VALIDATION_ERROR"
                    }, indent=2)
                )]
                
        return wrapper  # type: ignore
    return decorator


def forbid_extra_fields(model_class: type[BaseModel]) -> type[BaseModel]:
    """
    Utility to create a Pydantic model that forbids extra fields.
    
    Usage:
        @forbid_extra_fields
        class MySchema(BaseModel):
            field1: str
            field2: int
    
    Args:
        model_class: Pydantic BaseModel class
        
    Returns:
        Modified class with extra='forbid' in ConfigDict
    """
    # Add ConfigDict to forbid extra fields
    if not hasattr(model_class, 'model_config'):
        from pydantic import ConfigDict
        model_class.model_config = ConfigDict(extra='forbid')
    else:
        model_class.model_config['extra'] = 'forbid'
    
    return model_class


class StrictBaseModel(BaseModel):
    """
    Base Pydantic model with strict validation enabled.
    
    - Forbids extra fields (extra='forbid')
    - Validates assignment (validate_assignment=True)
    - Strict mode (strict=True)
    
    Use this as base for all MCP tool schemas to ensure security.
    
    Example:
        class RequestApprovalSchema(StrictBaseModel):
            account_id: str
            symbol: str
            side: str
            quantity: Decimal
            reason: str = Field(min_length=10)
    """
    model_config = {
        'extra': 'forbid',  # Reject unknown fields
        'validate_assignment': True,  # Validate on field assignment
        'strict': True,  # Strict type checking
    }


def list_allowed_tools() -> list[str]:
    """
    Return list of allowed MCP tools (allowlist).
    
    Only tools in this list can be called by LLM.
    All write operations must go through request_approval.
    
    Returns:
        List of allowed tool names
    """
    return [
        # Read-only broker tools
        "get_portfolio",
        "get_positions",
        "get_market_snapshot",
        "get_broker_status",
        
        # Read-only flex query tools
        "list_flex_queries",
        "run_flex_query",
        
        # Risk/simulation tools (read-only)
        "simulate_order",
        "evaluate_risk",
        
        # ONLY write tool (gated)
        "request_approval",
        
        # System tools
        "kill_switch_status",
    ]


def is_write_tool(tool_name: str) -> bool:
    """
    Check if a tool performs write operations.
    
    Only request_approval is allowed to write.
    Any other write operation should be rejected.
    
    Args:
        tool_name: Name of the MCP tool
        
    Returns:
        True if tool performs writes, False otherwise
    """
    write_tools = {
        "request_approval",  # Only allowed write tool
    }
    return tool_name in write_tools


def validate_tool_allowlist(tool_name: str) -> tuple[bool, str | None]:
    """
    Validate that a tool is in the allowlist.
    
    Args:
        tool_name: Name of the MCP tool to validate
        
    Returns:
        Tuple of (is_allowed, error_message)
    """
    allowed = list_allowed_tools()
    
    if tool_name not in allowed:
        return False, f"Tool '{tool_name}' not in allowlist. Allowed tools: {', '.join(allowed)}"
    
    return True, None
