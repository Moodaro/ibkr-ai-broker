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
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import Portfolio, Instrument, InstrumentType
from packages.kill_switch import KillSwitch, get_kill_switch
from packages.risk_engine import RiskEngine, RiskLimits, TradingHours, Decision
from packages.schemas import OrderIntent
from packages.structured_logging import get_logger, setup_logging
from packages.trade_sim import TradeSimulator, SimulationConfig
from packages.approval_service import ApprovalService


# Global services (initialized on startup)
audit_store: Optional[AuditStore] = None
broker: Optional[FakeBrokerAdapter] = None
simulator: Optional[TradeSimulator] = None
risk_engine: Optional[RiskEngine] = None
approval_service: Optional[ApprovalService] = None
kill_switch: Optional[KillSwitch] = None

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
        
        event = AuditEventCreate(
            event_type=EventType.CUSTOM if error is None else EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
            data=event_data,
            metadata={"event_subtype": f"mcp_tool_{tool_name}"},
        )
        
        audit_store.append_event(event)
    except Exception:
        # Silently ignore audit failures
        pass


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
            reason="MCP simulation",
            strategy_tag="mcp",
            constraints={},
        )
        
        # Simulate
        sim_result = simulator.simulate(portfolio, intent, market_price)
        
        result = {
            "status": sim_result.status,
            "gross_notional": str(sim_result.gross_notional),
            "estimated_slippage": str(sim_result.estimated_slippage),
            "estimated_fees": str(sim_result.estimated_fees),
            "net_cash_impact": str(sim_result.net_cash_impact),
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
            reason="MCP risk evaluation",
            strategy_tag="mcp",
            constraints={},
        )
        
        # Simulate first
        sim_result = simulator.simulate(portfolio, intent, market_price)
        
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


async def handle_request_approval(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Request approval for an order (GATED TOOL).
    
    This tool creates a proposal, simulates it, evaluates risk, and if approved,
    requests human approval. Returns proposal_id for tracking.
    
    Args:
        account_id: Account identifier
        symbol: Instrument symbol
        side: BUY or SELL
        quantity: Order quantity
        order_type: MKT, LMT, etc.
        limit_price: (optional) Limit price for LMT orders
        market_price: Current market price
        reason: Reason for the order (min 10 chars)
        
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
        sim_result = simulator.simulate(portfolio, intent, market_price)
        
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


async def main():
    """Main entry point for MCP server."""
    global audit_store, broker, simulator, risk_engine, approval_service, kill_switch
    
    # Setup logging
    import os
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(level=log_level, json_output=True)
    
    logger.info("mcp_server_initializing")
    
    # Initialize kill switch first
    kill_switch = get_kill_switch()
    
    audit_store = AuditStore("mcp_audit.db")
    
    broker = FakeBrokerAdapter(account_id="DU123456")
    broker.connect()
    
    simulator = TradeSimulator(config=SimulationConfig())
    
    risk_engine = RiskEngine(
        limits=RiskLimits(),
        trading_hours=TradingHours(allow_pre_market=True, allow_after_hours=True),
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )
    
    approval_service = ApprovalService(max_proposals=1000)
    
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
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    # Run server
    logger.info("mcp_server_starting", transport="stdio")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
