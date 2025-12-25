"""Main FastAPI application for IBKR AI Broker Assistant.

This module provides the REST API for order proposals, simulation,
risk evaluation, and approval management.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.audit_store import (
    AuditEventCreate,
    AuditStore,
    CorrelationIdMiddleware,
    EventType,
    get_correlation_id,
)
from packages.broker_ibkr import Instrument, InstrumentType
from packages.schemas import (
    OrderIntent,
    OrderIntentResponse,
    OrderProposal,
    SimulationRequest,
    SimulationResponse,
)
from packages.trade_sim import (
    SimulationConfig,
    SimulationResult,
    TradeSimulator,
)

# Global audit store instance
audit_store: AuditStore | None = None

# Global simulator instance
simulator: TradeSimulator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan management."""
    global audit_store, simulator
    
    # Initialize audit store
    audit_store = AuditStore("data/audit.db")
    
    # Initialize simulator with default config
    simulator = TradeSimulator(config=SimulationConfig())
    
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



@app.get("/api/v1/health")
async def health_check() -> dict:
    """Detailed health check."""
    return {
        "status": "healthy",
        "audit_store": "connected" if audit_store else "disconnected",
        "correlation_id": get_correlation_id() or "none",
    }
