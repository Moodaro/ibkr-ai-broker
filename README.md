# IBKR AI Broker

> **IBKR Paper Trading Assistant with LLM + Risk Gate + MCP**

A safe, auditable trading assistant that uses Interactive Brokers for paper trading, with LLM-powered order proposals, deterministic risk validation, and two-step commit approval workflow.

⚠️ **SAFETY FIRST**: This system is designed for paper trading with multiple safety layers. Live trading requires extensive testing and explicit approval gates.

## 🎯 Project Goals

- **LLM as Advisor**: AI proposes trades in structured format
- **Deterministic Risk Gate**: Code validates, simulates, and approves
- **Human Authority**: Explicit approval required for all trades
- **Complete Audit Trail**: Every decision is logged and reconstructible
- **Safety by Design**: Multiple layers prevent accidental execution

## 🏗️ Architecture

```
┌─────────────┐
│   User/LLM  │
└──────┬──────┘
       │ propose
       ▼
┌─────────────────┐
│ Assistant API   │
│  (FastAPI)      │
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼
┌────────┐ ┌──────┐ ┌────────┐ ┌────────┐
│ Broker │ │ Sim  │ │ Risk   │ │ Audit  │
│Adapter │ │      │ │ Gate   │ │ Store  │
└────────┘ └──────┘ └────────┘ └────────┘
         │
         ▼
    ┌─────────────┐
    │  Dashboard  │
    │  (Approval) │
    └─────────────┘
         │ approve
         ▼
    ┌─────────────┐
    │ IBKR Paper  │
    └─────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- Interactive Brokers TWS or IB Gateway (paper trading mode)
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd "IBKR AI Broker"
   ```

2. **Set up environment**
   ```bash
   # Copy environment template
   cp .env.example .env
   
   # Edit .env with your settings
   # Especially: IBKR_ACCOUNT, IBKR_PORT
   ```

3. **Start database**
   ```bash
   cd infra
   docker-compose up -d
   cd ..
   ```

4. **Install Python dependencies**
   ```bash
   # Using pip
   pip install -e '.[dev]'
   
   # Or using uv (faster)
   uv sync
   ```

5. **Set up pre-commit hooks**
   ```bash
   pre-commit install
   ```

6. **Run tests**
   ```bash
   pytest -v
   ```

### Running the Services

```bash
# Terminal 1: Start Assistant API
uvicorn apps.assistant_api.main:app --reload --port 8000

# Terminal 2: Start Dashboard
streamlit run apps.dashboard/main.py
# or
uvicorn apps.dashboard.main:app --reload --port 8080

# Terminal 3: Start MCP Server (for LLM integration)
python apps/mcp_server/main.py
```

## 📁 Project Structure

```
.
├── apps/                       # Runnable applications
│   ├── assistant_api/         # FastAPI orchestrator
│   ├── mcp_server/            # MCP tool server for LLM
│   └── dashboard/             # Approval UI
├── packages/                   # Reusable libraries
│   ├── broker_ibkr/           # IBKR adapter implementation
│   ├── risk_engine/           # Risk validation rules
│   ├── trade_sim/             # Order simulator
│   ├── schemas/               # Pydantic data models
│   └── audit_store/           # Event sourcing & audit
├── tests/                      # Integration & E2E tests
├── infra/                      # Infrastructure configs
│   ├── docker-compose.yml     # Database & services
│   └── init-db.sql            # Database schema
├── docs/                       # Documentation
│   ├── adr/                   # Architecture Decision Records
│   ├── threat-model.md        # Security analysis
│   └── runbook.md             # Operations guide
├── .github/                    # GitHub configs
│   ├── workflows/ci.yml       # CI/CD pipeline
│   └── copilot-instructions.md
├── AGENTS.md                   # Developer guide
├── ROADMAP.md                  # Development roadmap
└── pyproject.toml             # Python project config
```

## 🛡️ Safety Features

### 1. **No Direct LLM-to-Broker Writes**
All trade operations go through:
- Schema validation
- Simulation
- Risk gate evaluation
- Human approval (or strict auto-commit policy)

### 2. **Risk Gate Rules**
- Max notional per trade
- Position concentration limits
- Daily loss limits
- Instrument allowlist
- Kill switch support

### 3. **Two-Step Commit**
```python
# Step 1: Propose & Validate
order_intent = {...}
sim_result = simulate(order_intent)
risk_decision = evaluate(order_intent, sim_result)

# Step 2: Request Approval
if risk_decision.approved:
    approval_id = request_approval(order_intent)
    # Wait for user in dashboard...

# Step 3: Submit with Token
if token := get_approval_token(approval_id):
    submit_order(order_intent, token)
```

### 4. **Complete Audit Log**
Every event is logged:
- Order proposed
- Simulation run
- Risk evaluation
- Approval requested/granted/denied
- Order submitted/filled/rejected

### 5. **Kill Switch**
Emergency stop available at any time:
```python
POST /api/kill-switch/activate
```

## 🧪 Development Workflow

### Running Tests

```bash
# All tests
pytest -v

# Unit tests only
pytest tests/unit/ -v

# Integration tests (requires database)
pytest tests/integration/ -v -m integration

# With coverage
pytest --cov=packages --cov=apps --cov-report=html
```

### Code Quality

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
pyright
# or
mypy .

# All checks (runs automatically on commit)
pre-commit run --all-files
```

### Adding New Features

1. Create feature branch: `git checkout -b feature/name`
2. Write failing tests (TDD)
3. Implement feature (keep PRs < 300 LOC)
4. Ensure all checks pass
5. Open PR using template
6. Get review approval
7. Squash and merge

## 📚 Documentation

- **[AGENTS.md](AGENTS.md)** - Complete developer guide, commands, patterns
- **[ROADMAP.md](ROADMAP.md)** - Full development roadmap with 10 sprints
- **[.github/copilot-instructions.md](.github/copilot-instructions.md)** - Copilot coding guidelines
- **[docs/threat-model.md](docs/threat-model.md)** - Security considerations
- **[docs/adr/](docs/adr/)** - Architecture Decision Records

## 🔧 Configuration

### Environment Variables

Key settings in `.env`:

```bash
# Environment
ENV=dev                    # dev, paper, live
LOG_LEVEL=INFO

# IBKR Connection
IBKR_HOST=127.0.0.1
IBKR_PORT=7497            # 7497=paper, 7496=live
IBKR_CLIENT_ID=1
IBKR_ACCOUNT=DU1234567    # Your paper account

# Database
DATABASE_URL=postgresql://ibkr_user:password@localhost:5432/ibkr_broker

# Safety
KILL_SWITCH_ENABLED=false
ENABLE_LIVE_TRADING=false  # MUST be explicit
ENABLE_AUTO_COMMIT=false   # Keep false until proven
```

### Risk Policy

Edit `config/risk_policy.yml`:

```yaml
max_notional_per_trade: 10000
max_position_weight: 0.2
max_total_positions: 20
allowed_instruments: [STK, ETF]
require_limit_orders: true
```

## 🎯 Current Status

### ✅ Sprint 0 - Bootstrap (COMPLETED)
- [x] Project structure
- [x] Development environment
- [x] CI/CD pipeline
- [x] Documentation

### 🔄 Next: Sprint 1 - Audit Foundation
See [ROADMAP.md](ROADMAP.md) for detailed sprint plan.

## 🤝 Contributing

1. Read [AGENTS.md](AGENTS.md) for coding guidelines
2. Check [ROADMAP.md](ROADMAP.md) for current priorities
3. Create small, focused PRs (<300 LOC)
4. Ensure all tests pass
5. Follow the PR template

## ⚠️ Safety Reminders

- **Paper trading only** until extensive testing
- **Never commit secrets** to repository
- **All writes require approval** tokens
- **Test coverage** must not decrease
- **Audit events** for every state transition
- **Kill switch** always available

## 📄 License

MIT License - see LICENSE file

## 🆘 Support & Troubleshooting

### Database Connection Issues
```bash
# Check containers
docker-compose ps

# Restart database
docker-compose restart postgres
```

### IBKR Connection Refused
- Ensure TWS/IB Gateway is running
- Verify paper trading mode enabled
- Check port 7497 (paper) vs 7496 (live)
- Enable API connections in TWS settings

### Tests Failing
```bash
# Reset database
docker-compose down -v
docker-compose up -d

# Reinstall dependencies
pip install -e '.[dev]'
```

## 🔗 Resources

- [Interactive Brokers API Docs](https://interactivebrokers.github.io/)
- [TWS API Guide](https://ibkrcampus.com/ibkr-api-page/twsapi-doc/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

---

**Remember**: Safety first. When in doubt, REJECT and log. 🛡️
