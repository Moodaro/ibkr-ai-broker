# Testing Guide

## Overview

Il progetto ha **761 test** suddivisi in unit test e integration test. I test di integrazione richiedono una connessione IBKR attiva e sono marcati con `@pytest.mark.integration`.

## Test Statistics

- **Total tests**: 761
- **Unit tests**: 743 (97.6%)
- **Integration tests**: 18 (2.4%)
- **Current pass rate**: 99.7% (743/743 unit tests)

## Running Tests

### Unit Tests Only (Default - Recommended)

```bash
# Run all unit tests (no IBKR connection required)
pytest -v -m "not integration"

# With coverage report
pytest --cov=packages --cov=apps --cov-report=html -m "not integration"

# Quick smoke test
pytest --tb=no -q -m "not integration"
```

### Integration Tests (Requires IBKR)

Integration tests require IBKR Gateway or TWS running on port 7497 (paper trading mode).

```bash
# Run integration tests only
pytest -m integration -v

# Run specific integration test file
pytest tests/test_ibkr_real.py -v

# Run ALL tests (unit + integration)
pytest -v
```

### Test Markers

Il progetto usa i seguenti pytest markers:

- `@pytest.mark.integration`: Test che richiedono connessione IBKR live
- `@pytest.mark.slow`: Test lenti (non ancora implementato)
- `@pytest.mark.requires_ibkr`: Alias per integration (deprecato)

## Integration Test Files

### test_ibkr_real.py (18 tests)

Test per IBKRBrokerAdapter che richiedono connessione broker live:

- `test_connection`: Test connessione IBKR
- `test_get_portfolio`: Recupero portfolio
- `test_get_positions`: Recupero posizioni
- `test_get_market_snapshot`: Dati mercato real-time
- `test_get_market_bars`: Dati storici OHLCV
- `test_submit_order_readonly`: Verifica readonly mode
- `test_order_submission`: Invio ordine reale
- `test_get_order_status`: Stato ordine
- Altri test per search, resolve, cancel, ecc.

**Prerequisiti**:
1. IBKR Gateway o TWS in esecuzione
2. Porta 7497 aperta (paper trading)
3. Account paper trading configurato
4. Permessi API abilitati

## CI/CD Configuration

I test di integrazione sono automaticamente esclusi nelle pipeline CI/CD:

```yaml
# .github/workflows/ci.yml
- name: Run tests
  run: pytest -v -m "not integration" --cov
```

## Troubleshooting

### "Circuit breaker OPEN" Errors

Se vedi errori tipo `ConnectionError: Circuit breaker OPEN - too many connection failures`:

- **Causa**: Nessun IBKR Gateway/TWS attivo sulla porta 7497
- **Soluzione**: I test sono già marcati come `integration`, usa `-m "not integration"`

### Flaky Tests

Il test `test_live_config.py::TestLiveConfigManager::test_can_submit_live_order` può essere flaky quando eseguito con l'intera suite a causa di stato globale del singleton `LiveConfigManager`.

**Workaround**:
```bash
# Eseguilo singolarmente
pytest tests/test_live_config.py::TestLiveConfigManager::test_can_submit_live_order -v
```

### Test Isolation

I test usano fixture per garantire isolamento:

```python
@pytest.fixture
def clean_env():
    """Clean environment variables before each test."""
    # Reset singleton state
    packages.live_config._live_config_manager = None
```

## Writing New Tests

### Unit Tests

```python
def test_my_feature():
    """Test description."""
    # Arrange
    input_data = {...}
    
    # Act
    result = my_function(input_data)
    
    # Assert
    assert result.success is True
```

### Integration Tests

```python
import pytest

# Mark all tests in file as integration
pytestmark = pytest.mark.integration

def test_broker_integration(adapter):
    """Test with real IBKR connection."""
    adapter.connect()
    assert adapter.is_connected()
```

## Best Practices

1. **Keep tests fast**: Unit tests dovrebbero completare in < 5 secondi
2. **Mock external dependencies**: Usa `FakeBrokerAdapter` per unit test
3. **Use fixtures**: Riutilizza setup comuni
4. **Test one thing**: Un test, un concetto
5. **Clear names**: `test_should_reject_when_position_exceeds_limit`
6. **Add docstrings**: Spiega cosa testa e perché

## Coverage Goals

- **Packages**: > 80% coverage
- **Apps**: > 60% coverage
- **Critical paths**: 100% coverage (risk_engine, order_submission)

```bash
# Generate HTML coverage report
pytest --cov=packages --cov=apps --cov-report=html -m "not integration"

# Open in browser
open htmlcov/index.html  # macOS
start htmlcov/index.html  # Windows
```

## Test Failure Analysis

### Recent Fixes (Sprint 7)

**Fixed Bugs**:
1. ✅ **R9 Volatility Formula**: Rimossa divisione per sqrt(252) - 7 test
2. ✅ **YAML Corruption**: File risk_policy.yml ricreato - system-wide fix
3. ✅ **EventType.CUSTOM**: Sostituito con MARKET_SNAPSHOT_TAKEN - 5 test
4. ✅ **Obsolete Keys**: Aggiornate chiavi trading_hours nei test - 1 test

**Result**: Pass rate aumentato da 95.8% → 99.7% (743/743 unit tests)

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [AGENTS.md](../AGENTS.md) - Developer guide con pattern di testing

---

**Last updated**: 2025-12-27 (Sprint 7 - Test Suite Cleanup)
