# Quick Start - Test End-to-End

Guida pratica per testare il funzionamento completo del sistema IBKR AI Broker.

## 📋 Prerequisiti

- [x] Python 3.12+ installato
- [x] Docker Desktop in esecuzione
- [x] IBKR Paper Trading Account (opzionale per test completo)
- [ ] Git bash o PowerShell

## 🔧 Step 1: Setup Ambiente

### 1.1 Verifica Installazione

```bash
# Controlla versione Python
python --version  # Deve essere >= 3.12

# Controlla Docker
docker --version
docker-compose --version
```

### 1.2 Installa Dipendenze

```bash
# Opzione A: Con pip
pip install -e '.[dev]'

# Opzione B: Con uv (più veloce)
uv sync
```

### 1.3 Avvia Database

```bash
# Da cartella principale
cd infra
docker-compose up -d
cd ..

# Verifica che sia attivo
docker ps  # Dovresti vedere postgres
```

## 🧪 Step 2: Test Rapido (Senza IBKR)

### 2.1 Esegui Unit Tests

```bash
# Test completi (esclude integration)
pytest -v -m "not integration"

# Solo test critici (più veloce)
pytest tests/test_risk_engine.py tests/test_trade_sim.py -v
```

### 2.2 Test Broker Fake

```bash
# Test interattivo con broker fake
python -c "
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.schemas.market_data import TimeframeType

# Crea adapter fake
broker = FakeBrokerAdapter()
broker.connect()

# Test portfolio
portfolio = broker.get_portfolio('DU12345')
print(f'Portfolio: ${portfolio.total_value:,.2f}')
print(f'Cash: ${portfolio.cash:,.2f}')
print(f'Positions: {len(portfolio.positions)}')

# Test market data
snapshot = broker.get_market_snapshot_v2('AAPL')
print(f'\\nAAPL: Bid ${snapshot.bid} | Ask ${snapshot.ask}')
print(f'Last: ${snapshot.last} | Volume: {snapshot.volume:,}')

# Test bars
bars = broker.get_market_bars('AAPL', TimeframeType.ONE_DAY, limit=5)
print(f'\\nHistorical bars: {len(bars)}')
for bar in bars[:3]:
    print(f'  {bar.timestamp}: O=${bar.open} H=${bar.high} L=${bar.low} C=${bar.close}')
"
```

**Output atteso**:
```
Portfolio: $100,000.00
Cash: $95,000.00
Positions: 2

AAPL: Bid $190.28 | Ask $190.47
Last: $190.37 | Volume: 866,300

Historical bars: 5
  2025-12-22: O=$189.50 H=$192.30 L=$188.20 C=$190.75
  ...
```

## 🌐 Step 3: Avvia Servizi API

### 3.1 Terminal 1: Assistant API

```bash
# Avvia FastAPI server
uvicorn apps.assistant_api.main:app --reload --port 8000
```

**Output atteso**:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 3.2 Terminal 2: Test API con curl/httpx

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test portfolio
curl "http://localhost:8000/api/v1/portfolio?account_id=DU12345"

# Test market snapshot
curl "http://localhost:8000/api/v1/market/snapshot?instrument=AAPL"

# Test market bars
curl "http://localhost:8000/api/v1/market/bars?instrument=AAPL&timeframe=1d&limit=5"
```

**Output atteso** (market snapshot):
```json
{
  "instrument": "AAPL",
  "timestamp": "2025-12-27T00:00:00",
  "bid": "190.28",
  "ask": "190.47",
  "last": "190.37",
  "volume": 866300
}
```

### 3.3 Test Order Flow Completo

```bash
# Crea script di test
cat > test_order_flow.py << 'EOF'
import httpx
from decimal import Decimal

API_URL = "http://localhost:8000"

# 1. Proponi ordine
order_data = {
    "account_id": "DU12345",
    "instrument": {
        "symbol": "AAPL",
        "type": "STK",
        "exchange": "SMART",
        "currency": "USD"
    },
    "side": "BUY",
    "order_type": "MKT",
    "quantity": 10,
    "reason": "Test order - tech stock accumulation"
}

client = httpx.Client(timeout=30.0)

# Step 1: Proponi
print("📝 Step 1: Proposing order...")
response = client.post(f"{API_URL}/api/v1/orders/propose", json=order_data)
print(f"Status: {response.status_code}")
proposal = response.json()
print(f"Proposal ID: {proposal['proposal_id']}")
print(f"Simulation: {proposal['simulation']['status']}")
print(f"Risk Decision: {proposal['risk_decision']['decision']}")

# Step 2: Richiedi approvazione (se risk approved)
if proposal['risk_decision']['decision'] == 'APPROVE':
    print("\n✅ Step 2: Requesting approval...")
    approval_response = client.post(
        f"{API_URL}/api/v1/approvals/request",
        json={
            "proposal_id": proposal['proposal_id'],
            "reason": "Manual test approval request"
        }
    )
    approval = approval_response.json()
    print(f"Approval ID: {approval['approval_id']}")
    print(f"Status: {approval['status']}")
    print("\n⏳ Waiting for manual approval in dashboard...")
    print(f"   Open: http://localhost:8080/approvals/{approval['approval_id']}")
else:
    print(f"\n❌ Risk rejected: {proposal['risk_decision']['reason']}")

client.close()
EOF

# Esegui test
python test_order_flow.py
```

## 📊 Step 4: Dashboard Approval

### 4.1 Avvia Dashboard

```bash
# Terminal 3: Streamlit Dashboard
streamlit run apps/dashboard/main.py

# O FastAPI dashboard
uvicorn apps.dashboard.main:app --reload --port 8080
```

**Accedi a**: http://localhost:8080

### 4.2 Approva Ordine

1. Vai alla sezione **Pending Approvals**
2. Trova il tuo approval ID
3. Rivedi:
   - Order details (symbol, side, quantity)
   - Simulation results (impatto portfolio)
   - Risk decision (motivo approvazione)
4. Click **Approve** o **Deny**

### 4.3 Verifica Submission

```bash
# Controlla stato approval
curl "http://localhost:8000/api/v1/approvals/{APPROVAL_ID}"

# Se approvato, submitti (con token)
curl -X POST "http://localhost:8000/api/v1/orders/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "approval_id": "YOUR_APPROVAL_ID",
    "approval_token": "YOUR_TOKEN"
  }'
```

## 🔍 Step 5: Verifica Audit Log

### 5.1 Query Audit Events

```bash
# Via Python
python -c "
from packages.audit_store import AuditStore

store = AuditStore('data/audit.db')
events = store.query_events(limit=10)

print('📜 Last 10 Audit Events:')
print('=' * 80)
for evt in events:
    print(f'{evt.timestamp} | {evt.event_type:30} | {evt.correlation_id[:8]}')
    if evt.data:
        print(f'  Data: {evt.data}')
"
```

### 5.2 Query per Correlation ID

```bash
# Trova tutti gli eventi di un flusso specifico
python -c "
from packages.audit_store import AuditStore, AuditQuery

store = AuditStore('data/audit.db')
query = AuditQuery(correlation_id='YOUR_CORRELATION_ID')
events = store.query_events(query)

print(f'📊 Full order flow ({len(events)} events):')
for evt in events:
    print(f'  {evt.event_type}')
    if evt.data:
        for k, v in evt.data.items():
            print(f'    {k}: {v}')
"
```

## 🔐 Step 6: Test Kill Switch

### 6.1 Attiva Kill Switch

```bash
# Via API
curl -X POST "http://localhost:8000/api/kill-switch/activate" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Test emergency stop",
    "activated_by": "admin"
  }'
```

### 6.2 Verifica Blocco

```bash
# Prova a proporre ordine (deve fallire)
curl -X POST "http://localhost:8000/api/v1/orders/propose" \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "DU12345",
    "instrument": {"symbol": "AAPL", "type": "STK"},
    "side": "BUY",
    "order_type": "MKT",
    "quantity": 10
  }'

# Output atteso: 503 Service Unavailable
# "Kill switch is active - all trading halted"
```

### 6.3 Rilascia Kill Switch

```bash
curl -X POST "http://localhost:8000/api/kill-switch/deactivate" \
  -H "Content-Type: application/json" \
  -d '{"deactivated_by": "admin"}'
```

## 📱 Step 7: Test MCP Server (LLM Integration)

### 7.1 Avvia MCP Server

```bash
# Terminal 4: MCP Server
python apps/mcp_server/main.py
```

### 7.2 Test con MCP Inspector

```bash
# Installa MCP Inspector
npx @modelcontextprotocol/inspector python apps/mcp_server/main.py

# Accedi a: http://localhost:5173
```

### 7.3 Test Tools Disponibili

Nell'inspector, prova:

1. **get_portfolio**
   - Input: `{"account_id": "DU12345"}`
   - Output: Portfolio con posizioni e cash

2. **get_market_snapshot**
   - Input: `{"instrument": "AAPL"}`
   - Output: Bid/ask/last price

3. **propose_order**
   - Input: Order intent completo
   - Output: Proposal ID + simulation + risk decision

4. **request_approval**
   - Input: `{"proposal_id": "...", "reason": "test"}`
   - Output: Approval ID da usare in dashboard

## 🎯 Step 8: Test con IBKR Reale (Opzionale)

⚠️ **Solo se hai IBKR Gateway/TWS attivo**

### 8.1 Configura IBKR

1. Scarica [IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)
2. Configura paper trading account
3. Abilita API in configurazione
4. Imposta porta 7497 (paper)

### 8.2 Update Environment

```bash
# In .env
BROKER_TYPE=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
IBKR_MODE=paper
```

### 8.3 Test Connection

```bash
# Test connessione reale
python -c "
from packages.broker_ibkr.real import IBKRBrokerAdapter
from packages.ibkr_config import IBKRConfig

config = IBKRConfig(
    host='127.0.0.1',
    port=7497,
    client_id=1,
    mode='paper'
)

broker = IBKRBrokerAdapter(config)
broker.connect()

print(f'Connected: {broker.is_connected()}')

# Test portfolio reale
portfolio = broker.get_portfolio('DU12345')  # Usa il tuo account ID
print(f'Portfolio: ${portfolio.total_value:,.2f}')
print(f'Cash: ${portfolio.cash:,.2f}')

broker.disconnect()
"
```

### 8.4 Esegui Integration Tests

```bash
# Tutti i test IBKR
pytest -m integration -v

# Test specifico
pytest tests/test_ibkr_real.py::test_connection -v
```

## 🧹 Step 9: Cleanup

```bash
# Stop servizi
# Ctrl+C nei terminali con uvicorn/streamlit

# Stop database
cd infra
docker-compose down
cd ..

# Clean test data (opzionale)
rm -rf data/audit.db
rm -rf data/flex_reports/
rm -rf data/statistics.json
```

## 📊 Checklist Funzionalità Testate

- [ ] ✅ Unit tests passano (743/743)
- [ ] ✅ Broker fake funziona (portfolio, market data)
- [ ] ✅ API health endpoint risponde
- [ ] ✅ Order proposal con simulation
- [ ] ✅ Risk gate evaluation
- [ ] ✅ Approval request/grant/deny flow
- [ ] ✅ Audit log persistenza
- [ ] ✅ Kill switch attivazione/rilascio
- [ ] ✅ Dashboard approval UI
- [ ] ✅ MCP server tools
- [ ] ⭐ IBKR real connection (opzionale)
- [ ] ⭐ IBKR order submission (opzionale)

## 🐛 Troubleshooting

### Port già in uso

```bash
# Trova processo sulla porta 8000
netstat -ano | findstr :8000  # Windows
lsof -i :8000                 # macOS/Linux

# Kill processo
taskkill /PID <PID> /F        # Windows
kill -9 <PID>                 # macOS/Linux
```

### Database non si connette

```bash
# Verifica Docker
docker ps

# Restart container
cd infra
docker-compose restart
docker-compose logs postgres
```

### IBKR Connection Failed

- Verifica TWS/Gateway attivo
- Controlla porta 7497 (paper) o 7496 (live)
- Abilita API in TWS: Global Configuration → API → Settings
- Aggiungi 127.0.0.1 a trusted IP

### Test Flaky

```bash
# Pulisci singleton state
python -c "
import packages.live_config
packages.live_config._live_config_manager = None
"

# Re-run test singolo
pytest tests/test_live_config.py::TestLiveConfigManager::test_can_submit_live_order -v
```

## 📚 Prossimi Step

1. **Esplora AGENTS.md** - Comandi development completi
2. **Leggi docs/testing-guide.md** - Best practices testing
3. **Review ROADMAP.md** - Feature roadmap completo
4. **Check docs/adr/** - Architecture Decision Records

## 🎉 Successo!

Se hai completato tutti gli step, hai verificato:
- ✅ Setup environment corretto
- ✅ Unit tests funzionanti
- ✅ API endpoints operativi
- ✅ Order flow end-to-end
- ✅ Approval workflow
- ✅ Audit logging
- ✅ Kill switch safety
- ✅ MCP integration

**Il sistema è pronto per lo sviluppo!** 🚀

---

**Last updated**: 2025-12-27
**Version**: Sprint 7 - Production Ready
