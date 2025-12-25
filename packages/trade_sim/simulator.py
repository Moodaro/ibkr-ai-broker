"""Trade simulator implementation."""

from decimal import Decimal
from typing import Optional

from packages.broker_ibkr import OrderSide, OrderType, Portfolio
from packages.schemas import OrderIntent
from packages.trade_sim.models import (
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
)


class TradeSimulator:
    """
    Deterministic trade simulator.

    Simulates order execution with realistic fees, slippage, and portfolio impact.
    Used for pre-execution validation before submitting to broker.
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        """Initialize simulator with configuration."""
        self.config = config or SimulationConfig()

    def simulate(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        market_price: Decimal,
    ) -> SimulationResult:
        """
        Simulate order execution.

        Args:
            intent: Order intent to simulate.
            portfolio: Current portfolio state.
            market_price: Current market price for the instrument.

        Returns:
            Simulation result with estimated costs and portfolio impact.
        """
        warnings: list[str] = []

        # Validate quantity
        if intent.quantity <= 0:
            return SimulationResult(
                status=SimulationStatus.INVALID_QUANTITY,
                error_message=f"Invalid quantity: {intent.quantity}",
            )

        # Determine execution price based on order type
        execution_price = self._estimate_execution_price(
            intent.order_type,
            market_price,
            intent.limit_price,
            intent.stop_price,
            intent.side,
        )

        if execution_price is None:
            return SimulationResult(
                status=SimulationStatus.PRICE_UNAVAILABLE,
                error_message="Cannot determine execution price",
            )

        # Calculate gross notional
        gross_notional = execution_price * intent.quantity

        # Calculate slippage
        estimated_slippage = self._calculate_slippage(
            gross_notional,
            intent.side,
            intent.order_type,
        )

        # Add slippage warning if significant
        if estimated_slippage > gross_notional * Decimal("0.001"):  # > 0.1%
            warnings.append(
                f"Significant estimated slippage: ${estimated_slippage:.2f} "
                f"({(estimated_slippage / gross_notional * 100):.2f}%)"
            )

        # Calculate fees
        estimated_fee = self._calculate_fee(gross_notional, intent.quantity)

        # Calculate net notional (including fees and slippage)
        if intent.side == OrderSide.BUY:
            net_notional = gross_notional + estimated_fee + estimated_slippage
        else:  # SELL
            net_notional = gross_notional - estimated_fee - estimated_slippage

        # Get current cash balance
        cash_before = portfolio.cash[0].total if portfolio.cash else Decimal("0")

        # Calculate cash after trade
        if intent.side == OrderSide.BUY:
            cash_after = cash_before - net_notional
        else:  # SELL
            cash_after = cash_before + net_notional

        # Check cash sufficiency for buys
        if intent.side == OrderSide.BUY and cash_after < 0:
            return SimulationResult(
                status=SimulationStatus.INSUFFICIENT_CASH,
                execution_price=execution_price,
                gross_notional=gross_notional,
                estimated_fee=estimated_fee,
                estimated_slippage=estimated_slippage,
                net_notional=net_notional,
                cash_before=cash_before,
                cash_after=cash_after,
                error_message=f"Insufficient cash: need ${net_notional:.2f}, have ${cash_before:.2f}",
            )

        # Calculate exposure before and after
        exposure_before = portfolio.total_value
        
        if intent.side == OrderSide.BUY:
            # Add new position value (at execution price)
            exposure_after = exposure_before + gross_notional
        else:  # SELL
            # Remove position value (at execution price)
            exposure_after = exposure_before - gross_notional

        # Check constraints if provided
        if intent.constraints:
            constraint_error = self._check_constraints(
                intent,
                estimated_slippage,
                gross_notional,
                net_notional,
            )
            if constraint_error:
                return SimulationResult(
                    status=SimulationStatus.CONSTRAINT_VIOLATED,
                    execution_price=execution_price,
                    gross_notional=gross_notional,
                    estimated_fee=estimated_fee,
                    estimated_slippage=estimated_slippage,
                    net_notional=net_notional,
                    cash_before=cash_before,
                    cash_after=cash_after,
                    exposure_before=exposure_before,
                    exposure_after=exposure_after,
                    error_message=constraint_error,
                )

        # Add warning for large trades relative to portfolio
        if gross_notional > portfolio.total_value * Decimal("0.2"):  # > 20%
            warnings.append(
                f"Large trade: ${gross_notional:.2f} is "
                f"{(gross_notional / portfolio.total_value * 100):.1f}% of portfolio"
            )

        return SimulationResult(
            status=SimulationStatus.SUCCESS,
            execution_price=execution_price,
            gross_notional=gross_notional,
            estimated_fee=estimated_fee,
            estimated_slippage=estimated_slippage,
            net_notional=net_notional,
            cash_before=cash_before,
            cash_after=cash_after,
            exposure_before=exposure_before,
            exposure_after=exposure_after,
            warnings=warnings,
        )

    def _estimate_execution_price(
        self,
        order_type: OrderType,
        market_price: Decimal,
        limit_price: Optional[Decimal],
        stop_price: Optional[Decimal],
        side: OrderSide,
    ) -> Optional[Decimal]:
        """Estimate execution price based on order type."""
        if order_type == OrderType.MKT:
            # Market orders execute at market price
            return market_price
        elif order_type == OrderType.LMT:
            # Limit orders execute at limit price (assuming fill)
            return limit_price
        elif order_type == OrderType.STP:
            # Stop orders convert to market at stop price
            return stop_price
        elif order_type == OrderType.STP_LMT:
            # Stop-limit orders execute at limit price (assuming fill)
            return limit_price
        else:
            return None

    def _calculate_slippage(
        self,
        gross_notional: Decimal,
        side: OrderSide,
        order_type: OrderType,
    ) -> Decimal:
        """Calculate estimated slippage."""
        # No slippage for limit orders (by definition)
        if order_type in [OrderType.LMT, OrderType.STP_LMT]:
            return Decimal("0")

        # Base slippage in USD
        base_slippage_usd = (
            gross_notional * self.config.base_slippage_bps / Decimal("10000")
        )

        # Market impact based on trade size
        # For every $10k, add market_impact_factor bps
        size_factor = gross_notional / Decimal("10000")
        market_impact_bps = self.config.market_impact_factor * size_factor
        market_impact_usd = (
            gross_notional * market_impact_bps / Decimal("10000")
        )

        total_slippage = base_slippage_usd + market_impact_usd

        return total_slippage

    def _calculate_fee(
        self,
        gross_notional: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        """Calculate commission."""
        # Per-share fee
        per_share_fee = self.config.fee_per_share * quantity

        # Minimum fee
        fee = max(per_share_fee, self.config.min_fee)

        # Maximum fee as % of notional
        max_fee_amount = gross_notional * self.config.max_fee
        fee = min(fee, max_fee_amount)

        return fee

    def _check_constraints(
        self,
        intent: OrderIntent,
        estimated_slippage: Decimal,
        gross_notional: Decimal,
        net_notional: Decimal,
    ) -> Optional[str]:
        """Check if order violates constraints."""
        if not intent.constraints:
            return None

        # Check max slippage
        if intent.constraints.max_slippage_bps is not None:
            slippage_bps = (estimated_slippage / gross_notional) * Decimal("10000")
            if slippage_bps > intent.constraints.max_slippage_bps:
                return (
                    f"Estimated slippage {slippage_bps:.1f} bps exceeds "
                    f"max {intent.constraints.max_slippage_bps} bps"
                )

        # Check max notional
        if intent.constraints.max_notional is not None:
            if net_notional > intent.constraints.max_notional:
                return (
                    f"Net notional ${net_notional:.2f} exceeds "
                    f"max ${intent.constraints.max_notional:.2f}"
                )

        return None
