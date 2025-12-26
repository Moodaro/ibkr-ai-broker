"""
Tests for MCP security validation (Epic E).

Validates strict parameter validation, allowlists, and rejection of unknown fields.
"""

import pytest
from decimal import Decimal

from packages.mcp_security import (
    validate_schema,
    StrictBaseModel,
    list_allowed_tools,
    is_write_tool,
    validate_tool_allowlist,
)
from packages.mcp_security.schemas import (
    RequestApprovalSchema,
    GetPortfolioSchema,
    TOOL_SCHEMAS,
    get_schema_for_tool,
)
from pydantic import ValidationError


class TestStrictValidation:
    """Test strict parameter validation for MCP tools."""
    
    def test_request_approval_valid_parameters(self):
        """Test that valid parameters pass validation."""
        valid_args = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": Decimal("100"),
            "order_type": "MKT",
            "market_price": Decimal("150.50"),
            "reason": "Strategic portfolio rebalance based on Q4 earnings"
        }
        
        # Should not raise
        schema = RequestApprovalSchema(**valid_args)
        assert schema.account_id == "DU123456"
        assert schema.side == "BUY"
        assert schema.quantity == Decimal("100")
    
    def test_request_approval_rejects_extra_fields(self):
        """Test that extra/unknown parameters are rejected (prevents injection)."""
        invalid_args = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": Decimal("100"),
            "market_price": Decimal("150.50"),
            "reason": "Test order for validation",
            "extra_field": "malicious_value",  # SHOULD BE REJECTED
            "admin": "true",  # SHOULD BE REJECTED
        }
        
        with pytest.raises(ValidationError) as exc_info:
            RequestApprovalSchema(**invalid_args)
        
        errors = exc_info.value.errors()
        assert len(errors) >= 2  # At least 2 extra fields rejected
        assert any("extra_field" in str(e) for e in errors)
    
    def test_request_approval_validates_side(self):
        """Test that side must be exactly BUY or SELL."""
        invalid_args = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "buy",  # lowercase - should be rejected
            "quantity": Decimal("100"),
            "market_price": Decimal("150.50"),
            "reason": "Test order validation"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            RequestApprovalSchema(**invalid_args)
        
        errors = exc_info.value.errors()
        assert any("side" in str(e) for e in errors)
    
    def test_request_approval_validates_quantity_positive(self):
        """Test that quantity must be positive."""
        invalid_args = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": Decimal("-100"),  # Negative - should be rejected
            "market_price": Decimal("150.50"),
            "reason": "Test order validation"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            RequestApprovalSchema(**invalid_args)
        
        errors = exc_info.value.errors()
        # Check for 'greater_than' constraint
        assert any("quantity" in str(e) for e in errors)
    
    def test_request_approval_validates_reason_length(self):
        """Test that reason must be at least 10 characters."""
        invalid_args = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": Decimal("100"),
            "market_price": Decimal("150.50"),
            "reason": "Short"  # Too short - should be rejected
        }
        
        with pytest.raises(ValidationError) as exc_info:
            RequestApprovalSchema(**invalid_args)
        
        errors = exc_info.value.errors()
        assert any("reason" in str(e) and "at least" in str(e).lower() for e in errors)
    
    def test_get_portfolio_schema(self):
        """Test GetPortfolioSchema validation."""
        valid_args = {"account_id": "DU123456"}
        schema = GetPortfolioSchema(**valid_args)
        assert schema.account_id == "DU123456"
        
        # Test extra field rejection
        invalid_args = {"account_id": "DU123456", "extra": "value"}
        with pytest.raises(ValidationError):
            GetPortfolioSchema(**invalid_args)
    
    def test_strict_base_model_forbids_extra(self):
        """Test that StrictBaseModel rejects extra fields by default."""
        
        class TestSchema(StrictBaseModel):
            field1: str
            field2: int
        
        # Valid
        valid = TestSchema(field1="test", field2=42)
        assert valid.field1 == "test"
        
        # Invalid - extra field
        with pytest.raises(ValidationError):
            TestSchema(field1="test", field2=42, field3="extra")


class TestToolAllowlist:
    """Test tool allowlist and write tool detection."""
    
    def test_list_allowed_tools(self):
        """Test that allowlist contains expected tools."""
        allowed = list_allowed_tools()
        
        assert "get_portfolio" in allowed
        assert "get_positions" in allowed
        assert "request_approval" in allowed
        assert "simulate_order" in allowed
        assert "list_flex_queries" in allowed
        
        # Should NOT contain write tools beyond request_approval
        assert "submit_order" not in allowed
        assert "cancel_order" not in allowed
        assert "modify_order" not in allowed
    
    def test_is_write_tool(self):
        """Test write tool detection."""
        assert is_write_tool("request_approval") is True
        
        # Read-only tools
        assert is_write_tool("get_portfolio") is False
        assert is_write_tool("simulate_order") is False
        assert is_write_tool("evaluate_risk") is False
    
    def test_validate_tool_allowlist(self):
        """Test tool allowlist validation."""
        # Allowed tool
        is_allowed, error = validate_tool_allowlist("request_approval")
        assert is_allowed is True
        assert error is None
        
        # Not allowed tool
        is_allowed, error = validate_tool_allowlist("execute_order")
        assert is_allowed is False
        assert "not in allowlist" in error.lower()


class TestSchemaRegistry:
    """Test schema registry for tool validation."""
    
    def test_get_schema_for_tool(self):
        """Test retrieving schemas from registry."""
        schema = get_schema_for_tool("request_approval")
        assert schema is RequestApprovalSchema
        
        schema = get_schema_for_tool("get_portfolio")
        assert schema is GetPortfolioSchema
        
        # Non-existent tool
        schema = get_schema_for_tool("nonexistent_tool")
        assert schema is None
    
    def test_all_critical_tools_have_schemas(self):
        """Test that all critical tools have validation schemas."""
        critical_tools = [
            "request_approval",
            "get_portfolio",
            "get_positions",
            "simulate_order",
            "evaluate_risk",
        ]
        
        for tool in critical_tools:
            schema = get_schema_for_tool(tool)
            assert schema is not None, f"Tool {tool} missing validation schema"
    
    def test_tool_schemas_registry_completeness(self):
        """Test that TOOL_SCHEMAS registry is populated."""
        assert len(TOOL_SCHEMAS) >= 8  # At least 8 tools with schemas
        assert "request_approval" in TOOL_SCHEMAS
        assert "list_flex_queries" in TOOL_SCHEMAS


@pytest.mark.asyncio
class TestValidateSchemaDecorator:
    """Test @validate_schema decorator functionality."""
    
    async def test_decorator_allows_valid_arguments(self):
        """Test that decorator passes valid arguments through."""
        from mcp.types import TextContent
        
        @validate_schema(GetPortfolioSchema)
        async def mock_handler(arguments: dict):
            return [TextContent(type="text", text="success")]
        
        result = await mock_handler({"account_id": "DU123456"})
        assert len(result) == 1
        assert result[0].text == "success"
    
    async def test_decorator_rejects_extra_fields(self):
        """Test that decorator rejects extra/unknown fields."""
        from mcp.types import TextContent
        import json
        
        @validate_schema(GetPortfolioSchema)
        async def mock_handler(arguments: dict):
            return [TextContent(type="text", text="success")]
        
        result = await mock_handler({
            "account_id": "DU123456",
            "extra_field": "malicious"
        })
        
        assert len(result) == 1
        response = json.loads(result[0].text)
        assert response["status"] == "VALIDATION_ERROR"
        assert "extra_field" in str(response["validation_errors"])
    
    async def test_decorator_validates_field_constraints(self):
        """Test that decorator enforces field constraints."""
        from mcp.types import TextContent
        import json
        
        @validate_schema(RequestApprovalSchema)
        async def mock_handler(arguments: dict):
            return [TextContent(type="text", text="success")]
        
        # Missing required field
        result = await mock_handler({
            "account_id": "DU123456",
            "symbol": "AAPL"
            # Missing side, quantity, market_price, reason
        })
        
        assert len(result) == 1
        response = json.loads(result[0].text)
        assert response["status"] == "VALIDATION_ERROR"
        assert len(response["validation_errors"]) >= 4  # At least 4 missing fields
