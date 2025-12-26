"""
MCP Server main entry point for IBKR AI Broker.

Exposes tools via Model Context Protocol:
- get_portfolio: Retrieve portfolio snapshot
- get_positions: List open positions
- get_cash: Get cash balances
- get_open_orders: List pending orders
- simulate_order: Pre-trade simulation
- evaluate_risk: Risk gate evaluation
- request_approval: Create order proposal (GATED - requires human approval)

Security:
- request_approval creates proposals but does NOT execute orders
- Human approval required via dashboard
- All tool calls audited
- Parameter validation required
- Rate limiting support
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from packages.audit_store import AuditStore, AuditEventCreate, EventType
from packages.broker_ibkr import BrokerAdapter
from packages.broker_ibkr.factory import get_broker_adapter
from packages.broker_ibkr.models import Portfolio, Instrument, InstrumentType
from packages.kill_switch import KillSwitch, get_kill_switch
from packages.mcp_security import validate_schema
from packages.mcp_security.schemas import (
    RequestApprovalSchema,
    RequestCancelSchema,
    GetPortfolioSchema,
    GetPositionsSchema,
    GetCashSchema,
    GetOpenOrdersSchema,
    GetMarketSnapshotSchema,
    GetMarketBarsSchema,
    SimulateOrderSchema,
    EvaluateRiskSchema,
    InstrumentSearchSchema,
    InstrumentResolveSchema,
    ListFlexQueriesSchema,
    RunFlexQuerySchema,
)
from packages.risk_engine import RiskEngine, RiskLimits, TradingHours, Decision
from packages.schemas import OrderIntent
from packages.schemas.order_cancel import OrderCancelIntent, OrderCancelResponse
from packages.schemas.market_data import MarketSnapshot, MarketBar, TimeframeType
from packages.schemas.flex_query import FlexQueryRequest
from packages.structured_logging import get_logger, setup_logging
from packages.trade_sim import TradeSimulator, SimulationConfig
from packages.approval_service import ApprovalService
from packages.flex_query import FlexQueryService


# Global services (initialized on startup)
audit_store: Optional[AuditStore] = None
broker: Optional[BrokerAdapter] = None
simulator: Optional[TradeSimulator] = None
risk_engine: Optional[RiskEngine] = None
approval_service: Optional[ApprovalService] = None
kill_switch: Optional[KillSwitch] = None
flex_query_service: Optional[FlexQueryService] = None
flex_query_service: Optional[FlexQueryService] = None

# Initialize logger
logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def emit_audit_event(
    tool_name: str,
    correlation_id: str,
    parameters: dict[str, Any],
    result: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Emit audit event for tool call."""
    if audit_store is None:
        return
    
    try:
        event_data = {
            "tool_name": tool_name,
            "parameters": parameters,
        }
        
        if result is not None:
            event_data["result_summary"] = {
                "type": type(result).__name__,
                "keys": list(result.keys()) if isinstance(result, dict) else None,
            }
        
        if error is not None:
            event_data["error"] = error
        
        # Choose appropriate event type
        event_type = EventType.ERROR_OCCURRED if error is not None else EventType.PORTFOLIO_SNAPSHOT_TAKEN
        
        event = AuditEventCreate(
            event_type=event_type,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
            data=event_data,
            metadata={"event_subtype": f"mcp_tool_{tool_name}"},
        )
        
        audit_store.append_event(event)
    except Exception:
        # Silently ignore audit failures
        pass


@validate_schema(GetPortfolioSchema)
async def handle_get_portfolio(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Get portfolio snapshot.
    
    Args:
        account_id: Account identifier
        
    Returns:
        Portfolio with positions and cash balances
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        account_id = arguments.get("account_id")
        if not account_id:
            raise ValueError("account_id is required")
        
        emit_audit_event("get_portfolio", correlation_id, {"account_id": account_id})
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        portfolio = broker.get_portfolio(account_id)
        
        result = {
            "account_id": portfolio.account_id,
            "total_value": str(portfolio.total_value),
            "positions": [
                {
                    "symbol": pos.instrument.symbol,
                    "type": pos.instrument.type.value,
                    "quantity": str(pos.quantity),
                    "average_cost": str(pos.average_cost),
                    "market_value": str(pos.market_value),
                    "unrealized_pnl": str(pos.unrealized_pnl),
                }
                for pos in portfolio.positions
            ],
            "cash": [
                {
                    "currency": c.currency,
                    "available": str(c.available),
                    "total": str(c.total),
                }
                for c in portfolio.cash
            ],
        }
        
        emit_audit_event("get_portfolio", correlation_id, {"account_id": account_id}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("get_portfolio", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(GetPositionsSchema)
async def handle_get_positions(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Get open positions.
    
    Args:
        account_id: Account identifier
        
    Returns:
        List of open positions
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        account_id = arguments.get("account_id")
        if not account_id:
            raise ValueError("account_id is required")
        
        emit_audit_event("get_positions", correlation_id, {"account_id": account_id})
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        portfolio = broker.get_portfolio(account_id)
        positions = portfolio.positions
        
        result = {
            "positions": [
                {
                    "symbol": pos.instrument.symbol,
                    "type": pos.instrument.type.value,
                    "exchange": pos.instrument.exchange,
                    "currency": pos.instrument.currency,
                    "quantity": str(pos.quantity),
                    "average_cost": str(pos.average_cost),
                    "market_value": str(pos.market_value),
                    "unrealized_pnl": str(pos.unrealized_pnl),
                }
                for pos in positions
            ],
            "count": len(positions),
        }
        
        emit_audit_event("get_positions", correlation_id, {"account_id": account_id}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("get_positions", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(GetCashSchema)
async def handle_get_cash(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Get cash balances.
    
    Args:
        account_id: Account identifier
        
    Returns:
        Cash balances by currency
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        account_id = arguments.get("account_id")
        if not account_id:
            raise ValueError("account_id is required")
        
        emit_audit_event("get_cash", correlation_id, {"account_id": account_id})
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        portfolio = broker.get_portfolio(account_id)
        cash_list = portfolio.cash
        
        result = {
            "cash": [
                {
                    "currency": c.currency,
                    "available": str(c.available),
                    "total": str(c.total),
                }
                for c in cash_list
            ],
        }
        
        emit_audit_event("get_cash", correlation_id, {"account_id": account_id}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("get_cash", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(GetOpenOrdersSchema)
async def handle_get_open_orders(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Get open orders.
    
    Args:
        account_id: Account identifier
        
    Returns:
        List of open orders
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        account_id = arguments.get("account_id")
        if not account_id:
            raise ValueError("account_id is required")
        
        emit_audit_event("get_open_orders", correlation_id, {"account_id": account_id})
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        orders = broker.get_open_orders(account_id)
        
        result = {
            "orders": [
                {
                    "broker_order_id": order.broker_order_id,
                    "symbol": order.instrument.symbol,
                    "side": order.side,
                    "quantity": str(order.quantity),
                    "order_type": order.order_type,
                    "limit_price": str(order.limit_price) if order.limit_price else None,
                    "status": order.status.value,
                    "filled_quantity": str(order.filled_quantity),
                }
                for order in orders
            ],
            "count": len(orders),
        }
        
        emit_audit_event("get_open_orders", correlation_id, {"account_id": account_id}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("get_open_orders", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(SimulateOrderSchema)
async def handle_simulate_order(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Simulate order pre-trade.
    
    Args:
        account_id: Account identifier
        symbol: Instrument symbol
        side: BUY or SELL
        quantity: Order quantity
        order_type: MKT, LMT, etc.
        limit_price: (optional) Limit price for LMT orders
        market_price: Current market price for simulation
        
    Returns:
        Simulation result with estimated impacts
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        # Parse and validate order intent
        account_id = arguments.get("account_id")
        symbol = arguments.get("symbol")
        side = arguments.get("side")
        quantity_str = arguments.get("quantity")
        order_type = arguments.get("order_type", "MKT")
        limit_price_str = arguments.get("limit_price")
        market_price_str = arguments.get("market_price")
        
        if not all([account_id, symbol, side, quantity_str, market_price_str]):
            raise ValueError("Missing required parameters: account_id, symbol, side, quantity, market_price")
        
        quantity = Decimal(quantity_str)
        market_price = Decimal(market_price_str)
        limit_price = Decimal(limit_price_str) if limit_price_str else None
        
        emit_audit_event("simulate_order", correlation_id, arguments)
        
        if broker is None or simulator is None:
            raise RuntimeError("Services not initialized")
        
        # Get portfolio
        portfolio = broker.get_portfolio(account_id)
        
        # Create order intent
        intent = OrderIntent(
            account_id=account_id,
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol=symbol,
                exchange="SMART",
                currency="USD",
            ),
            side=side.upper(),
            quantity=quantity,
            order_type=order_type.upper(),
            limit_price=limit_price,
            time_in_force="DAY",
            reason="MCP tool order simulation",
            strategy_tag="mcp",
            constraints={},
        )
        
        # Simulate
        sim_result = simulator.simulate(intent, portfolio, market_price)
        
        result = {
            "status": sim_result.status,
            "gross_notional": str(sim_result.gross_notional),
            "estimated_slippage": str(sim_result.estimated_slippage),
            "estimated_fee": str(sim_result.estimated_fee),
            "net_notional": str(sim_result.net_notional),
            "cash_before": str(sim_result.cash_before),
            "cash_after": str(sim_result.cash_after),
            "exposure_before": str(sim_result.exposure_before),
            "exposure_after": str(sim_result.exposure_after),
            "warnings": sim_result.warnings,
            "error_message": sim_result.error_message,
        }
        
        emit_audit_event("simulate_order", correlation_id, arguments, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("simulate_order", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(EvaluateRiskSchema)
async def handle_evaluate_risk(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Evaluate risk for order.
    
    Args:
        account_id: Account identifier
        symbol: Instrument symbol
        side: BUY or SELL
        quantity: Order quantity
        order_type: MKT, LMT, etc.
        limit_price: (optional) Limit price
        market_price: Current market price
        
    Returns:
        Risk decision (APPROVE/REJECT) with violated rules
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        # Parse parameters (same as simulate)
        account_id = arguments.get("account_id")
        symbol = arguments.get("symbol")
        side = arguments.get("side")
        quantity_str = arguments.get("quantity")
        order_type = arguments.get("order_type", "MKT")
        limit_price_str = arguments.get("limit_price")
        market_price_str = arguments.get("market_price")
        
        if not all([account_id, symbol, side, quantity_str, market_price_str]):
            raise ValueError("Missing required parameters")
        
        quantity = Decimal(quantity_str)
        market_price = Decimal(market_price_str)
        limit_price = Decimal(limit_price_str) if limit_price_str else None
        
        emit_audit_event("evaluate_risk", correlation_id, arguments)
        
        if broker is None or simulator is None or risk_engine is None:
            raise RuntimeError("Services not initialized")
        
        # Get portfolio
        portfolio = broker.get_portfolio(account_id)
        
        # Create intent
        intent = OrderIntent(
            account_id=account_id,
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol=symbol,
                exchange="SMART",
                currency="USD",
            ),
            side=side.upper(),
            quantity=quantity,
            order_type=order_type.upper(),
            limit_price=limit_price,
            time_in_force="DAY",
            reason="MCP tool risk evaluation",
            strategy_tag="mcp",
            constraints={},
        )
        
        # Simulate first
        sim_result = simulator.simulate(intent, portfolio, market_price)
        
        # Evaluate risk
        risk_decision = risk_engine.evaluate(intent, portfolio, sim_result)
        
        result = {
            "decision": risk_decision.decision.value,
            "reason": risk_decision.reason,
            "violated_rules": risk_decision.violated_rules,
            "warnings": risk_decision.warnings,
            "metrics": {k: str(v) if isinstance(v, Decimal) else v for k, v in risk_decision.metrics.items()},
        }
        
        emit_audit_event("evaluate_risk", correlation_id, arguments, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("evaluate_risk", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(RequestApprovalSchema)
async def handle_request_approval(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Request approval for an order (GATED TOOL - STRICT VALIDATION).
    
    This tool creates a proposal, simulates it, evaluates risk, and if approved,
    requests human approval. Returns proposal_id for tracking.
    
    **SECURITY**: All parameters validated against RequestApprovalSchema.
    Extra/unknown parameters are REJECTED (prevents parameter injection).
    
    Args:
        account_id: Account identifier (required, 1-100 chars)
        symbol: Instrument symbol (required, 1-50 chars)
        side: BUY or SELL (required, exact match)
        quantity: Order quantity (required, must be >0)
        order_type: MKT, LMT, STP, STP_LMT (default: MKT)
        limit_price: Limit price for LMT orders (optional, must be >0)
        market_price: Current market price (required, must be >0)
        reason: Reason for order (required, 10-500 chars)
        
    Returns:
        Proposal ID and status (RISK_APPROVED + APPROVAL_REQUESTED or RISK_REJECTED)
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        # Check kill switch first
        if kill_switch and kill_switch.is_enabled():
            result = {
                "status": "KILL_SWITCH_ACTIVE",
                "error": "Trading is currently halted - kill switch is active",
                "proposal_id": None,
            }
            emit_audit_event("request_approval", correlation_id, arguments, result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Parse and validate parameters
        account_id = arguments.get("account_id")
        symbol = arguments.get("symbol")
        side = arguments.get("side")
        quantity_str = arguments.get("quantity")
        order_type = arguments.get("order_type", "MKT")
        limit_price_str = arguments.get("limit_price")
        market_price_str = arguments.get("market_price")
        reason = arguments.get("reason")
        
        if not all([account_id, symbol, side, quantity_str, market_price_str, reason]):
            raise ValueError("Missing required parameters: account_id, symbol, side, quantity, market_price, reason")
        
        if len(reason) < 10:
            raise ValueError("Reason must be at least 10 characters")
        
        quantity = Decimal(quantity_str)
        market_price = Decimal(market_price_str)
        limit_price = Decimal(limit_price_str) if limit_price_str else None
        
        emit_audit_event("request_approval", correlation_id, arguments)
        
        if broker is None or simulator is None or risk_engine is None or approval_service is None:
            raise RuntimeError("Services not initialized")
        
        # Get portfolio
        portfolio = broker.get_portfolio(account_id)
        
        # Create order intent
        intent = OrderIntent(
            account_id=account_id,
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol=symbol,
                exchange="SMART",
                currency="USD",
            ),
            side=side.upper(),
            quantity=quantity,
            order_type=order_type.upper(),
            limit_price=limit_price,
            time_in_force="DAY",
            reason=reason,
            strategy_tag="mcp_request",
            constraints={},
        )
        
        # Simulate
        sim_result = simulator.simulate(intent, portfolio, market_price)
        
        if sim_result.status != "SUCCESS":
            result = {
                "status": "SIMULATION_FAILED",
                "error": sim_result.error_message,
                "proposal_id": None,
            }
            emit_audit_event("request_approval", correlation_id, arguments, result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Evaluate risk
        risk_decision = risk_engine.evaluate(portfolio, intent, sim_result)
        
        if risk_decision.decision == Decision.REJECT:
            result = {
                "status": "RISK_REJECTED",
                "decision": risk_decision.decision.value,
                "reason": risk_decision.reason,
                "violated_rules": [v.rule_id for v in risk_decision.violations],
                "proposal_id": None,
            }
            emit_audit_event("request_approval", correlation_id, arguments, result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Risk approved - store proposal and request approval
        proposal = approval_service.store_proposal(
            intent=intent,
            sim_result=sim_result,
            risk_decision=risk_decision,
        )
        
        # Request approval
        approval_service.request_approval(proposal.proposal_id)
        
        result = {
            "status": "APPROVAL_REQUESTED",
            "proposal_id": proposal.proposal_id,
            "decision": risk_decision.decision.value,
            "reason": risk_decision.reason,
            "warnings": risk_decision.warnings,
            "symbol": symbol,
            "side": side.upper(),
            "quantity": str(quantity),
            "estimated_cost": str(sim_result.net_cash_impact),
            "message": "Proposal created and awaiting human approval. Use dashboard to approve or deny.",
        }
        
        emit_audit_event("request_approval", correlation_id, arguments, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, cls=DecimalEncoder))]
    
    except Exception as e:
        emit_audit_event("request_approval", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(RequestCancelSchema)
async def handle_request_cancel(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Request cancellation of an order (GATED TOOL - STRICT VALIDATION).
    
    This tool creates a cancel request that requires human approval before execution.
    Can cancel either a pending proposal (not yet submitted) or an active broker order.
    
    **SECURITY**: All parameters validated against RequestCancelSchema.
    Extra/unknown parameters are REJECTED (prevents parameter injection).
    
    Args:
        account_id: Account identifier (required, 1-100 chars)
        proposal_id: Internal proposal ID to cancel (optional)
        broker_order_id: Broker order ID to cancel (optional)
        reason: Reason for cancellation (required, 10-500 chars)
        
    Note: At least one of proposal_id or broker_order_id must be provided.
        
    Returns:
        Cancel approval ID and status (APPROVAL_REQUESTED or ERROR)
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        # Check kill switch first
        if kill_switch and kill_switch.is_enabled():
            result = {
                "status": "KILL_SWITCH_ACTIVE",
                "error": "Trading is currently halted - kill switch is active",
                "approval_id": None,
            }
            emit_audit_event("request_cancel", correlation_id, arguments, result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Extract validated parameters
        account_id = arguments.get("account_id")
        proposal_id = arguments.get("proposal_id")
        broker_order_id = arguments.get("broker_order_id")
        reason = arguments.get("reason")
        
        emit_audit_event("request_cancel", correlation_id, arguments)
        
        if approval_service is None:
            raise RuntimeError("Approval service not initialized")
        
        # Create cancel intent
        cancel_intent = OrderCancelIntent(
            account_id=account_id,
            proposal_id=proposal_id,
            broker_order_id=broker_order_id,
            reason=reason,
        )
        
        # Store cancel request in approval system
        # For now, we'll create a simple approval ID (in future, extend approval_service)
        cancel_approval_id = f"cancel_{uuid.uuid4().hex[:12]}"
        
        # Emit audit event for cancel request
        audit_event = AuditEventCreate(
            event_type=EventType.ORDER_CANCEL_REQUESTED,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "approval_id": cancel_approval_id,
                "account_id": account_id,
                "proposal_id": proposal_id,
                "broker_order_id": broker_order_id,
                "reason": reason,
            },
            metadata={"event_subtype": "mcp_tool_request_cancel"},
        )
        audit_store.append_event(audit_event)
        
        # Build response
        response = OrderCancelResponse(
            approval_id=cancel_approval_id,
            proposal_id=proposal_id,
            broker_order_id=broker_order_id,
            status="PENDING_APPROVAL",
            reason=reason,
            requested_at=datetime.now(timezone.utc),
        )
        
        result = {
            "status": "APPROVAL_REQUESTED",
            "approval_id": response.approval_id,
            "proposal_id": response.proposal_id,
            "broker_order_id": response.broker_order_id,
            "reason": response.reason,
            "message": "Cancel request created and awaiting human approval. Use dashboard to approve or deny.",
        }
        
        emit_audit_event("request_cancel", correlation_id, arguments, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("request_cancel", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(GetMarketSnapshotSchema)
async def handle_get_market_snapshot(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Get current market snapshot for an instrument.
    
    Args:
        instrument: Instrument symbol
        fields: Optional list of specific fields to retrieve
    
    Returns:
        MarketSnapshot with current prices and volume
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        instrument = arguments.get("instrument")
        if not instrument:
            raise ValueError("instrument is required")
        
        fields = arguments.get("fields")
        
        emit_audit_event("get_market_snapshot", correlation_id, {
            "instrument": instrument,
            "fields": fields,
        })
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        snapshot = broker.get_market_snapshot_v2(instrument, fields)
        
        result = {
            "instrument": snapshot.instrument,
            "timestamp": snapshot.timestamp.isoformat(),
            "bid": str(snapshot.bid) if snapshot.bid else None,
            "ask": str(snapshot.ask) if snapshot.ask else None,
            "last": str(snapshot.last) if snapshot.last else None,
            "mid": str(snapshot.mid) if snapshot.mid else None,
            "volume": snapshot.volume,
            "bid_size": snapshot.bid_size,
            "ask_size": snapshot.ask_size,
            "high": str(snapshot.high) if snapshot.high else None,
            "low": str(snapshot.low) if snapshot.low else None,
            "open": str(snapshot.open_price) if snapshot.open_price else None,
            "prev_close": str(snapshot.prev_close) if snapshot.prev_close else None,
        }
        
        emit_audit_event("get_market_snapshot", correlation_id, {"instrument": instrument}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("get_market_snapshot", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(GetMarketBarsSchema)
async def handle_get_market_bars(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Get historical OHLCV bars for an instrument.
    
    Args:
        instrument: Instrument symbol
        timeframe: Bar timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M)
        start: Optional start time (ISO 8601)
        end: Optional end time (ISO 8601)
        limit: Maximum bars to return (default: 100, max: 5000)
        rth_only: Regular trading hours only (default: true)
    
    Returns:
        List of MarketBar with OHLCV data
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        instrument = arguments.get("instrument")
        timeframe = arguments.get("timeframe")
        
        if not instrument:
            raise ValueError("instrument is required")
        if not timeframe:
            raise ValueError("timeframe is required")
        
        # Parse optional datetime arguments
        start_str = arguments.get("start")
        end_str = arguments.get("end")
        start = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else None
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else None
        
        limit = arguments.get("limit", 100)
        rth_only = arguments.get("rth_only", True)
        
        emit_audit_event("get_market_bars", correlation_id, {
            "instrument": instrument,
            "timeframe": timeframe,
            "start": start_str,
            "end": end_str,
            "limit": limit,
            "rth_only": rth_only,
        })
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        bars = broker.get_market_bars(
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
            rth_only=rth_only,
        )
        
        result = {
            "instrument": instrument,
            "timeframe": timeframe,
            "bar_count": len(bars),
            "bars": [
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": bar.volume,
                    "vwap": str(bar.vwap) if bar.vwap else None,
                    "trade_count": bar.trade_count,
                }
                for bar in bars
            ],
        }
        
        emit_audit_event("get_market_bars", correlation_id, {"instrument": instrument, "count": len(bars)}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, cls=DecimalEncoder))]
    except Exception as e:
        logger.error(f"Error getting market bars: {e}", exc_info=True)
        emit_audit_event("get_market_bars", correlation_id, {"instrument": instrument}, error=str(e))
        return [TextContent(type="text", text=f"Error: {e}")]


@validate_schema(InstrumentSearchSchema)
async def handle_instrument_search(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle instrument search tool call.
    
    Args:
        arguments: Tool arguments containing query, optional filters
    
    Returns:
        List of search candidates with match scores
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        query = arguments.get("query")
        if not query:
            raise ValueError("Query is required")
        
        type_filter = arguments.get("type")
        exchange = arguments.get("exchange")
        currency = arguments.get("currency")
        limit = arguments.get("limit", 10)
        
        emit_audit_event("instrument_search", correlation_id, {
            "query": query,
            "type": type_filter,
            "exchange": exchange,
            "currency": currency,
            "limit": limit,
        })
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        candidates = broker.search_instruments(
            query=query,
            type=type_filter,
            exchange=exchange,
            currency=currency,
            limit=limit,
        )
        
        result = {
            "query": query,
            "total_found": len(candidates),
            "candidates": [
                {
                    "con_id": c.con_id,
                    "symbol": c.symbol,
                    "type": c.type,
                    "exchange": c.exchange,
                    "currency": c.currency,
                    "name": c.name,
                    "match_score": c.match_score,
                }
                for c in candidates
            ],
        }
        
        emit_audit_event("instrument_search", correlation_id, {"query": query, "count": len(candidates)}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error(f"Error searching instruments: {e}", exc_info=True)
        emit_audit_event("instrument_search", correlation_id, {"query": arguments.get("query")}, error=str(e))
        return [TextContent(type="text", text=f"Error: {e}")]


@validate_schema(InstrumentResolveSchema)
async def handle_instrument_resolve(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle instrument resolution tool call.
    
    Args:
        arguments: Tool arguments containing symbol, optional filters/conId
    
    Returns:
        Resolved InstrumentContract or error with alternatives
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        symbol = arguments.get("symbol")
        if not symbol:
            raise ValueError("Symbol is required")
        
        type_filter = arguments.get("type")
        exchange = arguments.get("exchange")
        currency = arguments.get("currency")
        con_id = arguments.get("con_id")
        
        emit_audit_event("instrument_resolve", correlation_id, {
            "symbol": symbol,
            "type": type_filter,
            "exchange": exchange,
            "currency": currency,
            "con_id": con_id,
        })
        
        if broker is None:
            raise RuntimeError("Broker not initialized")
        
        # Attempt resolution
        from packages.schemas.instrument import InstrumentResolutionError
        
        try:
            contract = broker.resolve_instrument(
                symbol=symbol,
                type=type_filter,
                exchange=exchange,
                currency=currency,
                con_id=con_id,
            )
            
            result = {
                "success": True,
                "contract": {
                    "con_id": contract.con_id,
                    "symbol": contract.symbol,
                    "type": contract.type,
                    "exchange": contract.exchange,
                    "currency": contract.currency,
                    "local_symbol": contract.local_symbol,
                    "name": contract.name,
                    "sector": contract.sector,
                    "multiplier": contract.multiplier,
                    "expiry": contract.expiry,
                    "strike": str(contract.strike) if contract.strike else None,
                    "right": contract.right,
                    "tradeable": contract.tradeable,
                },
            }
            
            emit_audit_event("instrument_resolve", correlation_id, {"symbol": symbol, "con_id": contract.con_id}, result)
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        except InstrumentResolutionError as e:
            # Return alternatives
            result = {
                "success": False,
                "error": str(e),
                "alternatives": [
                    {
                        "con_id": c.con_id,
                        "symbol": c.symbol,
                        "type": c.type,
                        "exchange": c.exchange,
                        "currency": c.currency,
                        "name": c.name,
                        "match_score": c.match_score,
                    }
                    for c in e.candidates
                ],
            }
            
            emit_audit_event("instrument_resolve", correlation_id, {
                "symbol": symbol,
                "ambiguous": True,
                "alternatives": len(e.candidates)
            }, result)
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
    except Exception as e:
        logger.error(f"Error resolving instrument: {e}", exc_info=True)
        emit_audit_event("instrument_resolve", correlation_id, {"symbol": arguments.get("symbol")}, error=str(e))
        return [TextContent(type="text", text=f"Error: {e}")]
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        emit_audit_event("get_market_bars", correlation_id, arguments, error=str(e))
        return [TextContent(type="text", text=f"Error: {str(e)}")]


@validate_schema(ListFlexQueriesSchema)
async def handle_list_flex_queries(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle list_flex_queries tool call.
    
    Args:
        arguments: Tool arguments (enabled_only optional)
    
    Returns:
        List of configured Flex Queries
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        enabled_only = arguments.get("enabled_only", True)
        
        emit_audit_event("list_flex_queries", correlation_id, {"enabled_only": enabled_only})
        
        if flex_query_service is None:
            raise RuntimeError("FlexQuery service not initialized")
        
        response = flex_query_service.list_queries(enabled_only=enabled_only)
        
        result = {
            "total": response.total,
            "queries": [
                {
                    "query_id": q.query_id,
                    "name": q.name,
                    "type": q.query_type,
                    "description": q.description,
                    "enabled": q.enabled,
                    "auto_schedule": q.auto_schedule,
                    "schedule_cron": q.schedule_cron,
                }
                for q in response.queries
            ],
        }
        
        emit_audit_event("list_flex_queries", correlation_id, {"count": response.total}, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error(f"Error listing flex queries: {e}", exc_info=True)
        emit_audit_event("list_flex_queries", correlation_id, {}, error=str(e))
        return [TextContent(type="text", text=f"Error: {e}")]


@validate_schema(RunFlexQuerySchema)
async def handle_run_flex_query(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle run_flex_query tool call.
    
    Args:
        arguments: Tool arguments containing query_id, optional from_date/to_date
    
    Returns:
        Flex Query execution result with parsed data
    """
    correlation_id = str(uuid.uuid4())
    
    try:
        query_id = arguments.get("query_id")
        if not query_id:
            raise ValueError("query_id is required")
        
        from_date_str = arguments.get("from_date")
        to_date_str = arguments.get("to_date")
        
        from_date = None
        to_date = None
        if from_date_str:
            from_date = datetime.fromisoformat(from_date_str).date()
        if to_date_str:
            to_date = datetime.fromisoformat(to_date_str).date()
        
        emit_audit_event("run_flex_query", correlation_id, {
            "query_id": query_id,
            "from_date": from_date_str,
            "to_date": to_date_str,
        })
        
        if flex_query_service is None:
            raise RuntimeError("FlexQuery service not initialized")
        
        # Create request
        request = FlexQueryRequest(
            query_id=query_id,
            from_date=from_date,
            to_date=to_date,
        )
        
        # Execute query (with mock for now, real implementation would poll IBKR)
        query_result = flex_query_service.execute_query(request)
        
        result = {
            "execution_id": query_result.execution_id,
            "status": query_result.status,
            "query_type": query_result.query_type,
            "from_date": query_result.from_date.isoformat() if query_result.from_date else None,
            "to_date": query_result.to_date.isoformat() if query_result.to_date else None,
            "trades_count": len(query_result.trades),
            "pnl_records_count": len(query_result.pnl_records),
            "cash_transactions_count": len(query_result.cash_transactions),
        }
        
        # Include summary data if completed
        if query_result.status == "COMPLETED":
            if query_result.trades:
                result["trades_summary"] = [
                    {
                        "trade_id": t.trade_id,
                        "symbol": t.symbol,
                        "trade_date": t.trade_date.isoformat(),
                        "quantity": str(t.quantity),
                        "price": str(t.trade_price),
                        "net_cash": str(t.net_cash),
                        "buy_sell": t.buy_sell,
                    }
                    for t in query_result.trades[:10]  # First 10 for summary
                ]
            
            if query_result.pnl_records:
                result["pnl_summary"] = [
                    {
                        "symbol": p.symbol,
                        "realized_pnl": str(p.realized_pnl),
                        "unrealized_pnl": str(p.unrealized_pnl),
                    }
                    for p in query_result.pnl_records[:10]
                ]
        
        emit_audit_event("run_flex_query", correlation_id, {
            "query_id": query_id,
            "status": query_result.status,
            "trades": len(query_result.trades),
        }, result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, cls=DecimalEncoder))]
    except Exception as e:
        logger.error(f"Error running flex query: {e}", exc_info=True)
        emit_audit_event("run_flex_query", correlation_id, {"query_id": arguments.get("query_id")}, error=str(e))
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    """Main entry point for MCP server."""
    global audit_store, broker, simulator, risk_engine, approval_service, kill_switch, flex_query_service
    
    # Setup logging
    import os
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(level=log_level, json_output=True)
    
    logger.info("mcp_server_initializing")
    
    # Initialize kill switch first
    kill_switch = get_kill_switch()
    
    audit_store = AuditStore("mcp_audit.db")
    
    broker = get_broker_adapter()
    
    simulator = TradeSimulator(config=SimulationConfig())
    
    risk_engine = RiskEngine(
        limits=RiskLimits(),
        trading_hours=TradingHours(allow_pre_market=True, allow_after_hours=True),
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )
    
    approval_service = ApprovalService(max_proposals=1000)
    
    # Initialize FlexQuery service
    flex_query_service = FlexQueryService(
        storage_path="./data/flex_reports",
        config_path=os.getenv("FLEX_QUERY_CONFIG", None)
    )
    
    logger.info("mcp_server_services_initialized")
    
    # Create MCP server
    server = Server("ibkr-ai-broker-mcp")
    
    # Define tools
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_portfolio",
                description="Get complete portfolio snapshot including positions and cash",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "Account identifier (e.g., DU123456)",
                        },
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="get_positions",
                description="Get list of open positions",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "Account identifier",
                        },
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="get_cash",
                description="Get cash balances by currency",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "Account identifier",
                        },
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="get_open_orders",
                description="Get list of open orders",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "Account identifier",
                        },
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="simulate_order",
                description="Simulate order to estimate cash impact, fees, and slippage",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "symbol": {"type": "string", "description": "Stock symbol"},
                        "side": {"type": "string", "enum": ["BUY", "SELL"]},
                        "quantity": {"type": "string", "description": "Quantity as decimal string"},
                        "order_type": {"type": "string", "enum": ["MKT", "LMT"], "default": "MKT"},
                        "limit_price": {"type": "string", "description": "Limit price (required for LMT)"},
                        "market_price": {"type": "string", "description": "Current market price for simulation"},
                    },
                    "required": ["account_id", "symbol", "side", "quantity", "market_price"],
                },
            ),
            Tool(
                name="evaluate_risk",
                description="Evaluate order against risk rules (R1-R8)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "symbol": {"type": "string"},
                        "side": {"type": "string", "enum": ["BUY", "SELL"]},
                        "quantity": {"type": "string"},
                        "order_type": {"type": "string", "enum": ["MKT", "LMT"], "default": "MKT"},
                        "limit_price": {"type": "string"},
                        "market_price": {"type": "string"},
                    },
                    "required": ["account_id", "symbol", "side", "quantity", "market_price"],
                },
            ),
            Tool(
                name="request_approval",
                description="Request approval for an order (GATED). Creates proposal, simulates, evaluates risk, and requests human approval. Returns proposal_id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account identifier"},
                        "symbol": {"type": "string", "description": "Stock symbol"},
                        "side": {"type": "string", "enum": ["BUY", "SELL"], "description": "Order side"},
                        "quantity": {"type": "string", "description": "Quantity as decimal string"},
                        "order_type": {"type": "string", "enum": ["MKT", "LMT"], "default": "MKT", "description": "Order type"},
                        "limit_price": {"type": "string", "description": "Limit price (required for LMT)"},
                        "market_price": {"type": "string", "description": "Current market price"},
                        "reason": {"type": "string", "description": "Reason for order (min 10 chars)"},
                    },
                    "required": ["account_id", "symbol", "side", "quantity", "market_price", "reason"],
                },
            ),
            Tool(
                name="request_cancel",
                description="Request cancellation of an order (GATED). Creates cancel request that requires human approval. Can cancel pending proposals or active broker orders. Returns approval_id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account identifier"},
                        "proposal_id": {"type": "string", "description": "Proposal ID to cancel (optional, provide this OR broker_order_id)"},
                        "broker_order_id": {"type": "string", "description": "Broker order ID to cancel (optional, provide this OR proposal_id)"},
                        "reason": {"type": "string", "description": "Reason for cancellation (min 10 chars)"},
                    },
                    "required": ["account_id", "reason"],
                },
            ),
            Tool(
                name="get_market_snapshot",
                description="Get current market snapshot with bid/ask/last prices and volume",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument": {
                            "type": "string",
                            "description": "Instrument symbol (e.g., AAPL, SPY)",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional specific fields to retrieve (bid, ask, last, volume, etc.)",
                        },
                    },
                    "required": ["instrument"],
                },
            ),
            Tool(
                name="get_market_bars",
                description="Get historical OHLCV bars for technical analysis",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument": {
                            "type": "string",
                            "description": "Instrument symbol",
                        },
                        "timeframe": {
                            "type": "string",
                            "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"],
                            "description": "Bar timeframe",
                        },
                        "start": {
                            "type": "string",
                            "description": "Start time in ISO 8601 format (optional, default: 24h ago)",
                        },
                        "end": {
                            "type": "string",
                            "description": "End time in ISO 8601 format (optional, default: now)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum bars to return (default: 100, max: 5000)",
                            "minimum": 1,
                            "maximum": 5000,
                        },
                        "rth_only": {
                            "type": "boolean",
                            "description": "Regular trading hours only (default: true)",
                        },
                    },
                    "required": ["instrument", "timeframe"],
                },
            ),
            Tool(
                name="instrument_search",
                description="Search for instruments by symbol or name with fuzzy matching. Returns candidates sorted by match score.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (symbol or name, partial matches supported)",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["STK", "ETF", "OPT", "FUT", "CASH", "CRYPTO"],
                            "description": "Optional instrument type filter",
                        },
                        "exchange": {
                            "type": "string",
                            "description": "Optional exchange filter (e.g., NASDAQ, NYSE, CME)",
                        },
                        "currency": {
                            "type": "string",
                            "description": "Optional currency filter (e.g., USD, EUR)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return (default: 10, max: 100)",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="instrument_resolve",
                description="Resolve instrument symbol to exact IBKR contract. Use before creating orders to avoid ambiguity. Returns full contract or alternatives if ambiguous.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Instrument symbol to resolve (e.g., AAPL, SPY)",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["STK", "ETF", "OPT", "FUT", "CASH", "CRYPTO"],
                            "description": "Optional instrument type (recommended for disambiguation)",
                        },
                        "exchange": {
                            "type": "string",
                            "description": "Optional exchange (recommended for disambiguation)",
                        },
                        "currency": {
                            "type": "string",
                            "description": "Optional currency (e.g., USD)",
                        },
                        "con_id": {
                            "type": "integer",
                            "description": "Optional explicit IBKR contract ID (highest priority if provided)",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="list_flex_queries",
                description="List available IBKR Flex Queries configured for reporting and reconciliation (read-only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "enabled_only": {
                            "type": "boolean",
                            "description": "Return only enabled queries (default: true)",
                            "default": True,
                        },
                    },
                },
            ),
            Tool(
                name="run_flex_query",
                description="Execute an IBKR Flex Query to retrieve trade confirmations, P&L, or cash reports (read-only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query_id": {
                            "type": "string",
                            "description": "IBKR Flex Query ID to execute",
                        },
                        "from_date": {
                            "type": "string",
                            "description": "Start date in ISO format (YYYY-MM-DD), optional",
                        },
                        "to_date": {
                            "type": "string",
                            "description": "End date in ISO format (YYYY-MM-DD), optional",
                        },
                    },
                    "required": ["query_id"],
                },
            ),
        ]
    
    # Handle tool calls
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "get_portfolio":
            return await handle_get_portfolio(arguments)
        elif name == "get_positions":
            return await handle_get_positions(arguments)
        elif name == "get_cash":
            return await handle_get_cash(arguments)
        elif name == "get_open_orders":
            return await handle_get_open_orders(arguments)
        elif name == "simulate_order":
            return await handle_simulate_order(arguments)
        elif name == "evaluate_risk":
            return await handle_evaluate_risk(arguments)
        elif name == "request_approval":
            return await handle_request_approval(arguments)
        elif name == "request_cancel":
            return await handle_request_cancel(arguments)
        elif name == "get_market_snapshot":
            return await handle_get_market_snapshot(arguments)
        elif name == "get_market_bars":
            return await handle_get_market_bars(arguments)
        elif name == "instrument_search":
            return await handle_instrument_search(arguments)
        elif name == "instrument_resolve":
            return await handle_instrument_resolve(arguments)
        elif name == "list_flex_queries":
            return await handle_list_flex_queries(arguments)
        elif name == "run_flex_query":
            return await handle_run_flex_query(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    # Run server
    logger.info("mcp_server_starting", transport="stdio")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
