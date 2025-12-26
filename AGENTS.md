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

# Run tests
pytest -v

# Run tests with coverage
pytest --cov=packages --cov=apps --cov-report=html
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

## Resources

- [ROADMAP.md](ROADMAP.md) - Full development roadmap
- [docs/threat-model.md](docs/threat-model.md) - Security considerations
- [docs/adr/](docs/adr/) - Architecture Decision Records
- [IBKR API Docs](https://interactivebrokers.github.io/)
- [MCP Specification](https://modelcontextprotocol.io/)

---

**Remember**: Safety first. When in doubt, REJECT and log.
