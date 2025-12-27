"""
Advanced risk rules with volatility-aware position sizing.

Implements:
- R9: Volatility-adjusted position sizing (VIX-based or symbol-specific)
- R10: Correlation exposure limits (cross-asset)
- R11: Drawdown protection (portfolio level)
- R12: Time-of-day restrictions (avoid market open/close volatility)
"""

from datetime import datetime, time
from decimal import Decimal
from typing import Optional
import math

from packages.broker_ibkr import Portfolio
from packages.broker_ibkr.models import OrderSide
from packages.schemas import OrderIntent
from packages.trade_sim import SimulationResult
from .models import Decision, RiskDecision


class VolatilityMetrics:
    """Volatility metrics for risk assessment."""

    def __init__(
        self,
        symbol_volatility: Optional[float] = None,  # Annual volatility (e.g., 0.20 = 20%)
        market_volatility: Optional[float] = None,  # VIX or market volatility
        beta: Optional[float] = None,  # Symbol beta vs market
    ):
        self.symbol_volatility = symbol_volatility
        self.market_volatility = market_volatility
        self.beta = beta

    def get_effective_volatility(self) -> Optional[float]:
        """
        Calculate effective volatility for sizing.

        Uses symbol-specific if available, otherwise beta * market_vol.
        """
        if self.symbol_volatility is not None:
            return self.symbol_volatility

        if self.beta is not None and self.market_volatility is not None:
            return self.beta * self.market_volatility

        return None


class AdvancedRiskLimits:
    """Advanced risk limits configuration."""

    def __init__(
        self,
        # R9: Volatility-adjusted sizing
        max_position_volatility: float = 0.02,  # Max 2% portfolio risk per position
        volatility_scaling_enabled: bool = True,
        min_position_size: Decimal = Decimal("100"),  # Minimum $ size
        max_position_size: Decimal = Decimal("50000"),  # Maximum $ size
        # R10: Correlation limits
        max_correlated_exposure_pct: float = 30.0,  # Max 30% in correlated assets
        correlation_threshold: float = 0.7,  # Consider correlated if r > 0.7
        # R11: Drawdown protection
        max_drawdown_pct: float = 10.0,  # Max 10% drawdown from high water mark
        enable_drawdown_halt: bool = True,
        # R12: Time-of-day restrictions
        avoid_market_open_minutes: int = 10,  # Avoid first 10 minutes
        avoid_market_close_minutes: int = 10,  # Avoid last 10 minutes
        enable_time_restrictions: bool = True,
    ):
        self.max_position_volatility = max_position_volatility
        self.volatility_scaling_enabled = volatility_scaling_enabled
        self.min_position_size = min_position_size
        self.max_position_size = max_position_size

        self.max_correlated_exposure_pct = max_correlated_exposure_pct
        self.correlation_threshold = correlation_threshold

        self.max_drawdown_pct = max_drawdown_pct
        self.enable_drawdown_halt = enable_drawdown_halt

        self.avoid_market_open_minutes = avoid_market_open_minutes
        self.avoid_market_close_minutes = avoid_market_close_minutes
        self.enable_time_restrictions = enable_time_restrictions


class AdvancedRiskEngine:
    """
    Advanced risk engine with volatility-aware sizing.

    Extends basic RiskEngine with:
    - R9: Volatility-adjusted position sizing
    - R10: Correlation exposure limits
    - R11: Drawdown protection
    - R12: Time-of-day restrictions
    """

    def __init__(
        self,
        limits: AdvancedRiskLimits,
        high_water_mark: Optional[Decimal] = None,
        market_open_time: str = "09:30",  # HH:MM format
        market_close_time: str = "16:00",
    ):
        self.limits = limits
        self.high_water_mark = high_water_mark
        self.market_open_time = self._parse_time(market_open_time)
        self.market_close_time = self._parse_time(market_close_time)

    def evaluate_advanced(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        simulation: SimulationResult,
        volatility_metrics: Optional[VolatilityMetrics] = None,
        current_time: Optional[datetime] = None,
    ) -> RiskDecision:
        """
        Evaluate order against advanced risk rules.

        Args:
            intent: Order intent
            portfolio: Current portfolio
            simulation: Trade simulation result
            volatility_metrics: Volatility data for sizing (optional)
            current_time: Current time (defaults to now UTC)

        Returns:
            RiskDecision with APPROVE/REJECT
        """
        if current_time is None:
            current_time = datetime.utcnow()

        violated_rules: list[str] = []
        warnings: list[str] = []
        metrics: dict = {}

        # R9: Volatility-adjusted position sizing
        if self.limits.volatility_scaling_enabled and volatility_metrics is not None:
            r9_result = self._check_volatility_sizing(
                intent, portfolio, simulation, volatility_metrics, metrics
            )
            if r9_result is not None:
                violated_rules.append("R9")
                warnings.append(r9_result)

        # R10: Correlation exposure (placeholder - requires correlation matrix)
        # For now, check if adding to same sector/asset class
        # r10_result = self._check_correlation_limits(intent, portfolio, metrics)
        # if r10_result is not None:
        #     violated_rules.append("R10")
        #     warnings.append(r10_result)

        # R11: Drawdown protection
        if self.limits.enable_drawdown_halt:
            r11_result = self._check_drawdown_limit(portfolio, metrics)
            if r11_result is not None:
                violated_rules.append("R11")
                warnings.append(r11_result)

        # R12: Time-of-day restrictions
        if self.limits.enable_time_restrictions:
            r12_result = self._check_time_restrictions(current_time, metrics)
            if r12_result is not None:
                violated_rules.append("R12")
                warnings.append(r12_result)

        # Build decision
        if violated_rules:
            return RiskDecision(
                decision=Decision.REJECT,
                reason="; ".join(warnings),
                violated_rules=violated_rules,
                warnings=[],
                metrics=metrics,
            )

        # Non-blocking warnings
        if volatility_metrics is not None:
            effective_vol = volatility_metrics.get_effective_volatility()
            if effective_vol is not None and effective_vol > 0.30:  # 30% annual vol
                warnings.append(
                    f"High volatility detected ({effective_vol*100:.1f}% annual) - consider reduced size"
                )

        return RiskDecision(
            decision=Decision.APPROVE,
            reason="All advanced risk checks passed",
            violated_rules=[],
            warnings=warnings,
            metrics=metrics,
        )

    def _check_volatility_sizing(
        self,
        intent: OrderIntent,
        portfolio: Portfolio,
        simulation: SimulationResult,
        volatility_metrics: VolatilityMetrics,
        metrics: dict,
    ) -> Optional[str]:
        """
        R9: Check volatility-adjusted position sizing.

        Kelly criterion inspired: size based on edge and volatility.
        Position risk = position_value * volatility * multiplier
        Max position risk = portfolio_value * max_position_volatility
        """
        effective_vol = volatility_metrics.get_effective_volatility()
        if effective_vol is None:
            # No volatility data = skip check
            metrics["volatility_available"] = False
            return None

        metrics["symbol_volatility"] = effective_vol

        # Calculate position risk contribution
        position_value = simulation.gross_notional
        portfolio_value = portfolio.total_value

        if portfolio_value <= 0:
            return "Portfolio value invalid for volatility sizing"

        # Check min/max absolute size limits FIRST
        if position_value < self.limits.min_position_size:
            return f"R9: Position size ${position_value:,.2f} below minimum ${self.limits.min_position_size:,.2f}"

        if position_value > self.limits.max_position_size:
            return f"R9: Position size ${position_value:,.2f} exceeds maximum ${self.limits.max_position_size:,.2f}"

        # Use annual volatility directly for position risk calculation
        # Position risk = position_value * volatility (as % of portfolio)
        # This represents the volatility contribution of this position
        position_risk = float(position_value) * effective_vol
        portfolio_risk_pct = (position_risk / float(portfolio_value)) * 100

        metrics["symbol_volatility"] = effective_vol
        metrics["position_risk_pct"] = portfolio_risk_pct

        # Check against limit
        max_risk_pct = self.limits.max_position_volatility * 100
        if portfolio_risk_pct > max_risk_pct:
            # Calculate suggested size
            suggested_size = (
                float(portfolio_value)
                * self.limits.max_position_volatility
                / effective_vol
            )
            metrics["suggested_position_size"] = suggested_size

            return (
                f"R9: Position risk {portfolio_risk_pct:.2f}% exceeds limit {max_risk_pct:.2f}%. "
                f"Suggested max size: ${suggested_size:,.0f}"
            )

        return None

    def _check_correlation_limits(
        self, intent: OrderIntent, portfolio: Portfolio, metrics: dict
    ) -> Optional[str]:
        """
        R10: Check correlation exposure limits.

        Placeholder - requires correlation matrix data.
        """
        # TODO: Implement with actual correlation data
        # For now, group by sector/asset class as proxy
        return None

    def _check_drawdown_limit(
        self, portfolio: Portfolio, metrics: dict
    ) -> Optional[str]:
        """
        R11: Check drawdown protection.

        Halts trading if portfolio drawdown exceeds limit.
        """
        current_value = portfolio.total_value

        # Update high water mark if current value is higher
        if self.high_water_mark is None or current_value > self.high_water_mark:
            self.high_water_mark = current_value
            metrics["high_water_mark"] = float(self.high_water_mark)
            metrics["drawdown_pct"] = 0.0
            return None

        # Calculate drawdown
        drawdown = self.high_water_mark - current_value
        drawdown_pct = (drawdown / self.high_water_mark) * 100

        metrics["high_water_mark"] = float(self.high_water_mark)
        metrics["current_value"] = float(current_value)
        metrics["drawdown_pct"] = float(drawdown_pct)

        if drawdown_pct > self.limits.max_drawdown_pct:
            return (
                f"R11: Portfolio drawdown {drawdown_pct:.2f}% exceeds limit {self.limits.max_drawdown_pct:.1f}%. "
                f"Trading halted until recovery."
            )

        return None

    def _check_time_restrictions(
        self, current_time: datetime, metrics: dict
    ) -> Optional[str]:
        """
        R12: Check time-of-day restrictions.

        Avoids high-volatility periods (market open/close).
        """
        current_time_only = current_time.time()
        metrics["trade_time"] = current_time_only.strftime("%H:%M:%S")

        # Calculate restricted time windows
        from datetime import timedelta

        open_avoid_end = (
            datetime.combine(datetime.today(), self.market_open_time)
            + timedelta(minutes=self.limits.avoid_market_open_minutes)
        ).time()

        close_avoid_start = (
            datetime.combine(datetime.today(), self.market_close_time)
            - timedelta(minutes=self.limits.avoid_market_close_minutes)
        ).time()

        # Check if in restricted window after market open
        if (
            self.market_open_time <= current_time_only < open_avoid_end
        ):
            minutes_since_open = (
                datetime.combine(datetime.today(), current_time_only)
                - datetime.combine(datetime.today(), self.market_open_time)
            ).seconds // 60
            return (
                f"R12: Too close to market open ({minutes_since_open} min). "
                f"Wait {self.limits.avoid_market_open_minutes - minutes_since_open} more minutes."
            )

        # Check if in restricted window before market close
        if close_avoid_start <= current_time_only < self.market_close_time:
            minutes_to_close = (
                datetime.combine(datetime.today(), self.market_close_time)
                - datetime.combine(datetime.today(), current_time_only)
            ).seconds // 60
            return (
                f"R12: Too close to market close ({minutes_to_close} min remaining). "
                f"Trading restricted in final {self.limits.avoid_market_close_minutes} minutes."
            )

        return None

    def _parse_time(self, time_str: str) -> time:
        """Parse HH:MM time string."""
        hour, minute = map(int, time_str.split(":"))
        return time(hour, minute)
