"""
Unit tests for kill switch module.

Tests cover:
- Singleton pattern
- State persistence
- Environment variable override
- Thread safety
- Activation/deactivation
- check_or_raise functionality
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from time import sleep

import pytest

from packages.kill_switch import KillSwitch, KillSwitchState, get_kill_switch


@pytest.fixture
def temp_state_file(tmp_path):
    """Create temporary state file."""
    return str(tmp_path / ".kill_switch_test_state")


@pytest.fixture
def clean_kill_switch(temp_state_file):
    """Create fresh kill switch instance for testing."""
    # Clear singleton
    KillSwitch._instance = None
    
    # Clear environment variable
    if "KILL_SWITCH_ENABLED" in os.environ:
        del os.environ["KILL_SWITCH_ENABLED"]
    
    # Create new instance
    ks = KillSwitch(state_file=temp_state_file)
    yield ks
    
    # Cleanup
    KillSwitch._instance = None
    if Path(temp_state_file).exists():
        Path(temp_state_file).unlink()


def test_kill_switch_singleton():
    """Test that KillSwitch is a singleton."""
    KillSwitch._instance = None
    
    ks1 = get_kill_switch()
    ks2 = get_kill_switch()
    
    assert ks1 is ks2


def test_kill_switch_default_disabled(clean_kill_switch):
    """Test that kill switch is disabled by default."""
    assert not clean_kill_switch.is_enabled()
    
    state = clean_kill_switch.get_state()
    assert not state.enabled
    assert state.activated_at is None
    assert state.activated_by is None
    assert state.reason is None


def test_kill_switch_activate(clean_kill_switch):
    """Test kill switch activation."""
    state = clean_kill_switch.activate(
        activated_by="test",
        reason="Testing activation"
    )
    
    assert state.enabled
    assert state.activated_by == "test"
    assert state.reason == "Testing activation"
    assert state.activated_at is not None
    assert isinstance(state.activated_at, datetime)
    
    assert clean_kill_switch.is_enabled()


def test_kill_switch_deactivate(clean_kill_switch):
    """Test kill switch deactivation."""
    # First activate
    clean_kill_switch.activate(activated_by="test", reason="Test")
    assert clean_kill_switch.is_enabled()
    
    # Then deactivate
    state = clean_kill_switch.deactivate(deactivated_by="test")
    
    assert not state.enabled
    assert not clean_kill_switch.is_enabled()
    
    # History should be preserved
    assert state.activated_at is not None
    assert state.activated_by == "test"


def test_kill_switch_multiple_activations(clean_kill_switch):
    """Test that multiple activations don't override first activation."""
    state1 = clean_kill_switch.activate(activated_by="admin", reason="First activation")
    sleep(0.01)  # Ensure different timestamps
    
    state2 = clean_kill_switch.activate(activated_by="api", reason="Second activation")
    
    # Should keep first activation details
    assert state1.activated_at == state2.activated_at
    assert state2.activated_by == "admin"
    assert state2.reason == "First activation"


def test_kill_switch_check_or_raise_disabled(clean_kill_switch):
    """Test check_or_raise when kill switch is disabled."""
    # Should not raise
    clean_kill_switch.check_or_raise("test_operation")


def test_kill_switch_check_or_raise_enabled(clean_kill_switch):
    """Test check_or_raise when kill switch is enabled."""
    clean_kill_switch.activate(activated_by="test", reason="Testing")
    
    with pytest.raises(RuntimeError) as exc_info:
        clean_kill_switch.check_or_raise("test_operation")
    
    error_message = str(exc_info.value)
    assert "Kill switch is active" in error_message
    assert "test_operation blocked" in error_message
    assert "test" in error_message
    assert "Testing" in error_message


def test_kill_switch_state_persistence(temp_state_file):
    """Test that kill switch state persists across instances."""
    # Clear singleton
    KillSwitch._instance = None
    
    # Create first instance and activate
    ks1 = KillSwitch(state_file=temp_state_file)
    ks1.activate(activated_by="test", reason="Persistence test")
    activated_at = ks1.get_state().activated_at
    
    # Clear singleton
    KillSwitch._instance = None
    
    # Create second instance - should load persisted state
    ks2 = KillSwitch(state_file=temp_state_file)
    
    assert ks2.is_enabled()
    state = ks2.get_state()
    assert state.enabled
    assert state.activated_by == "test"
    assert state.reason == "Persistence test"
    assert state.activated_at == activated_at
    
    # Cleanup
    Path(temp_state_file).unlink()


def test_kill_switch_environment_override(temp_state_file):
    """Test that environment variable overrides state."""
    # Clear singleton
    KillSwitch._instance = None
    
    # Set environment variable
    os.environ["KILL_SWITCH_ENABLED"] = "true"
    
    try:
        ks = KillSwitch(state_file=temp_state_file)
        
        # Should be enabled due to environment variable
        assert ks.is_enabled()
        
        state = ks.get_state()
        assert state.enabled
        assert state.activated_by == "environment_variable"
        
    finally:
        del os.environ["KILL_SWITCH_ENABLED"]
        KillSwitch._instance = None
        if Path(temp_state_file).exists():
            Path(temp_state_file).unlink()


def test_kill_switch_cannot_deactivate_env_override(temp_state_file):
    """Test that kill switch cannot be deactivated when env var is set."""
    # Clear singleton
    KillSwitch._instance = None
    
    # Set environment variable
    os.environ["KILL_SWITCH_ENABLED"] = "true"
    
    try:
        ks = KillSwitch(state_file=temp_state_file)
        assert ks.is_enabled()
        
        # Try to deactivate - should raise
        with pytest.raises(RuntimeError) as exc_info:
            ks.deactivate(deactivated_by="test")
        
        assert "environment variable" in str(exc_info.value).lower()
        assert ks.is_enabled()  # Still enabled
        
    finally:
        del os.environ["KILL_SWITCH_ENABLED"]
        KillSwitch._instance = None
        if Path(temp_state_file).exists():
            Path(temp_state_file).unlink()


def test_kill_switch_thread_safety(clean_kill_switch):
    """Test that kill switch is thread-safe."""
    results = []
    
    def activate_thread():
        state = clean_kill_switch.activate(activated_by="thread", reason="Thread test")
        results.append(state.activated_at)
    
    threads = [Thread(target=activate_thread) for _ in range(10)]
    
    for t in threads:
        t.start()
    
    for t in threads:
        t.join()
    
    # All threads should get the same activation time (first wins)
    assert len(set(results)) == 1
    assert clean_kill_switch.is_enabled()


def test_kill_switch_state_file_corruption(temp_state_file):
    """Test that kill switch handles corrupted state file gracefully."""
    # Clear singleton
    KillSwitch._instance = None
    
    # Create corrupted state file
    with open(temp_state_file, "w") as f:
        f.write("corrupted json {{{")
    
    # Should create fresh state without crashing
    ks = KillSwitch(state_file=temp_state_file)
    assert not ks.is_enabled()
    
    # Cleanup
    KillSwitch._instance = None
    Path(temp_state_file).unlink()


def test_kill_switch_get_state_returns_copy(clean_kill_switch):
    """Test that get_state returns a copy, not reference."""
    state1 = clean_kill_switch.get_state()
    state1.enabled = True  # Modify copy
    
    # Original should not be affected
    state2 = clean_kill_switch.get_state()
    assert not state2.enabled


def test_kill_switch_state_model():
    """Test KillSwitchState model validation."""
    state = KillSwitchState(
        enabled=True,
        activated_at=datetime.now(timezone.utc),
        activated_by="test",
        reason="Test reason"
    )
    
    assert state.enabled
    assert state.activated_by == "test"
    assert state.reason == "Test reason"
    assert isinstance(state.activated_at, datetime)
