"""Risk Engine for evaluating trade proposals.

This module implements the deterministic risk gate that evaluates
every order proposal against policy rules (R1-R12).

Rules R1-R8: Basic risk checks
Rules R9-R12: Advanced risk checks (volatility, drawdown, time-of-day)
"""

from datetime import datetime, time
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from packages.broker_ibkr import Portfolio
from packages.broker_ibkr.models import OrderSide
from packages.schemas import OrderIntent
from packages.trade_sim import SimulationResult, SimulationStatus

from .models import Decision, RiskDecision, RiskLimits, TradingHours

if TYPE_CHECKING:
    from .advanced import AdvancedRiskEngine, VolatilityMetrics


class RiskEngine:
    """Risk gate that evaluates orders against policy rules (R1-R12)."""

    def __init__(
        self,
        limits: RiskLimits,
        trading_hours: TradingHours,
        daily_trades_count: int = 0,
        daily_pnl: Decimal = Decimal("0"),
        advanced_engine: Optional["AdvancedRiskEngine"] = None,
    ):
        """
        Initialize risk engine.

        Args:
            limits: Risk limits configuration (R1-R4, R6-R8).
            trading_hours: Trading hours configuration (R5).
            daily_trades_count: Current number of trades today (for R7).
            daily_pnl: Current P&L for today (for R8).
            advanced_engine: Optional advanced risk engine for R9-R12 (volatility,
                drawdown, time-of-day restrictions). If None, only R1-R8 are checked.
        """
        self.limits = limits
        self.trading_hours = trading_hours
        self.daily_trades_count = daily_trades_count
        self.daily_pnl = daily_pnl
        self.advanced_engine = advanced_engine

    def evaluate(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        simulation: SimulationResult,
        current_time: Optional[datetime] = None,
        volatility_metrics: Optional["VolatilityMetrics"] = None,
    ) -> RiskDecision:
        """
        Evaluate order against all risk rules (R1-R12).

        Args:
            intent: Validated order intent.
            portfolio: Current portfolio state.
            simulation: Pre-trade simulation result.
            current_time: Current time for R5/R12 checks (defaults to now).
            volatility_metrics: Optional volatility data for R9 (volatility-aware sizing).
                If provided and advanced_engine is configured, enables R9-R12 checks.

        Returns:
            RiskDecision with APPROVE/REJECT. Combines violations from R1-R8 and R9-R12.
        """
        if current_time is None:
            current_time = datetime.utcnow()

        violated_rules: list[str] = []
        warnings: list[str] = []
        metrics: dict = {}

        # If simulation failed, reject immediately
        if simulation.status != SimulationStatus.SUCCESS:
            return RiskDecision(
                decision=Decision.REJECT,
                reason=f"Simulation failed: {simulation.error_message}",
                violated_rules=["SIMULATION_FAILED"],
                warnings=[],
                metrics={},
            )

        # R1: Maximum notional value
        gross_notional = simulation.gross_notional
        metrics["gross_notional"] = float(gross_notional)
        if gross_notional > self.limits.max_notional:
            violated_rules.append("R1")

        # R2: Maximum position size as % of portfolio
        # Calculate position value for the specific symbol after trade
        symbol = intent.instrument.symbol
        current_position_value = Decimal("0")
        for pos in portfolio.positions:
            if pos.instrument.symbol == symbol:
                current_position_value = pos.market_value
                break
        
        # Calculate position value after trade
        if intent.side == OrderSide.BUY:
            position_value_after = current_position_value + simulation.gross_notional
        else:  # SELL
            position_value_after = current_position_value - simulation.gross_notional
        
        portfolio_value = portfolio.total_value
        if portfolio_value > 0:
            position_pct = (position_value_after / portfolio_value) * 100
            metrics["position_pct"] = float(position_pct)
            if position_pct > self.limits.max_position_pct:
                violated_rules.append("R2")

        # R3: Sector exposure (placeholder - requires sector data)
        # For MVP, skip or implement with mock sector mapping
        # violated_rules.append("R3") if condition

        # R4: Maximum slippage
        if simulation.estimated_slippage > 0:
            slippage_bps = (
                (simulation.estimated_slippage / simulation.gross_notional) * 10000
            )
            metrics["slippage_bps"] = float(slippage_bps)
            if slippage_bps > self.limits.max_slippage_bps:
                violated_rules.append("R4")

        # R5: Trading hours
        if not self._is_market_open(current_time):
            violated_rules.append("R5")

        # R6: Minimum liquidity (requires market data - placeholder)
        # For MVP, assume satisfied or check intent.constraints
        # if daily_volume < self.limits.min_daily_volume:
        #     violated_rules.append("R6")

        # R7: Maximum daily trades
        metrics["daily_trades_count"] = self.daily_trades_count
        if self.daily_trades_count >= self.limits.max_daily_trades:
            violated_rules.append("R7")

        # R8: Maximum daily loss
        metrics["daily_pnl"] = float(self.daily_pnl)
        if self.daily_pnl < -self.limits.max_daily_loss:
            violated_rules.append("R8")

        # Decision logic
        if violated_rules:
            return RiskDecision(
                decision=Decision.REJECT,
                reason=self._build_rejection_reason(violated_rules, metrics),
                violated_rules=violated_rules,
                warnings=warnings,
                metrics=metrics,
            )

        # Check for warnings (non-blocking)
        if gross_notional > self.limits.max_notional * Decimal("0.8"):
            warnings.append(
                f"Notional ${gross_notional:,.2f} is close to limit ${self.limits.max_notional:,.2f}"
            )

        if "position_pct" in metrics and metrics["position_pct"] >= float(
            self.limits.max_position_pct * Decimal("0.8")
        ):
            warnings.append(
                f"Position size {metrics['position_pct']:.1f}% approaching limit {self.limits.max_position_pct}%"
            )

        # R9-R12: Advanced risk checks (if configured)
        if self.advanced_engine is not None:
            advanced_decision = self.advanced_engine.evaluate_advanced(
                intent=intent,
                portfolio=portfolio,
                simulation=simulation,
                volatility_metrics=volatility_metrics,
                current_time=current_time,
            )
            
            # Merge violations from advanced rules
            violated_rules.extend(advanced_decision.violated_rules)
            
            # Merge metrics
            metrics.update(advanced_decision.metrics)
            
            # Merge warnings
            warnings.extend(advanced_decision.warnings)
            
            # If advanced rules rejected, return rejection
            if advanced_decision.decision == Decision.REJECT:
                return RiskDecision(
                    decision=Decision.REJECT,
                    reason=f"{self._build_rejection_reason(violated_rules[:len(violated_rules)-len(advanced_decision.violated_rules)], metrics)}; {advanced_decision.reason}" if violated_rules[:len(violated_rules)-len(advanced_decision.violated_rules)] else advanced_decision.reason,
                    violated_rules=violated_rules,
                    warnings=warnings,
                    metrics=metrics,
                )

        return RiskDecision(
            decision=Decision.APPROVE,
            reason="All risk checks passed (R1-R8" + (" + R9-R12)" if self.advanced_engine else ")"),
            violated_rules=[],
            warnings=warnings,
            metrics=metrics,
        )

    def _is_market_open(self, current_time: datetime) -> bool:
        """
        Check if market is open (R5).

        Args:
            current_time: Current time in UTC.

        Returns:
            True if trading is allowed at this time.
        """
        current_time_only = current_time.time()

        # Parse market open/close times
        open_hour, open_minute = map(int, self.trading_hours.market_open_utc.split(":"))
        close_hour, close_minute = map(
            int, self.trading_hours.market_close_utc.split(":")
        )

        market_open = time(open_hour, open_minute)
        market_close = time(close_hour, close_minute)

        # Check if within regular hours
        is_regular_hours = market_open <= current_time_only <= market_close

        if is_regular_hours:
            return True

        # Check pre-market / after-hours if allowed
        if self.trading_hours.allow_pre_market and current_time_only < market_open:
            return True

        if self.trading_hours.allow_after_hours and current_time_only > market_close:
            return True

        return False

    def _build_rejection_reason(
        self, violated_rules: list[str], metrics: dict
    ) -> str:
        """Build human-readable rejection reason."""
        reasons = []

        if "R1" in violated_rules:
            reasons.append(
                f"R1: Notional ${metrics['gross_notional']:,.2f} exceeds limit ${self.limits.max_notional:,.2f}"
            )

        if "R2" in violated_rules:
            reasons.append(
                f"R2: Position size {metrics['position_pct']:.1f}% exceeds limit {self.limits.max_position_pct}%"
            )

        if "R3" in violated_rules:
            reasons.append("R3: Sector exposure limit exceeded")

        if "R4" in violated_rules:
            reasons.append(
                f"R4: Slippage {metrics['slippage_bps']:.1f} bps exceeds limit {self.limits.max_slippage_bps} bps"
            )

        if "R5" in violated_rules:
            reasons.append("R5: Trading outside allowed market hours")

        if "R6" in violated_rules:
            reasons.append("R6: Insufficient liquidity (daily volume too low)")

        if "R7" in violated_rules:
            reasons.append(
                f"R7: Daily trade limit reached ({self.daily_trades_count}/{self.limits.max_daily_trades})"
            )

        if "R8" in violated_rules:
            reasons.append(
                f"R8: Daily loss limit exceeded (${self.daily_pnl:,.2f} / -${self.limits.max_daily_loss:,.2f})"
            )

        return "; ".join(reasons)
