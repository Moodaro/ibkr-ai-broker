"""Main FastAPI application for IBKR AI Broker Assistant.

This module provides the REST API for order proposals, simulation,
risk evaluation, and approval management.
"""

import time
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from packages.structured_logging import get_logger, setup_logging

from packages.approval_service import ApprovalService
from packages.metrics_collector import get_metrics_collector
from packages.feature_flags import get_feature_flags
from packages.reconciliation import get_reconciler
from packages.statistics import get_stats_collector, PreLiveStatus
from packages.safety_checks import get_safety_checker
from packages.audit_store import (
    AuditEventCreate,
    AuditStore,
    CorrelationIdMiddleware,
    EventType,
    get_correlation_id,
)
from packages.broker_ibkr import Instrument, InstrumentType
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.kill_switch import KillSwitch, get_kill_switch
from packages.order_submission import OrderSubmitter, OrderSubmissionError
from packages.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    DenyApprovalRequest,
    DenyApprovalResponse,
    GrantApprovalRequest,
    GrantApprovalResponse,
    OrderIntent,
    OrderIntentResponse,
    OrderProposal,
    OrderProposalLifecycle,
    OrderState,
    PendingProposalsResponse,
    RiskEvaluationRequest,
    RiskEvaluationResponse,
    SimulationRequest,
    SimulationResponse,
    SubmitOrderRequest,
    SubmitOrderResponse,
)
from packages.trade_sim import (
    SimulationConfig,
    SimulationResult,
    TradeSimulator,
)
from packages.risk_engine import (
    Decision,
    RiskDecision,
    RiskEngine,
    RiskLimits,
    TradingHours,
    load_policy,
)

# Global audit store instance
audit_store: AuditStore | None = None

# Global simulator instance
simulator: TradeSimulator | None = None

# Global risk engine instance
risk_engine: RiskEngine | None = None

# Global approval service instance
approval_service: ApprovalService | None = None

# Global broker adapter instance
broker: FakeBrokerAdapter | None = None

# Global order submitter instance
order_submitter: OrderSubmitter | None = None

# Global kill switch instance
kill_switch: KillSwitch | None = None

# Initialize logger
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan management."""
    global audit_store, simulator, risk_engine, approval_service, broker, order_submitter, kill_switch
    
    # Setup logging
    import os
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_file = os.getenv("LOG_FILE", "logs/assistant_api.log")
    setup_logging(level=log_level, log_file=log_file, json_output=True)
    
    logger.info("assistant_api_starting")
    
    # Initialize kill switch first (highest priority)
    kill_switch = get_kill_switch()
    
    # Initialize audit store
    audit_store = AuditStore("data/audit.db")
    
    # Initialize simulator with default config
    simulator = TradeSimulator(config=SimulationConfig())
    
    # Initialize risk engine from policy file
    try:
        limits, trading_hours, _ = load_policy("risk_policy.yml")
        risk_engine = RiskEngine(
            limits=limits,
            trading_hours=trading_hours,
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
        )
    except Exception as e:
        logger.warning("failed_to_load_risk_policy", error=str(e))
        # Use default configuration
        risk_engine = RiskEngine(
            limits=RiskLimits(),
            trading_hours=TradingHours(),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
        )
    
    # Initialize approval service
    approval_service = ApprovalService(max_proposals=1000, token_ttl_minutes=5)
    
    # Initialize broker adapter (fake for testing)
    broker = FakeBrokerAdapter(account_id="DU123456")
    broker.connect()
    
    # Initialize reconciler
    get_reconciler(broker_adapter=broker)
    
    # Initialize statistics collector with persistent storage
    from pathlib import Path
    stats_storage = Path("data/statistics.json")
    get_stats_collector(storage_path=stats_storage)
    
    # Initialize order submitter
    order_submitter = OrderSubmitter(
        broker=broker,
        approval_service=approval_service,
        audit_store=audit_store,
    )
    
    yield
    
    # Cleanup (if needed)
    pass


# Create FastAPI app
app = FastAPI(
    title="IBKR AI Broker Assistant API",
    description="Paper trading assistant with LLM proposals and deterministic risk gates",
    version="0.1.0",
    lifespan=lifespan,
)

# Add correlation ID middleware
app.add_middleware(CorrelationIdMiddleware)


@app.exception_handler(ValidationError)
async def validation_exception_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors."""
    correlation_id = get_correlation_id()
    
    # Convert errors to JSON-serializable format
    serializable_errors = []
    for error in exc.errors():
        serializable_error = {
            "type": error.get("type"),
            "loc": [str(loc) for loc in error.get("loc", [])],
            "msg": error.get("msg"),
            "input": str(error.get("input", ""))[:100],  # Truncate long inputs
        }
        serializable_errors.append(serializable_error)
    
    # Emit audit event for validation failure
    if audit_store:
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id or "no-correlation-id",
            data={
                "error_type": "ValidationError",
                "errors": serializable_errors,
                "path": str(request.url),
            },
        )
        audit_store.append_event(event)
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": serializable_errors,
            "correlation_id": correlation_id,
        },
    )


@app.get("/")
async def root() -> dict:
    """Health check endpoint."""
    return {
        "service": "IBKR AI Broker Assistant",
        "version": "0.1.0",
        "status": "healthy",
    }


@app.get("/api/v1/metrics", response_class=PlainTextResponse)
async def get_metrics() -> str:
    """
    Get Prometheus-formatted metrics.
    
    Returns metrics including:
    - Proposal count by symbol and state
    - Risk rejection rate by rule
    - Order latency (submission, fill)
    - Broker errors
    - Daily P&L
    - System uptime
    
    Returns:
        Prometheus text format metrics
    """
    collector = get_metrics_collector()
    return collector.export_prometheus()


@app.post("/api/v1/propose", response_model=OrderIntentResponse)
async def propose_order(proposal: OrderProposal) -> OrderIntentResponse:
    """
    Propose an order for validation.

    This endpoint accepts an order proposal, validates it against
    the OrderIntent schema, and returns a validated intent ready
    for simulation and risk evaluation.

    Args:
        proposal: Order proposal from LLM or user.

    Returns:
        Validated OrderIntent with warnings.

    Raises:
        HTTPException: If validation fails or audit store unavailable.
    """
    # Check kill switch first
    if kill_switch and kill_switch.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Trading is currently halted - kill switch is active",
        )
    
    if not audit_store:
        raise HTTPException(
            status_code=500,
            detail="Audit store not initialized",
        )
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    warnings: list[str] = []
    
    try:
        # Infer instrument type if not provided
        instrument_type = (
            InstrumentType(proposal.instrument_type)
            if proposal.instrument_type
            else InstrumentType.STK  # Default to stock
        )
        
        # Create instrument
        instrument = Instrument(
            type=instrument_type,
            symbol=proposal.symbol.upper(),
            exchange=proposal.exchange,
            currency=proposal.currency,
        )
        
        # Create constraints if provided
        constraints = None
        if proposal.max_slippage_bps or proposal.max_notional:
            from packages.schemas import OrderConstraints
            constraints = OrderConstraints(
                max_slippage_bps=proposal.max_slippage_bps,
                max_notional=proposal.max_notional,
            )
        
        # Create OrderIntent
        intent = OrderIntent(
            account_id=proposal.account_id,
            instrument=instrument,
            side=proposal.side,
            quantity=proposal.quantity,
            order_type=proposal.order_type,
            limit_price=proposal.limit_price,
            stop_price=proposal.stop_price,
            time_in_force=proposal.time_in_force,
            reason=proposal.reason,
            strategy_tag=proposal.strategy_tag,
            constraints=constraints,
        )
        
        # Add warnings for risky configurations
        if intent.order_type == "MKT":
            warnings.append(
                "Market orders have unbounded slippage risk. Consider using LIMIT orders."
            )
        
        if intent.constraints and intent.constraints.max_slippage_bps:
            if intent.constraints.max_slippage_bps > 50:
                warnings.append(
                    f"High slippage tolerance: {intent.constraints.max_slippage_bps} bps"
                )
        
        # Emit audit event
        event = AuditEventCreate(
            event_type=EventType.ORDER_PROPOSED,
            correlation_id=correlation_id,
            data={
                "account_id": intent.account_id,
                "symbol": intent.instrument.symbol,
                "side": intent.side.value,
                "quantity": str(intent.quantity),
                "order_type": intent.order_type.value,
                "limit_price": str(intent.limit_price) if intent.limit_price else None,
                "reason": intent.reason,
                "strategy_tag": intent.strategy_tag,
                "warnings": warnings,
            },
        )
        audit_store.append_event(event)
        
        return OrderIntentResponse(
            intent=intent,
            validation_passed=True,
            warnings=warnings,
            correlation_id=correlation_id,
        )
    
    except ValidationError as e:
        # Re-raise for exception handler
        raise
    except Exception as e:
        # Emit audit event for unexpected errors
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "proposal": proposal.model_dump(),
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create order intent: {str(e)}",
        )


@app.post("/api/v1/simulate", response_model=SimulationResponse)
async def simulate_order(request: SimulationRequest) -> SimulationResponse:
    """
    Simulate an order execution.

    This endpoint accepts a validated OrderIntent and market price,
    simulates the execution using the TradeSimulator, and returns
    detailed cost and impact estimates.

    Args:
        request: Simulation request with intent and market price.

    Returns:
        SimulationResult with execution estimates.

    Raises:
        HTTPException: If simulation fails or services unavailable.
    """
    if not audit_store:
        raise HTTPException(
            status_code=500,
            detail="Audit store not initialized",
        )
    
    if not simulator:
        raise HTTPException(
            status_code=500,
            detail="Simulator not initialized",
        )
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        # Create minimal portfolio for simulation
        # In production, fetch from broker adapter
        from packages.broker_ibkr import Cash, Portfolio
        
        portfolio = Portfolio(
            account_id=request.intent.account_id,
            cash=[
                Cash(
                    currency="USD",
                    total=Decimal("100000.00"),  # Placeholder cash
                    available=Decimal("100000.00"),
                )
            ],
            positions=[],  # Empty positions for now
            total_value=Decimal("100000.00"),
        )
        
        # Run simulation
        result = simulator.simulate(
            intent=request.intent,
            portfolio=portfolio,
            market_price=request.market_price,
        )
        
        # Emit audit event (use mode='json' to convert Decimals to strings)
        event = AuditEventCreate(
            event_type=EventType.ORDER_SIMULATED,
            correlation_id=correlation_id,
            data={
                "intent": request.intent.model_dump(mode="json"),
                "market_price": str(request.market_price),
                "result": result.model_dump(mode="json"),
            },
        )
        audit_store.append_event(event)
        
        return SimulationResponse(
            result=result.model_dump(),
            correlation_id=correlation_id,
        )
    
    except ValidationError as e:
        # Re-raise for exception handler
        raise
    except Exception as e:
        # Emit audit event for unexpected errors
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "request": request.model_dump(),
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(
            status_code=500,
            detail=f"Simulation failed: {str(e)}",
        )


@app.post("/api/v1/risk/evaluate", response_model=RiskEvaluationResponse)
async def evaluate_risk(request: RiskEvaluationRequest) -> RiskEvaluationResponse:
    """
    Evaluate an order against risk policy rules.

    This endpoint accepts an OrderIntent, SimulationResult, and portfolio value,
    evaluates them against configured risk rules (R1-R8), and returns a
    deterministic risk decision (APPROVE, REJECT, or MANUAL_REVIEW).

    Args:
        request: Risk evaluation request with intent, simulation, and portfolio value.

    Returns:
        RiskDecision with approval status, violated rules, warnings, and metrics.

    Raises:
        HTTPException: If risk engine or audit store not initialized.
    """
    if not risk_engine:
        raise HTTPException(
            status_code=500,
            detail="Risk engine not initialized",
        )
    
    if not audit_store:
        raise HTTPException(
            status_code=500,
            detail="Audit store not initialized",
        )
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        # Parse simulation result from dict
        from packages.trade_sim import SimulationResult
        
        simulation = SimulationResult(**request.simulation)
        
        # Create minimal portfolio for risk evaluation
        # In production, fetch from broker adapter
        from packages.broker_ibkr import Cash, Portfolio
        
        portfolio = Portfolio(
            account_id=request.intent.account_id,
            cash=[
                Cash(
                    currency="USD",
                    total=request.portfolio_value,
                    available=request.portfolio_value,
                )
            ],
            positions=[],  # In production, fetch actual positions
            total_value=request.portfolio_value,
        )
        
        # Evaluate risk using current time
        from datetime import datetime, timezone
        
        decision = risk_engine.evaluate(
            intent=request.intent,
            portfolio=portfolio,
            simulation=simulation,
            current_time=datetime.now(timezone.utc),
        )
        
        # Emit audit event
        event = AuditEventCreate(
            event_type=EventType.RISK_GATE_EVALUATED,
            correlation_id=correlation_id,
            data={
                "intent": request.intent.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "violated_rules": decision.violated_rules,
                "warnings": decision.warnings,
            },
        )
        audit_store.append_event(event)
        
        # Record metrics
        collector = get_metrics_collector()
        if decision.is_rejected():
            # Track rejection by each violated rule
            for rule in decision.violated_rules:
                collector.record_risk_rejection(rule)
        
        return RiskEvaluationResponse(
            decision=decision.model_dump(),
            correlation_id=correlation_id,
        )
    
    except ValidationError as e:
        # Re-raise for exception handler
        raise
    except Exception as e:
        # Emit audit event for unexpected errors
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "request": {
                    "intent": request.intent.model_dump(mode="json"),
                    "portfolio_value": str(request.portfolio_value),
                },
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(
            status_code=500,
            detail=f"Risk evaluation failed: {str(e)}",
        )


@app.post("/api/v1/approval/request", response_model=ApprovalResponse)
async def request_approval(request: ApprovalRequest) -> ApprovalResponse:
    """
    Request approval for a proposal.
    
    Transitions proposal from RISK_APPROVED to APPROVAL_REQUESTED.
    
    Args:
        request: Approval request with proposal_id
        
    Returns:
        ApprovalResponse with updated state
        
    Raises:
        HTTPException: If services not initialized or proposal invalid
    """
    if not audit_store:
        raise HTTPException(status_code=500, detail="Audit store not initialized")
    if not approval_service:
        raise HTTPException(status_code=500, detail="Approval service not initialized")
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        # Request approval
        updated = approval_service.request_approval(request.proposal_id)
        
        # Record metrics - proposal count by state
        collector = get_metrics_collector()
        # Extract symbol from intent JSON
        import json
        intent_data = json.loads(updated.intent_json)
        symbol = intent_data.get("symbol", "UNKNOWN")
        collector.increment_proposal_count(symbol=symbol, state=updated.state.value)
        
        # Emit audit event
        event = AuditEventCreate(
            event_type=EventType.APPROVAL_REQUESTED,
            correlation_id=updated.correlation_id,
            data={
                "proposal_id": updated.proposal_id,
                "state": updated.state.value,
            },
        )
        audit_store.append_event(event)
        
        return ApprovalResponse(
            proposal_id=updated.proposal_id,
            state=updated.state,
            message=f"Approval requested for proposal {updated.proposal_id}",
            correlation_id=correlation_id,
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "proposal_id": request.proposal_id,
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}")


@app.post("/api/v1/approval/grant", response_model=GrantApprovalResponse)
async def grant_approval(request: GrantApprovalRequest) -> GrantApprovalResponse:
    """
    Grant approval and generate token.
    
    Transitions proposal from APPROVAL_REQUESTED to APPROVAL_GRANTED.
    Generates single-use ApprovalToken with expiration.
    
    Args:
        request: Grant request with proposal_id and optional reason
        
    Returns:
        GrantApprovalResponse with token
        
    Raises:
        HTTPException: If services not initialized or proposal invalid
    """
    if not audit_store:
        raise HTTPException(status_code=500, detail="Audit store not initialized")
    if not approval_service:
        raise HTTPException(status_code=500, detail="Approval service not initialized")
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        from datetime import datetime, timezone
        current_time = datetime.now(timezone.utc)
        
        # Grant approval
        updated, token = approval_service.grant_approval(
            request.proposal_id,
            reason=request.reason,
            current_time=current_time,
        )
        
        # Emit audit event
        event = AuditEventCreate(
            event_type=EventType.APPROVAL_GRANTED,
            correlation_id=updated.correlation_id,
            data={
                "proposal_id": updated.proposal_id,
                "token_id": token.token_id,
                "expires_at": token.expires_at.isoformat(),
                "reason": request.reason,
            },
        )
        audit_store.append_event(event)
        
        return GrantApprovalResponse(
            proposal_id=updated.proposal_id,
            token=token.token_id,
            expires_at=token.expires_at,
            message=f"Approval granted. Token expires at {token.expires_at.isoformat()}",
            correlation_id=correlation_id,
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "proposal_id": request.proposal_id,
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(status_code=500, detail=f"Grant failed: {str(e)}")


@app.post("/api/v1/approval/deny", response_model=DenyApprovalResponse)
async def deny_approval(request: DenyApprovalRequest) -> DenyApprovalResponse:
    """
    Deny approval.
    
    Transitions proposal from APPROVAL_REQUESTED to APPROVAL_DENIED.
    
    Args:
        request: Deny request with proposal_id and required reason
        
    Returns:
        DenyApprovalResponse with updated state
        
    Raises:
        HTTPException: If services not initialized or proposal invalid
    """
    if not audit_store:
        raise HTTPException(status_code=500, detail="Audit store not initialized")
    if not approval_service:
        raise HTTPException(status_code=500, detail="Approval service not initialized")
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        # Deny approval
        updated = approval_service.deny_approval(
            request.proposal_id,
            reason=request.reason,
        )
        
        # Emit audit event
        event = AuditEventCreate(
            event_type=EventType.APPROVAL_DENIED,
            correlation_id=updated.correlation_id,
            data={
                "proposal_id": updated.proposal_id,
                "reason": request.reason,
            },
        )
        audit_store.append_event(event)
        
        return DenyApprovalResponse(
            proposal_id=updated.proposal_id,
            state=updated.state,
            message=f"Approval denied: {request.reason}",
            correlation_id=correlation_id,
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "proposal_id": request.proposal_id,
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(status_code=500, detail=f"Deny failed: {str(e)}")


@app.get("/api/v1/approval/pending", response_model=PendingProposalsResponse)
async def get_pending_proposals(limit: int = 100) -> PendingProposalsResponse:
    """
    Get list of proposals awaiting approval.
    
    Returns proposals in APPROVAL_REQUESTED or RISK_APPROVED states.
    
    Args:
        limit: Maximum number of proposals to return (default 100)
        
    Returns:
        PendingProposalsResponse with list of pending proposals
        
    Raises:
        HTTPException: If approval service not initialized
    """
    if not approval_service:
        raise HTTPException(status_code=500, detail="Approval service not initialized")
    
    try:
        proposals = approval_service.get_pending_proposals(limit=limit)
        
        return PendingProposalsResponse(
            proposals=proposals,
            count=len(proposals),
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get pending proposals: {str(e)}",
        )


@app.get("/api/v1/health")
async def health_check() -> dict:
    """Comprehensive health check of all critical components.
    
    Returns detailed status of:
    - Kill switch (active/inactive/error)
    - Audit store (connected/disconnected)
    - Broker adapter (connected/disconnected)
    - Approval service (operational/not initialized)
    - Risk engine (operational/not initialized)
    - Trade simulator (operational/not initialized)
    - Order submitter (operational/not initialized)
    
    Returns:
        dict: Health status with component details
    """
    from datetime import datetime, timezone
    
    health = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": get_correlation_id() or "none",
        "components": {},
    }
    
    # Check kill switch
    if kill_switch:
        try:
            ks_state = kill_switch.get_state()
            if ks_state.enabled:
                health["components"]["kill_switch"] = {
                    "status": "active",
                    "message": "⚠️ Kill switch is ACTIVE - trading is halted",
                    "activated_at": ks_state.activated_at.isoformat() if ks_state.activated_at else None,
                    "reason": ks_state.reason,
                }
                health["status"] = "degraded"
            else:
                health["components"]["kill_switch"] = {
                    "status": "inactive",
                    "message": "✅ Kill switch is inactive",
                }
        except Exception as e:
            health["components"]["kill_switch"] = {
                "status": "error",
                "message": f"❌ Error: {str(e)}",
            }
            health["status"] = "degraded"
    else:
        health["components"]["kill_switch"] = {
            "status": "not_initialized",
            "message": "❌ Not initialized",
        }
        health["status"] = "degraded"
    
    # Check audit store
    health["components"]["audit_store"] = {
        "status": "connected" if audit_store else "disconnected",
        "message": "✅ Connected" if audit_store else "❌ Disconnected",
    }
    if not audit_store:
        health["status"] = "unhealthy"
    
    # Check broker
    if broker:
        is_connected = broker.is_connected() if hasattr(broker, "is_connected") else True
        health["components"]["broker"] = {
            "status": "connected" if is_connected else "disconnected",
            "message": "✅ Connected (fake mode)" if is_connected else "❌ Disconnected",
        }
        if not is_connected:
            health["status"] = "degraded"
    else:
        health["components"]["broker"] = {
            "status": "disconnected",
            "message": "❌ Not initialized",
        }
        health["status"] = "unhealthy"
    
    # Check approval service
    health["components"]["approval_service"] = {
        "status": "operational" if approval_service else "not_initialized",
        "message": "✅ Operational" if approval_service else "❌ Not initialized",
    }
    if not approval_service:
        health["status"] = "unhealthy"
    
    # Check risk engine
    health["components"]["risk_engine"] = {
        "status": "operational" if risk_engine else "not_initialized",
        "message": "✅ Operational" if risk_engine else "❌ Not initialized",
    }
    if not risk_engine:
        health["status"] = "unhealthy"
    
    # Check simulator
    health["components"]["simulator"] = {
        "status": "operational" if simulator else "not_initialized",
        "message": "✅ Operational" if simulator else "❌ Not initialized",
    }
    if not simulator:
        health["status"] = "unhealthy"
    
    # Check order submitter
    health["components"]["order_submitter"] = {
        "status": "operational" if order_submitter else "not_initialized",
        "message": "✅ Operational" if order_submitter else "❌ Not initialized",
    }
    if not order_submitter:
        health["status"] = "unhealthy"
    
    return health



@app.post("/api/v1/orders/submit", response_model=SubmitOrderResponse)
async def submit_order(request: SubmitOrderRequest) -> SubmitOrderResponse:
    """
    Submit approved order to broker.
    
    Validates approval token, consumes it, transitions proposal to SUBMITTED,
    submits order to broker, and returns broker order ID.
    
    This is the ONLY way to submit orders - requires valid approval token.
    
    Args:
        request: Submit request with proposal_id and token_id
        
    Returns:
        SubmitOrderResponse with broker order details
        
    Raises:
        HTTPException: If services not initialized or submission fails
    """
    if not order_submitter:
        raise HTTPException(status_code=500, detail="Order submitter not initialized")
    if not audit_store:
        raise HTTPException(status_code=500, detail="Audit store not initialized")
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        from datetime import datetime, timezone
        current_time = datetime.now(timezone.utc)
        start_time = time.time()
        
        # Submit order (validates token, consumes it, submits to broker)
        open_order = order_submitter.submit_order(
            proposal_id=request.proposal_id,
            token_id=request.token_id,
            correlation_id=correlation_id,
            current_time=current_time,
        )
        
        # Record submission latency
        submission_latency = time.time() - start_time
        collector = get_metrics_collector()
        collector.record_order_latency("submission", submission_latency)
        
        # Return response
        return SubmitOrderResponse(
            proposal_id=request.proposal_id,
            broker_order_id=open_order.broker_order_id or "unknown",
            status=open_order.status,
            symbol=open_order.instrument.symbol,
            side=open_order.side,
            quantity=open_order.quantity,
            order_type=open_order.order_type,
            limit_price=open_order.limit_price,
            submitted_at=open_order.created_at,
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OrderSubmissionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        event = AuditEventCreate(
            event_type=EventType.ERROR_OCCURRED,
            correlation_id=correlation_id,
            data={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "proposal_id": request.proposal_id,
                "token_id": request.token_id,
            },
        )
        audit_store.append_event(event)
        
        raise HTTPException(status_code=500, detail=f"Submission failed: {str(e)}")


# Kill Switch Management Endpoints


@app.get("/api/v1/kill-switch/status")
async def get_kill_switch_status():
    """
    Get current kill switch status.
    
    Returns:
        Kill switch state including enabled status, activation time, and reason.
    """
    if not kill_switch:
        raise HTTPException(status_code=500, detail="Kill switch not initialized")
    
    state = kill_switch.get_state()
    return {
        "enabled": state.enabled,
        "activated_at": state.activated_at.isoformat() if state.activated_at else None,
        "activated_by": state.activated_by,
        "reason": state.reason,
    }


@app.post("/api/v1/kill-switch/activate")
async def activate_kill_switch(request: Request, reason: str = "Manual activation via API"):
    """
    Activate kill switch to halt all trading.
    
    Args:
        reason: Reason for activation (optional)
        
    Returns:
        Updated kill switch state.
        
    Raises:
        HTTPException: If kill switch not initialized.
    """
    if not kill_switch or not audit_store:
        raise HTTPException(status_code=500, detail="Services not initialized")
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    # Activate kill switch
    state = kill_switch.activate(activated_by="api", reason=reason)
    
    # Log to audit
    event = AuditEventCreate(
        event_type=EventType.KILL_SWITCH_ACTIVATED,
        correlation_id=correlation_id,
        data={
            "reason": reason,
            "activated_at": state.activated_at.isoformat() if state.activated_at else None,
        },
    )
    audit_store.append_event(event)
    
    return {
        "success": True,
        "enabled": state.enabled,
        "activated_at": state.activated_at.isoformat() if state.activated_at else None,
        "activated_by": state.activated_by,
        "reason": state.reason,
        "message": "Kill switch activated - all trading operations are now blocked",
    }


@app.post("/api/v1/kill-switch/deactivate")
async def deactivate_kill_switch(request: Request):
    """
    Deactivate kill switch to resume trading.
    
    WARNING: Only use after verifying system is safe to resume trading.
    Cannot deactivate if KILL_SWITCH_ENABLED environment variable is set.
    
    Returns:
        Updated kill switch state.
        
    Raises:
        HTTPException: If kill switch not initialized or deactivation blocked by env var.
    """
    if not kill_switch or not audit_store:
        raise HTTPException(status_code=500, detail="Services not initialized")
    
    correlation_id = get_correlation_id() or "no-correlation-id"
    
    try:
        # Deactivate kill switch
        state = kill_switch.deactivate(deactivated_by="api")
        
        # Log to audit
        event = AuditEventCreate(
            event_type=EventType.KILL_SWITCH_RELEASED,
            correlation_id=correlation_id,
            data={
                "deactivated_at": state.activated_at.isoformat() if state.activated_at else None,
            },
        )
        audit_store.append_event(event)
        
        return {
            "success": True,
            "enabled": state.enabled,
            "message": "Kill switch deactivated - trading operations resumed",
        }
    
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Feature Flags Endpoints


@app.get("/api/v1/feature-flags")
async def get_feature_flags_status():
    """
    Get current feature flags status.
    
    Returns:
        Dictionary with all feature flag values.
    """
    flags = get_feature_flags()
    return flags.to_dict()


@app.post("/api/v1/feature-flags/{flag_name}/enable")
async def enable_feature_flag(flag_name: str):
    """
    Enable a feature flag at runtime.
    
    Args:
        flag_name: Name of flag to enable
        
    Returns:
        Updated flag status.
        
    Raises:
        HTTPException: If flag name is invalid.
    """
    flags = get_feature_flags()
    
    if not hasattr(flags, flag_name):
        raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
    
    flags.set_flag(flag_name, True)
    
    return {
        "flag": flag_name,
        "enabled": True,
        "message": f"Feature flag '{flag_name}' enabled",
    }


@app.post("/api/v1/feature-flags/{flag_name}/disable")
async def disable_feature_flag(flag_name: str):
    """
    Disable a feature flag at runtime.
    
    Args:
        flag_name: Name of flag to disable
        
    Returns:
        Updated flag status.
        
    Raises:
        HTTPException: If flag name is invalid.
    """
    flags = get_feature_flags()
    
    if not hasattr(flags, flag_name):
        raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
    
    flags.set_flag(flag_name, False)
    
    return {
        "flag": flag_name,
        "enabled": False,
        "message": f"Feature flag '{flag_name}' disabled",
    }


@app.get("/api/v1/reconciliation/status")
async def get_reconciliation_status(account_id: str = "DU123456"):
    """
    Perform reconciliation between internal state and broker state.
    
    Compares:
    - Open orders
    - Positions
    - Cash balance
    
    Args:
        account_id: Broker account ID (defaults to DU123456)
        
    Returns:
        Reconciliation result with discrepancies.
        
    Example:
        GET /api/v1/reconciliation/status?account_id=DU123456
        
        Returns:
        {
          "timestamp": "2025-12-25T10:00:00Z",
          "is_reconciled": false,
          "discrepancy_count": 2,
          "has_critical_discrepancies": false,
          "discrepancies": [
            {
              "type": "position_mismatch",
              "severity": "medium",
              "description": "Position AAPL mismatch: system=100, broker=95",
              "internal_value": "100",
              "broker_value": "95",
              "difference": 5.0,
              "symbol": "AAPL",
              "order_id": null,
              "detected_at": "2025-12-25T10:00:00Z"
            }
          ],
          "summary": {
            "internal_orders_count": 1,
            "broker_orders_count": 1,
            "internal_positions_count": 2,
            "broker_positions_count": 2,
            "internal_cash": 10000.0,
            "broker_cash": 9950.0
          },
          "duration_ms": 123.45
        }
    """
    logger = get_logger()
    
    try:
        # Get reconciler instance (already initialized with broker in lifespan)
        reconciler = get_reconciler()
        
        # For now, use empty internal state (would fetch from approval service/database in production)
        # TODO: Integrate with real internal state tracking
        internal_orders = []
        internal_positions = {}
        internal_cash = 0.0
        
        # Perform reconciliation
        result = reconciler.reconcile(
            account_id=account_id,
            internal_orders=internal_orders,
            internal_positions=internal_positions,
            internal_cash=internal_cash
        )
        
        logger.info(
            "reconciliation_completed",
            account_id=account_id,
            is_reconciled=result.is_reconciled,
            discrepancy_count=result.discrepancy_count,
            has_critical=result.has_critical_discrepancies
        )
        
        return result.to_dict()
        
    except Exception as e:
        logger.error("reconciliation_failed", error=str(e), account_id=account_id)
        raise HTTPException(
            status_code=500,
            detail=f"Reconciliation failed: {e}"
        )


@app.get("/api/v1/statistics/summary")
async def get_statistics_summary():
    """
    Get paper trading statistics summary.
    
    Returns comprehensive statistics including:
    - Order success rate
    - Rejection breakdown
    - Average latency
    - Simulator accuracy
    - Reconciliation success rate
    
    Returns:
        Dictionary with all tracked metrics
    """
    try:
        stats = get_stats_collector()
        summary = stats.get_summary()
        
        logger.info(
            "statistics_summary_retrieved",
            total_orders=summary.get("total_orders", 0),
            success_rate=summary.get("success_rate", 0.0),
            reject_rate=summary.get("reject_rate", 0.0)
        )
        
        return summary
        
    except Exception as e:
        logger.error("statistics_summary_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve statistics: {e}"
        )


@app.get("/api/v1/statistics/pre-live-checklist")
async def get_pre_live_checklist():
    """
    Get pre-live trading readiness checklist.
    
    Validates system readiness for live trading based on:
    - 200+ orders simulated
    - 50+ orders submitted successfully
    - 0 unintended orders (critical)
    - Reject rate <20%
    - 30 days of 100% reconciliation
    
    Returns:
        PreLiveStatus with validation results
    """
    try:
        stats = get_stats_collector()
        status = stats.get_pre_live_status()
        
        logger.info(
            "pre_live_checklist_evaluated",
            ready_for_live=status.ready_for_live,
            checks_passed=status.checks_passed,
            checks_total=status.checks_total,
            blocking_issues_count=len(status.blocking_issues)
        )
        
        return status.to_dict()
        
    except Exception as e:
        logger.error("pre_live_checklist_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to evaluate pre-live checklist: {e}"
        )


@app.get("/api/v1/safety-checks/status")
async def get_safety_checks():
    """
    Run pre-live safety validation checks.
    
    Validates infrastructure and system health:
    - Test coverage (adequate test files)
    - Audit backup system operational
    - Alerting system configured
    - Reconciliation system initialized
    - Kill switch functional
    - Feature flags working
    - Statistics collection active
    
    Returns:
        SafetyCheckResult with ready_for_live decision and all check results
    """
    try:
        checker = get_safety_checker()
        result = checker.run_all_checks()
        
        logger.info(
            "safety_checks_completed",
            ready_for_live=result.ready_for_live,
            checks_passed=result.checks_passed,
            checks_total=result.checks_total,
            blocking_issues_count=len(result.blocking_issues),
            warnings_count=len(result.warnings)
        )
        
        return result.to_dict()
        
    except Exception as e:
        logger.error("safety_checks_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Safety checks failed: {e}"
        )
