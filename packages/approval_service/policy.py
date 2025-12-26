"""
Auto-approval policy configuration and checker.

Defines advanced filtering rules for automatic order approval beyond simple notional threshold.
"""

from datetime import time
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class DayOfWeek(str, Enum):
    """Day of week for time window restrictions."""
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class TimeWindow(BaseModel):
    """Trading time window restriction."""
    start_time: time = Field(..., description="Start time (HH:MM:SS)")
    end_time: time = Field(..., description="End time (HH:MM:SS)")
    days: list[DayOfWeek] = Field(
        default_factory=lambda: [
            DayOfWeek.MONDAY,
            DayOfWeek.TUESDAY,
            DayOfWeek.WEDNESDAY,
            DayOfWeek.THURSDAY,
            DayOfWeek.FRIDAY,
        ],
        description="Days when window is active",
    )
    timezone: str = Field(default="America/New_York", description="Timezone for time window")


class DCASchedule(BaseModel):
    """Dollar-Cost Averaging schedule configuration."""
    symbols: list[str] = Field(..., description="Symbols eligible for DCA")
    max_order_size: float = Field(..., gt=0, description="Max size per DCA order")
    side: str = Field(..., pattern=r"^(BUY|SELL)$", description="Order side (BUY or SELL)")
    order_type: str = Field(default="MKT", pattern=r"^(MKT|LMT)$", description="Order type")


class AutoApprovalPolicy(BaseModel):
    """
    Advanced auto-approval policy configuration.
    
    Defines rules beyond simple notional threshold:
    - Symbol whitelists (ETFs, stocks)
    - Time window restrictions (market hours only)
    - DCA pattern detection
    - Order type restrictions
    """
    
    enabled: bool = Field(default=True, description="Master enable/disable switch")
    
    # Symbol restrictions
    symbol_whitelist: Optional[list[str]] = Field(
        default=None,
        description="Allowed symbols (None = all allowed). Example: ['SPY', 'QQQ', 'VTI']",
    )
    symbol_blacklist: list[str] = Field(
        default_factory=list,
        description="Forbidden symbols (takes precedence over whitelist)",
    )
    
    # Security type restrictions
    allowed_sec_types: list[str] = Field(
        default_factory=lambda: ["STK", "ETF"],
        description="Allowed security types (STK, ETF, FUT, OPT, FX, CRYPTO)",
    )
    
    # Time window restrictions
    time_windows: list[TimeWindow] = Field(
        default_factory=list,
        description="Allowed trading time windows (empty = always allowed)",
    )
    
    # Order type restrictions
    allowed_order_types: list[str] = Field(
        default_factory=lambda: ["MKT", "LMT"],
        description="Allowed order types",
    )
    
    # DCA schedules
    dca_schedules: list[DCASchedule] = Field(
        default_factory=list,
        description="DCA schedules with per-symbol limits",
    )
    
    # Risk limits
    max_position_pct: Optional[float] = Field(
        default=None,
        gt=0,
        le=100,
        description="Max position size as % of portfolio NAV (None = no limit)",
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "symbol_whitelist": ["SPY", "QQQ", "VTI", "AGG"],
                "symbol_blacklist": ["TSLA"],
                "allowed_sec_types": ["STK", "ETF"],
                "time_windows": [
                    {
                        "start_time": "09:30:00",
                        "end_time": "16:00:00",
                        "days": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"],
                        "timezone": "America/New_York",
                    }
                ],
                "allowed_order_types": ["MKT", "LMT"],
                "dca_schedules": [
                    {
                        "symbols": ["SPY", "QQQ"],
                        "max_order_size": 200.0,
                        "side": "BUY",
                        "order_type": "MKT",
                    }
                ],
                "max_position_pct": 5.0,
            }
        }


class PolicyChecker:
    """
    Checks if an order intent matches auto-approval policy rules.
    """
    
    def __init__(self, policy: AutoApprovalPolicy):
        self.policy = policy
    
    def check_symbol(self, symbol: str) -> tuple[bool, str]:
        """Check if symbol is allowed by policy."""
        if not self.policy.enabled:
            return False, "Policy disabled"
        
        # Blacklist takes precedence
        if symbol in self.policy.symbol_blacklist:
            return False, f"Symbol {symbol} is blacklisted"
        
        # Whitelist check (if configured)
        if self.policy.symbol_whitelist is not None:
            if symbol not in self.policy.symbol_whitelist:
                return False, f"Symbol {symbol} not in whitelist"
        
        return True, ""
    
    def check_security_type(self, sec_type: str) -> tuple[bool, str]:
        """Check if security type is allowed."""
        if not self.policy.enabled:
            return False, "Policy disabled"
        
        if sec_type not in self.policy.allowed_sec_types:
            return False, f"Security type {sec_type} not allowed"
        
        return True, ""
    
    def check_time_window(self, current_time: time, current_day: DayOfWeek) -> tuple[bool, str]:
        """Check if current time is within allowed time windows."""
        if not self.policy.enabled:
            return False, "Policy disabled"
        
        # No time windows = always allowed
        if not self.policy.time_windows:
            return True, ""
        
        # Check if current time falls within any window
        for window in self.policy.time_windows:
            if current_day not in window.days:
                continue
            
            if window.start_time <= current_time <= window.end_time:
                return True, ""
        
        return False, "Outside allowed time windows"
    
    def check_order_type(self, order_type: str) -> tuple[bool, str]:
        """Check if order type is allowed."""
        if not self.policy.enabled:
            return False, "Policy disabled"
        
        if order_type not in self.policy.allowed_order_types:
            return False, f"Order type {order_type} not allowed"
        
        return True, ""
    
    def check_dca_schedule(
        self,
        symbol: str,
        side: str,
        order_type: str,
        notional: float,
    ) -> tuple[bool, str]:
        """Check if order matches DCA schedule (if applicable)."""
        if not self.policy.enabled:
            return False, "Policy disabled"
        
        # No DCA schedules = N/A (not a blocking condition)
        if not self.policy.dca_schedules:
            return True, ""
        
        # Find matching DCA schedule
        for schedule in self.policy.dca_schedules:
            if symbol not in schedule.symbols:
                continue
            if side != schedule.side:
                continue
            if order_type != schedule.order_type:
                continue
            
            # Matched DCA schedule - check size limit
            if notional > schedule.max_order_size:
                return False, f"DCA order size ${notional} exceeds limit ${schedule.max_order_size}"
            
            return True, f"Matches DCA schedule for {symbol}"
        
        # No matching DCA schedule = N/A (not a blocking condition)
        return True, ""
    
    def check_position_size(
        self,
        notional: float,
        portfolio_nav: Optional[float],
    ) -> tuple[bool, str]:
        """Check if position size is within policy limits."""
        if not self.policy.enabled:
            return False, "Policy disabled"
        
        # No limit configured = always allowed
        if self.policy.max_position_pct is None:
            return True, ""
        
        # No portfolio NAV = cannot check (fail safe)
        if portfolio_nav is None or portfolio_nav <= 0:
            return False, "Cannot verify position size limit (portfolio NAV unavailable)"
        
        position_pct = (notional / portfolio_nav) * 100
        
        if position_pct > self.policy.max_position_pct:
            return False, f"Position size {position_pct:.2f}% exceeds limit {self.policy.max_position_pct}%"
        
        return True, ""
    
    def check_all(
        self,
        symbol: str,
        sec_type: str,
        side: str,
        order_type: str,
        notional: float,
        current_time: time,
        current_day: DayOfWeek,
        portfolio_nav: Optional[float] = None,
    ) -> tuple[bool, list[str]]:
        """
        Check all policy rules.
        
        Returns:
            tuple[bool, list[str]]: (all_passed, reasons)
            - all_passed: True if all checks passed
            - reasons: List of failure reasons (empty if all passed)
        """
        if not self.policy.enabled:
            return False, ["Policy disabled"]
        
        reasons = []
        
        # Symbol check
        ok, reason = self.check_symbol(symbol)
        if not ok:
            reasons.append(reason)
        
        # Security type check
        ok, reason = self.check_security_type(sec_type)
        if not ok:
            reasons.append(reason)
        
        # Time window check
        ok, reason = self.check_time_window(current_time, current_day)
        if not ok:
            reasons.append(reason)
        
        # Order type check
        ok, reason = self.check_order_type(order_type)
        if not ok:
            reasons.append(reason)
        
        # DCA schedule check
        ok, reason = self.check_dca_schedule(symbol, side, order_type, notional)
        if not ok:
            reasons.append(reason)
        
        # Position size check
        ok, reason = self.check_position_size(notional, portfolio_nav)
        if not ok:
            reasons.append(reason)
        
        return len(reasons) == 0, reasons
