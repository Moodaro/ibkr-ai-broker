"""Tests for feature flags."""

import json
import os
from pathlib import Path

import pytest

from packages.feature_flags import FeatureFlags, get_feature_flags, set_feature_flags


class TestFeatureFlags:
    """Test feature flags functionality."""
    
    def test_default_values(self):
        """Test default feature flag values."""
        flags = FeatureFlags()
        
        assert flags.live_trading_mode is False
        assert flags.auto_approval is False
        assert flags.auto_approval_max_notional == 1000.0
        assert flags.new_risk_rules is False
        assert flags.strict_validation is True
        assert flags.enable_dashboard is True
        assert flags.enable_mcp_server is True
    
    def test_is_enabled(self):
        """Test is_enabled method."""
        flags = FeatureFlags(live_trading_mode=True, auto_approval=False)
        
        assert flags.is_enabled("live_trading_mode") is True
        assert flags.is_enabled("auto_approval") is False
        assert flags.is_enabled("nonexistent_flag") is False
    
    def test_set_flag(self):
        """Test setting flag at runtime."""
        flags = FeatureFlags()
        
        flags.set_flag("live_trading_mode", True)
        
        assert flags.live_trading_mode is True
        assert flags.is_enabled("live_trading_mode") is True
    
    def test_to_dict(self):
        """Test exporting flags to dictionary."""
        flags = FeatureFlags(live_trading_mode=True, auto_approval=True)
        
        data = flags.to_dict()
        
        assert data["live_trading_mode"] is True
        assert data["auto_approval"] is True
        assert data["strict_validation"] is True
        assert "auto_approval_max_notional" in data
    
    def test_from_config_file(self, tmp_path):
        """Test loading from config file."""
        config_path = tmp_path / "feature_flags.json"
        config_data = {
            "live_trading_mode": True,
            "auto_approval": True,
            "auto_approval_max_notional": 5000.0,
            "new_risk_rules": True,
        }
        
        with open(config_path, "w") as f:
            json.dump(config_data, f)
        
        flags = FeatureFlags.from_config_file(str(config_path))
        
        assert flags.live_trading_mode is True
        assert flags.auto_approval is True
        assert flags.auto_approval_max_notional == 5000.0
        assert flags.new_risk_rules is True
        assert flags.strict_validation is True  # Default
    
    def test_from_config_file_missing(self, tmp_path):
        """Test loading from missing config file returns defaults."""
        config_path = tmp_path / "nonexistent.json"
        
        flags = FeatureFlags.from_config_file(str(config_path))
        
        assert flags.live_trading_mode is False  # Default
        assert flags.auto_approval is False  # Default
    
    def test_from_config_file_invalid(self, tmp_path):
        """Test loading from invalid config file returns defaults."""
        config_path = tmp_path / "invalid.json"
        
        with open(config_path, "w") as f:
            f.write("invalid json{{{")
        
        flags = FeatureFlags.from_config_file(str(config_path))
        
        assert flags.live_trading_mode is False  # Default
    
    def test_from_env(self, monkeypatch):
        """Test loading from environment variables."""
        monkeypatch.setenv("LIVE_TRADING_MODE", "true")
        monkeypatch.setenv("AUTO_APPROVAL", "1")
        monkeypatch.setenv("AUTO_APPROVAL_MAX_NOTIONAL", "2500.0")
        monkeypatch.setenv("NEW_RISK_RULES", "yes")
        monkeypatch.setenv("STRICT_VALIDATION", "false")
        
        flags = FeatureFlags.from_env()
        
        assert flags.live_trading_mode is True
        assert flags.auto_approval is True
        assert flags.auto_approval_max_notional == 2500.0
        assert flags.new_risk_rules is True
        assert flags.strict_validation is False
    
    def test_from_env_invalid_values(self, monkeypatch):
        """Test from_env handles invalid values gracefully."""
        monkeypatch.setenv("LIVE_TRADING_MODE", "invalid")
        monkeypatch.setenv("AUTO_APPROVAL_MAX_NOTIONAL", "not_a_number")
        
        flags = FeatureFlags.from_env()
        
        assert flags.live_trading_mode is False  # Invalid bool → False
        assert flags.auto_approval_max_notional == 1000.0  # Invalid float → default
    
    def test_load_priority(self, tmp_path, monkeypatch):
        """Test load() priority: env vars > config file > defaults."""
        # Create config file
        config_path = tmp_path / "feature_flags.json"
        config_data = {
            "live_trading_mode": True,
            "auto_approval": True,
            "auto_approval_max_notional": 3000.0,
        }
        
        with open(config_path, "w") as f:
            json.dump(config_data, f)
        
        # Set env var (should override config file)
        monkeypatch.setenv("LIVE_TRADING_MODE", "false")
        
        flags = FeatureFlags.load(str(config_path))
        
        # Env var overrides config file
        assert flags.live_trading_mode is False  # From env
        # Config file values used when no env var
        assert flags.auto_approval is True  # From config
        assert flags.auto_approval_max_notional == 3000.0  # From config
        # Default used when neither env nor config
        assert flags.strict_validation is True  # Default
    
    def test_thread_safety(self):
        """Test thread safety of flag operations."""
        import threading
        
        flags = FeatureFlags()
        
        def toggle_flag():
            for _ in range(100):
                flags.set_flag("live_trading_mode", True)
                flags.set_flag("live_trading_mode", False)
        
        threads = [threading.Thread(target=toggle_flag) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should not crash (final value may be True or False)
        assert isinstance(flags.live_trading_mode, bool)


class TestGlobalFeatureFlags:
    """Test global feature flags singleton."""
    
    def test_get_feature_flags_singleton(self):
        """Test get_feature_flags returns same instance."""
        flags1 = get_feature_flags()
        flags2 = get_feature_flags()
        
        assert flags1 is flags2
    
    def test_set_feature_flags(self):
        """Test setting custom feature flags."""
        custom_flags = FeatureFlags(live_trading_mode=True)
        
        set_feature_flags(custom_flags)
        
        retrieved = get_feature_flags()
        assert retrieved is custom_flags
        assert retrieved.live_trading_mode is True
    
    def test_flags_persist_across_calls(self):
        """Test flags persist across multiple calls."""
        flags = get_feature_flags()
        
        flags.set_flag("auto_approval", True)
        
        flags2 = get_feature_flags()
        
        # Should have same state
        assert flags2.auto_approval is True
