"""Risk policy loader from YAML configuration.

This module loads and validates risk policy from risk_policy.yml.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import RiskLimits, TradingHours


class PolicyLoadError(Exception):
    """Raised when policy file cannot be loaded or validated."""

    pass


def load_policy(policy_path: str | Path = "risk_policy.yml") -> tuple[RiskLimits, TradingHours, dict[str, bool]]:
    """
    Load risk policy from YAML file.

    Args:
        policy_path: Path to risk_policy.yml file.

    Returns:
        Tuple of (RiskLimits, TradingHours, rules_enabled dict).

    Raises:
        PolicyLoadError: If file not found, invalid YAML, or validation fails.
    """
    policy_path = Path(policy_path)

    if not policy_path.exists():
        raise PolicyLoadError(f"Policy file not found: {policy_path}")

    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PolicyLoadError(f"Invalid YAML syntax: {e}")
    except Exception as e:
        raise PolicyLoadError(f"Failed to read policy file: {e}")

    if not isinstance(data, dict):
        raise PolicyLoadError("Policy file must contain a YAML dictionary")

    # Extract sections
    limits_data = data.get("limits", {})
    trading_hours_data = data.get("trading_hours", {})
    rules_enabled = data.get("rules_enabled", {})

    # Check kill switch
    kill_switch = data.get("kill_switch", {})
    if kill_switch.get("enabled", False):
        reason = kill_switch.get("reason", "Kill switch activated")
        raise PolicyLoadError(f"KILL SWITCH ACTIVE: {reason}")

    # Parse and validate limits
    try:
        limits = RiskLimits(
            max_notional=Decimal(str(limits_data.get("max_notional", "50000.00"))),
            max_position_pct=Decimal(str(limits_data.get("max_position_pct", "10.0"))),
            max_sector_exposure_pct=Decimal(
                str(limits_data.get("max_sector_exposure_pct", "30.0"))
            ),
            max_slippage_bps=int(limits_data.get("max_slippage_bps", 50)),
            min_daily_volume=int(limits_data.get("min_daily_volume", 100000)),
            max_daily_trades=int(limits_data.get("max_daily_trades", 50)),
            max_daily_loss=Decimal(str(limits_data.get("max_daily_loss", "5000.00"))),
        )
    except (ValidationError, ValueError, TypeError) as e:
        raise PolicyLoadError(f"Invalid limits configuration: {e}")

    # Parse and validate trading hours
    try:
        trading_hours = TradingHours(
            allow_pre_market=bool(trading_hours_data.get("allow_pre_market", False)),
            allow_after_hours=bool(
                trading_hours_data.get("allow_after_hours", False)
            ),
            market_open_utc=str(trading_hours_data.get("market_open_utc", "14:30")),
            market_close_utc=str(trading_hours_data.get("market_close_utc", "21:00")),
        )
    except (ValidationError, ValueError, TypeError) as e:
        raise PolicyLoadError(f"Invalid trading hours configuration: {e}")

    return limits, trading_hours, rules_enabled


def reload_policy(engine: Any, policy_path: str | Path = "risk_policy.yml") -> None:
    """
    Reload policy and update engine configuration.

    Args:
        engine: RiskEngine instance to update.
        policy_path: Path to risk_policy.yml file.

    Raises:
        PolicyLoadError: If reload fails.
    """
    limits, trading_hours, rules_enabled = load_policy(policy_path)

    # Update engine
    engine.limits = limits
    engine.trading_hours = trading_hours

    # Note: rules_enabled would be used if we add per-rule toggles to engine
    # For now, all enabled rules are always evaluated
