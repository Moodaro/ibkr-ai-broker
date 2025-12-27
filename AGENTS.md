# AGENTS.md — Trading Assistant (IBKR + LLM + MCP)

## Project overview

- **Goal**: IBKR paper trading assistant. LLM proposes orders; deterministic gate validates/simulates/approves; two-step commit.
- **Safety**: NO direct LLM-to-broker writes. All writes go through RiskGate and explicit approval.
- **Stack**: Python 3.12+, FastAPI, Pydantic v2, pytest, ruff, PostgreSQL (SQLite in dev)

## Commands

### Setup
```bash
# Install dependencies (using uv - recommended)
uv sync

# Or using pip
pip install -e .

# Install pre-commit hooks
pre-commit install
```

### Development
```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
pyright
# or
mypy .

# Run tests (excluding integration tests that require IBKR connection)
pytest -v -m "not integration"

# Run tests with coverage
pytest --cov=packages --cov=apps --cov-report=html -m "not integration"

# Run integration tests (requires IBKR Gateway/TWS on port 7497)
pytest -m integration -v

# Run ALL tests including integration
pytest -v
```

### Run services
```bash
# Start database
docker-compose up -d

# Run Assistant API
uvicorn apps.assistant_api.main:app --reload --port 8000

# Run MCP Server
python apps/mcp_server/main.py

# Run Dashboard
streamlit run apps/dashboard/main.py
# or
uvicorn apps.dashboard.main:app --reload --port 8080
```

## Code style

- **Python 3.12+** with type hints everywhere
- Use **Pydantic models** for all IO (API requests, responses, configs)
- No business logic in FastAPI routes; keep in `packages/`
- Use **Protocol** for interfaces (e.g., `BrokerAdapter`)
- Prefer **composition over inheritance**
- Keep functions small and focused (max 50 lines)

## Testing rules

- **Every new feature** must include unit tests
- **Risk rules** must include property-based tests (Hypothesis) when feasible
- Add integration tests using mocked broker responses (`FakeBrokerAdapter`)
- Test coverage target: **>80%** for packages, **>60%** for apps
- Use `pytest.mark.integration` for integration tests
- Use `pytest.mark.slow` for slow tests

## Boundaries (hard rules)

⚠️ **CRITICAL SAFETY RULES** ⚠️

1. **Never submit live orders** unless `ENV=live` AND approval step passes
2. **Never store secrets** in repo. Use environment variables or secret manager
3. Any function named `submit_*` or `execute_*` **MUST** require an explicit `ApprovalToken`
4. All trade-writing paths **MUST** go through:
   - Schema validation
   - Simulation
   - Risk Gate evaluation
   - Approval/commit step
5. **Default to REJECT** in risk engine
6. **Kill switch** must always be available and tested

## Security

- Treat all user inputs + LLM outputs as **untrusted**
- Validate JSON strictly against schemas (no `extra="allow"`)
- Log all decisions as **AuditEvent** with correlation ID
- Never log sensitive data (credentials, full account details)
- Use **structured logging** (structlog or JSON format)
- Sanitize all outputs shown to users

## Architecture patterns

### Adapter pattern
```python
from typing import Protocol

class BrokerAdapter(Protocol):
    def get_portfolio(self, account_id: str) -> Portfolio: ...
    def submit_order(self, intent: OrderIntent, token: ApprovalToken) -> str: ...
```

### Two-step commit pattern
```python
# Step 1: Propose and simulate
intent = create_order_intent(...)
sim_result = simulator.simulate(portfolio, intent)
risk_decision = risk_engine.evaluate(portfolio, intent, sim_result)

# Step 2: Request approval (only if risk approved)
if risk_decision.decision == Decision.APPROVE:
    approval_id = approval_service.request(intent, sim_result, risk_decision)
    # Wait for user approval...
    
# Step 3: Submit (only with valid token)
if approval_token := approval_service.get_token(approval_id):
    broker.submit_order(intent, approval_token)
```

### Order cancellation pattern (gated)
```python
# Step 1: Request cancellation
cancel_intent = OrderCancelIntent(
    account_id="DU12345",
    proposal_id="abc123" # OR broker_order_id="12345"
    reason="Market conditions changed"
)
cancel_approval_id = f"cancel_{uuid.uuid4().hex[:12]}"

# Emit audit event
audit_store.append_event(AuditEvent(
    event_type=EventType.ORDER_CANCEL_REQUESTED,
    correlation_id=correlation_id,
    data={"approval_id": cancel_approval_id, "intent": cancel_intent.model_dump()}
))

# Step 2: Wait for human approval/denial
# User approves via dashboard or API

# Step 3: Execute cancellation (only if approved)
if action == "grant":
    try:
        broker.cancel_order(broker_order_id)
        audit_store.append_event(AuditEvent(
            event_type=EventType.ORDER_CANCEL_EXECUTED,
            data={"broker_order_id": broker_order_id}
        ))
    except Exception as e:
        audit_store.append_event(AuditEvent(
            event_type=EventType.ORDER_CANCEL_FAILED,
            data={"error": str(e)}
        ))
```

### Audit event pattern
```python
from packages.audit_store import AuditStore, AuditEvent, EventType

audit_store = AuditStore("data/audit.db")
audit_store.append_event(AuditEvent(
    event_type=EventType.ORDER_PROPOSED,
    correlation_id=correlation_id,
    timestamp=datetime.utcnow(),
    data={"intent": intent.model_dump(), "reason": reason}
))
```

### Background scheduler pattern
```python
from packages.flex_query.scheduler import FlexQueryScheduler
from packages.flex_query.service import FlexQueryService

# Initialize scheduler with service and audit store
scheduler = FlexQueryScheduler(
    service=flex_query_service,
    audit_store=audit_store,
    timezone="UTC"  # or "America/New_York", etc.
)

# Start scheduler (only schedules enabled + auto_schedule queries)
scheduler.start()

# ... application runs, queries execute on cron schedule ...

# Stop scheduler on shutdown
scheduler.stop(wait=True)  # wait for running jobs to complete
```

**Flex Query Configuration** (JSON):
```json
{
  "query_id": "123456",
  "name": "Daily Trades",
  "query_type": "TRADES",
  "enabled": true,
  "auto_schedule": true,
  "schedule_cron": "0 9 * * *",  // 9 AM daily
  "retention_days": 90
}
```

**Cron Expression Format**:
- **5 fields**: `minute hour day month weekday` (e.g., `0 9 * * *`)
- **6 fields**: `second minute hour day month weekday` (e.g., `0 0 9 * * *`)
- Examples:

### Advanced risk engine integration pattern (R9-R12)
```python
from packages.risk_engine import (
    RiskEngine,
    AdvancedRiskEngine,
    AdvancedRiskLimits,
    VolatilityMetrics,
)

# Initialize advanced risk engine with R9-R12 limits
advanced_limits = AdvancedRiskLimits(
    # R9: Volatility-aware position sizing
    max_position_volatility=0.02,  # 2% max portfolio risk per position
    min_position_size=Decimal("100"),
    max_position_size=Decimal("50000"),
    volatility_scaling_enabled=True,
    
    # R10: Correlation limits (placeholder, not yet implemented)
    max_correlation_exposure=0.50,
    correlation_enabled=False,
    
    # R11: Drawdown protection
    max_drawdown_pct=10.0,  # Halt trading if 10% drawdown
    enable_drawdown_halt=True,
    
    # R12: Time-of-day restrictions
    avoid_market_open_minutes=10,  # Skip first 10 min
    avoid_market_close_minutes=10,  # Skip last 10 min
)

advanced_engine = AdvancedRiskEngine(
    limits=advanced_limits,
    high_water_mark=portfolio.total_value,  # Track HWM for drawdown
    market_open_time="09:30",
    market_close_time="16:00",
)

# Integrate with basic RiskEngine (R1-R8)
engine = RiskEngine(
    limits=basic_limits,  # R1-R8 configuration
    trading_hours=trading_hours,
    advanced_engine=advanced_engine,  # Optional: None for R1-R8 only
)

# Evaluate with volatility data
volatility_metrics = VolatilityMetrics(
    symbol_volatility=0.15,  # 15% annual volatility for symbol
    beta=1.2,                # Optional: beta vs market
    market_volatility=0.18,  # Optional: market volatility
)

decision = engine.evaluate(
    intent=intent,
    portfolio=portfolio,
    simulation=simulation,
    current_time=datetime.now(tz=timezone.utc),
    volatility_metrics=volatility_metrics,  # Optional: None skips R9
)

# Check result
if decision.decision == Decision.REJECT:
    # R1-R8 or R9-R12 rejected
    violated = ", ".join(decision.violated_rules)
    print(f"REJECTED: {decision.reason} (rules: {violated})")
else:
    # All checks passed
    print(f"APPROVED: {decision.reason}")
    print(f"Metrics: {decision.metrics}")
```

**Backward Compatibility**:
```python
# Works without advanced engine (R1-R8 only)
basic_engine = RiskEngine(
    limits=basic_limits,
    trading_hours=trading_hours,
    # advanced_engine=None by default
)

decision = basic_engine.evaluate(
    intent=intent,
    portfolio=portfolio,
    simulation=simulation,
    # volatility_metrics not needed
)
```

**Configuration** (risk_policy.yml):
```yaml
advanced_rules:
  volatility_sizing:
    enabled: true
    max_position_volatility: 0.02
    min_position_size: 100.00
    max_position_size: 50000.00
  
  drawdown_protection:
    enabled: true
    max_drawdown_pct: 10.0
    enable_drawdown_halt: true
  
  time_restrictions:
    enabled: true
    avoid_market_open_minutes: 10
    avoid_market_close_minutes: 10
```

### Volatility data provider pattern
```python
from packages.volatility_provider import (
    MockVolatilityProvider,
    HistoricalVolatilityProvider,
    VolatilityService,
)
from packages.broker_ibkr import FakeBrokerAdapter, IBKRBrokerAdapter

# Option 1: Mock provider (for testing)
mock_provider = MockVolatilityProvider(
    volatility_map={
        "AAPL": 0.18,  # 18%
        "TSLA": 0.50,  # 50%
    },
    default_volatility=0.20,  # 20% for unknown symbols
    market_volatility=0.15,  # 15% VIX equivalent
)

vol_data = mock_provider.get_volatility("AAPL")
print(f"AAPL volatility: {vol_data.realized_volatility}")  # 0.18

# Option 2: Historical provider (production)
broker = IBKRBrokerAdapter()
historical_provider = HistoricalVolatilityProvider(
    broker_adapter=broker,
    annualization_factor=252,  # Trading days per year
)

vol_data = historical_provider.get_volatility("AAPL", lookback_days=30)
# Calculates realized volatility from last 30 days of price data

# Option 3: Service with caching and fallback
vol_service = VolatilityService(
    primary_provider=historical_provider,
    fallback_provider=mock_provider,
    cache_ttl_seconds=3600,  # 1 hour cache
)

# Fetches from primary, falls back to mock if unavailable, caches result
vol_data = vol_service.get_volatility("AAPL")

# Check cache stats
stats = vol_service.get_cache_stats()
print(f"Cache hit rate: {stats['hit_rate_pct']}%")
print(f"Fallback uses: {stats['fallback_uses']}")

# Convert to VolatilityMetrics for RiskEngine
from packages.risk_engine import VolatilityMetrics

volatility_metrics = VolatilityMetrics(
    symbol_volatility=vol_data.realized_volatility,
    market_volatility=vol_data.market_volatility,
    beta=vol_data.beta,
)

# Use with RiskEngine (R9 volatility-aware sizing)
decision = risk_engine.evaluate(
    intent=intent,
    portfolio=portfolio,
    simulation=simulation,
    volatility_metrics=volatility_metrics,  # Enables R9 check
)
```

**Configuration** (risk_policy.yml):
```yaml
volatility_provider:
  provider_type: "historical"  # or "mock" for testing
  fallback_provider: "mock"
  fallback_default_volatility: 0.25
  
  cache_enabled: true
  cache_ttl_seconds: 3600  # 1 hour
  
  historical:
    lookback_days: 30
    annualization_factor: 252
    min_data_points: 10
  
  mock:
    default_volatility: 0.20
    market_volatility: 0.15
    symbol_overrides:
      AAPL: 0.18
      TSLA: 0.50
```

### MCP parameter validation pattern
```python
from packages.mcp_security import validate_schema
from packages.mcp_security.schemas import RequestApprovalSchema

# Apply decorator to any MCP tool handler
@validate_schema(RequestApprovalSchema)
async def handle_request_approval(arguments: dict[str, Any]):
    # Arguments already validated against schema
    # - Type safety enforced (Decimal for money, str for text)
    # - Unknown fields rejected (extra="forbid")
    # - Pattern matching applied (regex for symbols, sides)
    # - Range validation checked (gt=0 for quantities)
    pass
```

**Pydantic Schema** (example):
```python
from packages.mcp_security import StrictBaseModel

class RequestApprovalSchema(StrictBaseModel):
    """Schema rejects unknown fields automatically."""
    account_id: str = Field(..., min_length=1)
    symbol: str = Field(..., pattern=r"^[A-Z]{1,5}$")
    side: str = Field(..., pattern=r"^(BUY|SELL)$")
    quantity: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=10)
```

**Security Benefits**:
- **Parameter injection prevention**: Unknown fields rejected
- **Type safety**: Decimal for money (prevents float precision issues)
- **Enum validation**: Fixed choices (BUY|SELL, MKT|LMT|STP|STP_LMT)
- **Range checking**: Positive quantities/prices enforced
- **Pattern matching**: Symbol format validated
- **Audit trail**: Validation errors logged automatically

### MCP security hardening pattern (Epic E)
```python
from packages.mcp_security import get_rate_limiter, get_redactor, get_policy
from packages.mcp_security import RateLimitConfig, RedactionConfig

# Initialize security services (in main())
rate_limiter = get_rate_limiter(RateLimitConfig())
redactor = get_redactor(RedactionConfig())
policy = get_policy()  # Loads from MCP_POLICY_PATH env var or uses defaults

# In call_tool handler
@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    session_id = arguments.get("session_id", str(uuid.uuid4()))
    
    # 1. Policy check (allowlist + parameter validation)
    allowed, reason = policy.check_tool_allowed(name, session_id, arguments)
    if not allowed:
        return error_response(f"Policy denied: {reason}")
    
    # 2. Rate limit check (per-tool + per-session + global)
    rate_ok, rate_reason = rate_limiter.check_rate_limit(name, session_id)
    if not rate_ok:
        return error_response(f"Rate limit: {rate_reason}")
    
    # 3. Execute tool
    result = await execute_tool(name, arguments)
    
    # 4. Record successful call
    policy.record_tool_call(name, session_id)
    
    # 5. Redact sensitive data from output
    for content in result:
        if content.type == "text":
            data = json.loads(content.text)
            redacted = redactor.redact(data)
            content.text = json.dumps(redacted)
    
    return result
```

**Policy Configuration** (config/mcp_policy.json):
```json
{
  "rules": [
    {
      "tool_name": "get_portfolio",
      "action": "allow"
    },
    {
      "tool_name": "run_flex_query",
      "action": "allow",
      "max_calls_per_session": 10
    },
    {
      "tool_name": "request_approval",
      "action": "allow",
      "max_calls_per_session": 50,
      "denied_parameters": ["bypass_risk"]
    }
  ]
}
```

**Security Features**:
- **Rate limiting**: 60/min per-tool, 100/min per-session, 1000/min global
- **Circuit breaker**: 100 consecutive rejections → 300s timeout
- **Policy enforcement**: Tool allowlist, parameter validation, session restrictions
- **Output redaction**: PII/sensitive data (account IDs → DU****56, tokens → ***)
- **Audit logging**: All tool calls, rejections, and errors logged
- **Fail-safe defaults**: Unknown tools denied, unknown parameters rejected

### Background scheduler pattern
```python
from packages.flex_query.scheduler import FlexQueryScheduler
from packages.flex_query.service import FlexQueryService

# Initialize scheduler with service and audit store
scheduler = FlexQueryScheduler(
    service=flex_query_service,
    audit_store=audit_store,
    timezone="UTC"  # or "America/New_York", etc.
)

# Start scheduler (only schedules enabled + auto_schedule queries)
scheduler.start()

# ... application runs, queries execute on cron schedule ...

# Stop scheduler on shutdown
scheduler.stop(wait=True)  # wait for running jobs to complete
```

**Flex Query Configuration** (JSON):
```json
{
  "query_id": "123456",
  "name": "Daily Trades",
  "query_type": "TRADES",
  "enabled": true,
  "auto_schedule": true,
  "schedule_cron": "0 9 * * *",  // 9 AM daily
  "retention_days": 90
}
```

**Cron Expression Format**:
- **5 fields**: `minute hour day month weekday` (e.g., `0 9 * * *`)
- **6 fields**: `second minute hour day month weekday` (e.g., `0 0 9 * * *`)
- Examples:
  - `0 9 * * *` - Every day at 9:00 AM
  - `30 14 * * 1-5` - Weekdays at 2:30 PM
  - `0 0 1 * *` - First day of month at midnight
  - `*/15 * * * *` - Every 15 minutes

## Project structure

```
.
├── apps/                    # Runnable applications
│   ├── assistant_api/      # FastAPI orchestrator
│   ├── mcp_server/         # MCP tool server
│   └── dashboard/          # Approval UI
├── packages/               # Reusable libraries
│   ├── broker_ibkr/       # IBKR adapter
│   ├── risk_engine/       # Risk gate
│   ├── trade_sim/         # Order simulator
│   ├── schemas/           # Pydantic models
│   └── audit_store/       # Event store
├── tests/                 # Cross-package tests
├── infra/                 # Docker, k8s, etc.
└── docs/                  # Architecture docs
```

## Development workflow

1. **Create feature branch**: `git checkout -b feature/risk-rule-R1`
2. **Write failing test**: test-driven development
3. **Implement feature**: keep PRs small (<300 LOC)
4. **Run checks**: `ruff check . && pytest`
5. **Commit with pre-commit**: hooks run automatically
6. **Open PR**: use template, link issues
7. **Review**: at least 1 approval required
8. **Merge**: squash and merge

## Environment variables

Required:

- `IBKR_HOST` - IBKR gateway host (default: localhost)
- `IBKR_PORT` - IBKR gateway port (default: 7497 for paper)
- `IBKR_CLIENT_ID` - Client ID for connection
- `DATABASE_URL` - Postgres connection string
- `ENV` - Environment: `dev`, `paper`, `live` (default: dev)

Optional:

- `LOG_LEVEL` - Logging level (default: INFO)
- `KILL_SWITCH_ENABLED` - Force kill switch (default: false)
- `RISK_POLICY_PATH` - Path to risk policy YAML
- `FLEX_QUERY_STORAGE` - Path for Flex Query reports (default: ./data/flex_reports)
- `FLEX_QUERY_CONFIG` - Path to Flex Query configuration JSON (optional)
- `SCHEDULER_TIMEZONE` - Timezone for cron scheduling (default: UTC)

## Troubleshooting

### Tests fail with connection error
- Ensure `docker-compose up -d` is running
- Check `DATABASE_URL` is set correctly

### IBKR connection refused
- Ensure TWS or IB Gateway is running
- Check paper trading mode is enabled
- Verify port 7497 (paper) or 7496 (live) is correct

### Pre-commit hooks fail
- Run `ruff format .` to auto-fix formatting
- Run `ruff check . --fix` to auto-fix linting issues

### Type check errors
- Ensure all dependencies are installed: `uv sync`
- Check `pyrightconfig.json` or `mypy.ini` settings

## Live Trading Patterns

### Pre-flight validation pattern
```python
from pathlib import Path

# Check environment
import os
env = os.getenv("ENV", "dev")
if env == "live":
    # Run live readiness checks
    import pytest
    result = pytest.main([
        "tests/test_live_readiness.py",
        "-v",
        "--tb=short",
    ])
    if result != 0:
        raise RuntimeError("Live readiness checks failed - DO NOT DEPLOY")
```

### Kill switch pattern
```python
from packages.kill_switch import get_kill_switch

# Get global kill switch instance
kill_switch = get_kill_switch()

# Check before any order submission
if kill_switch.is_enabled():
    raise RuntimeError("Kill switch active - trading halted")

# Or use check_or_raise (raises with detailed message)
kill_switch.check_or_raise("order_submission")
```

### Health monitoring pattern
```python
from packages.health_monitor import (
    HealthMonitor,
    create_kill_switch_check,
    create_broker_connection_check,
    create_disk_space_check,
)
from packages.audit_store import AuditStore
from packages.kill_switch import get_kill_switch

# Setup health monitor
audit_store = AuditStore("data/audit.db")
monitor = HealthMonitor(audit_store)

# Register checks
monitor.register_health_check(
    "kill_switch",
    create_kill_switch_check(get_kill_switch()),
)
monitor.register_health_check(
    "broker",
    create_broker_connection_check(broker, account_id),
)
monitor.register_health_check(
    "disk_space",
    create_disk_space_check(min_gb=5.0),
)

# Run all checks
checks = monitor.run_health_checks()
overall_status = monitor.get_overall_status()

if overall_status == HealthStatus.UNHEALTHY:
    # Trigger kill switch or alert
    pass
```

### Alert condition pattern
```python
from packages.health_monitor import AlertCondition, AlertSeverity

# Define custom alert condition
high_error_rate = AlertCondition(
    name="high_error_rate",
    check_function=lambda: error_count > 10,  # Your logic
    severity=AlertSeverity.CRITICAL,
    message_template="Error rate exceeded threshold",
    cooldown_seconds=300,  # 5 min between alerts
)

monitor.register_alert_condition(high_error_rate)

# Check alerts periodically
alerts = monitor.check_alerts()
for alert in alerts:
    # Send notification (email, SMS, etc.)
    send_alert(alert)
```

### Live deployment workflow
```bash
# 1. Run pre-flight checklist
pytest tests/test_live_readiness.py -v

# 2. Review LIVE_TRADING.md procedures
cat docs/LIVE_TRADING.md

# 3. Set environment
export ENV=live
export IBKR_PORT=7496  # Live port (7497 = paper)

# 4. Start services with health monitoring
docker-compose up -d

# 5. Verify kill switch is ACTIVE
python -c "from packages.kill_switch import get_kill_switch; ks = get_kill_switch(); print(f'Kill switch: {'ACTIVE' if not ks.is_enabled() else 'TRIGGERED'}')"

# 6. Test minimum trade (1 share or $100)
# Use dashboard or API to submit test order
# Verify approval flow, execution, audit logging

# 7. Monitor continuously
# Open dashboard: http://localhost:8080
# Watch audit log: tail -f data/audit.db
```

### Emergency kill switch activation
```python
from packages.kill_switch import get_kill_switch

# Activate kill switch
kill_switch = get_kill_switch()
kill_switch.activate(
    reason="Emergency stop - unexpected behavior",
    activated_by="operator_name",
)

# All subsequent order submissions will be blocked
# Reset only after investigation:
# kill_switch.deactivate(deactivated_by="operator_name")
```

**Critical Rules**:
1. Never deploy to live without passing `test_live_readiness.py`
2. Always verify kill switch is accessible before trading
3. Monitor health checks continuously (every 60 seconds recommended)
4. Review LIVE_TRADING.md emergency procedures before going live
5. Keep dashboard open during live trading hours
6. Test kill switch activation/deactivation in paper mode first

## Resources

- [ROADMAP.md](ROADMAP.md) - Full development roadmap
- [docs/LIVE_TRADING.md](docs/LIVE_TRADING.md) - Live trading operations guide **← READ BEFORE GOING LIVE**
- [docs/threat-model.md](docs/threat-model.md) - Security considerations
- [docs/adr/](docs/adr/) - Architecture Decision Records
- [IBKR API Docs](https://interactivebrokers.github.io/)
- [MCP Specification](https://modelcontextprotocol.io/)

---

**Remember**: Safety first. When in doubt, REJECT and log.
