# 🧪 Guida Interattiva - Test API Swagger

**API avviata su**: http://localhost:8000  
**Swagger UI**: http://localhost:8000/docs

## 🎯 Test Flow Completo (15 minuti)

Questo flusso testa il ciclo completo di approvazione di un ordine:

**PROPOSE** → **SIMULATE** → **RISK EVALUATE** → **CREATE PROPOSAL** → **REQUEST APPROVAL** → **GRANT** → **SUBMIT**

---

### 1️⃣ Test Health Check

**Endpoint**: `GET /health`

1. Clicca su **GET /health**
2. Clicca **Try it out**
3. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "status": "healthy",
  "timestamp": "2025-12-27T...",
  "version": "0.1.0",
  "components": {
    "database": "connected",
    "broker": "connected (fake)",
    "audit_store": "healthy"
  }
}
```

---

### 2️⃣ Test Market Data

**Endpoint**: `GET /api/v1/market/snapshot`

1. Clicca su **GET /api/v1/market/snapshot**
2. Clicca **Try it out**
3. Nel campo `instrument` inserisci: `AAPL`
4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "instrument": "AAPL",
  "timestamp": "2025-12-27T...",
  "bid": "190.28",
  "ask": "190.47",
  "last": "190.37",
  "mid": "190.375",
  "volume": 866300,
  "high": "193.23",
  "low": "187.52",
  "open": "190.00",
  "prev_close": "189.62"
}
```

**Try Also**:
- `MSFT` - Microsoft
- `TSLA` - Tesla
- `GOOGL` - Google

---

### 3️⃣ Test Market Bars (Historical Data)

**Endpoint**: `GET /api/v1/market/bars`

1. Clicca su **GET /api/v1/market/bars**
2. Clicca **Try it out**
3. Parametri:
   - `instrument`: `AAPL`
   - `timeframe`: `1d`
   - `limit`: `5`
4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "instrument": "AAPL",
  "timeframe": "1d",
  "bars": [
    {
      "timestamp": "2025-12-22T...",
      "open": "189.50",
      "high": "192.30",
      "low": "188.20",
      "close": "190.75",
      "volume": 45234567
    },
    ...
  ]
}
```

---

### 4️⃣ Test Order Proposal ⭐ (Flow Principale)

**Endpoint**: `POST /api/v1/propose`

1. Clicca su **POST /api/v1/propose**
2. Clicca **Try it out**
3. Nel **Request body** inserisci:

```json
{
  "account_id": "DU123456",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "MKT",
  "quantity": 5,
  "exchange": "SMART",
  "currency": "USD",
  "instrument_type": "STK",
  "reason": "Test order from Swagger UI",
  "strategy_tag": "manual_test"
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "proposal_id": "prop_abc123...",
  "status": "proposed",
  "intent": { ... },
  "simulation": {
    "status": "SUCCESS",
    "execution_price": "190.37",
    "net_notional": "953.85",
    "cash_after": "49046.15",
    "warnings": []
  },
  "risk_decision": {
    "decision": "APPROVE",  // o "REJECT"
    "reason": "All risk checks passed",
    "violated_rules": [],
    "metrics": {
      "position_size_pct": 0.9,
      "total_exposure_pct": 53.8
    }
  },
  "timestamp": "2025-12-27T..."
}
```

**📝 Copia il `proposal_id`** per il prossimo step!

---

### 5️⃣ Test Approval Request

**Endpoint**: `POST /api/v1/approvals/request`

1. Clicca su **POST /api/v1/approvals/request**
2. Clicca **Try it out**
3. Nel **Request body** inserisci (usa il tuo proposal_id):

```json
{
  "proposal_id": "prop_abc123...",
  "reason": "Manual approval test from Swagger"
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "approval_id": "appr_xyz789...",
  "proposal_id": "prop_abc123...",
  "status": "pending",
  "requested_at": "2025-12-27T...",
  "expires_at": "2025-12-27T..."
}
```

**📝 Copia l'`approval_id`** per approvarlo!

---

### 6️⃣ Test Approval Grant

**Endpoint**: `POST /api/v1/approval/grant`

⚠️ **PREREQUISITO**: Devi avere un `proposal_id` valido da un proposal esistente (vedi step 5).

1. Clicca su **POST /api/v1/approval/grant**
2. Clicca **Try it out**
3. Nel **Request body** inserisci:

```json
{
  "proposal_id": "prop_abc123...",
  "approved_by": "test_user",
  "notes": "Approved via Swagger UI test"
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "proposal_id": "prop_abc123...",
  "state": "APPROVED",
  "token": {
    "token_id": "token_secure123...",
    "proposal_id": "prop_abc123...",
    "expires_at": "2025-12-27T..."
  },
  "message": "Approval granted",
  "correlation_id": "..."
}
```

**📝 Copia il `token.token_id`** per submittare!

---

### 5️⃣ Test Create Proposal ⭐ (NEW)

**Endpoint**: `POST /api/v1/proposals/create`

🎯 **Questo endpoint crea e salva una proposal** che poi può essere approvata.

⚠️ **PREREQUISITO**: Devi avere:
- Il risultato della simulazione (step 4)
- La valutazione del rischio (step 5 precedente)

1. Clicca su **POST /api/v1/proposals/create**
2. Clicca **Try it out**
3. Nel **Request body**, usa i risultati degli step precedenti:

```json
{
  "intent": {
    "account_id": "DU123456",
    "instrument": {
      "symbol": "AAPL",
      "type": "STK",
      "exchange": "SMART",
      "currency": "USD"
    },
    "side": "BUY",
    "order_type": "MKT",
    "quantity": "5",
    "reason": "Test approval flow",
    "strategy_tag": "test"
  },
  "simulation": {
    "status": "SUCCESS",
    "execution_price": "190.50",
    "net_notional": "953.97",
    "commission": "1.00",
    "market_impact": "0.00",
    "slippage": "0.03",
    "cash_after": "49046.03"
  },
  "risk_decision": {
    "decision": "APPROVE",
    "reason": "All risk checks passed",
    "violated_rules": [],
    "warnings": [],
    "metrics": {}
  }
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "proposal_id": "prop_abc123def456...",
  "state": "RISK_APPROVED",
  "message": "Proposal prop_abc123def456... created successfully",
  "correlation_id": "..."
}
```

**📝 Copia il `proposal_id`** - ti serve per gli step successivi!

---

### 6️⃣ Test Request Approval ⭐⭐

**Endpoint**: `POST /api/v1/approval/request`

⚠️ **PREREQUISITO**: Devi avere un `proposal_id` valido (vedi step 5).

1. Clicca su **POST /api/v1/approval/request**
2. Clicca **Try it out**
3. Nel **Request body** inserisci il `proposal_id` dello step 5:

```json
{
  "proposal_id": "prop_abc123def456...",
  "reason": "Request approval for test order"
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "proposal_id": "prop_abc123def456...",
  "state": "APPROVAL_REQUESTED",
  "message": "Approval requested",
  "correlation_id": "..."
}
```

---

### 7️⃣ Test Grant Approval ⭐⭐⭐

**Endpoint**: `POST /api/v1/approval/grant`

⚠️ **PREREQUISITO**: Devi aver richiesto l'approvazione (step 6).

1. Clicca su **POST /api/v1/approval/grant**
2. Clicca **Try it out**
3. Nel **Request body**:

```json
{
  "proposal_id": "prop_abc123def456...",
  "granted_by": "test_user",
  "reason": "Order approved for testing"
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "proposal_id": "prop_abc123def456...",
  "state": "APPROVAL_GRANTED",
  "has_token": true,
  "message": "Approval granted",
  "correlation_id": "..."
}
```

**✅ A questo punto l'ordine è pronto per essere submittato!**

---

### 8️⃣ Test Order Submission ⭐⭐⭐⭐ (DANGER)

**Endpoint**: `POST /api/v1/submit`

⚠️ **ATTENZIONE**: Questo step **submitta l'ordine al broker** (fake broker in test, IBKR reale in production).

⚠️ **PREREQUISITO**: Devi aver ottenuto l'approvazione (step 7).

1. Clicca su **POST /api/v1/submit**
2. Clicca **Try it out**
3. Nel **Request body** inserisci solo il `proposal_id`:

```json
{
  "proposal_id": "prop_abc123def456..."
}
```

4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "broker_order_id": "ord_fake_789...",
  "proposal_id": "prop_abc123def456...",
  "status": "SUBMITTED",
  "message": "Order submitted successfully",
  "correlation_id": "..."
}
```

**Per verificare lo stato dell'ordine**, usa il `broker_order_id` nell'endpoint GET /api/v1/orders/{broker_order_id}.

---

### 9️⃣ Test Kill Switch 🚨

**Activate Kill Switch**:

1. Clicca su **POST /api/kill-switch/activate**
2. Clicca **Try it out**
3. Nel **Request body**:

```json
{
  "reason": "Test emergency stop",
  "activated_by": "admin"
}
```

4. Clicca **Execute**

**Expected**: 200 OK

**Verifica** - Ora prova a fare un **nuovo propose** order:
- Dovrebbe fallire con: **503 Service Unavailable**
- Messaggio: "Kill switch is active - all trading halted"

**Deactivate Kill Switch**:

1. Clicca su **POST /api/kill-switch/deactivate**
2. Clicca **Try it out**
3. Nel **Request body**:

```json
{
  "deactivated_by": "admin"
}
```

4. Clicca **Execute**

---

### 9️⃣ Test Get Order Status

**Endpoint**: `GET /api/v1/orders/{broker_order_id}`

1. Clicca su **GET /api/v1/orders/{broker_order_id}**
2. Clicca **Try it out**
3. Nel campo `broker_order_id` inserisci il tuo order ID
4. Clicca **Execute**

**Expected Response** (200 OK):
```json
{
  "broker_order_id": "ord_fake_456...",
  "status": "filled",
  "account_id": "DU123456",
  "instrument": "AAPL",
  "side": "BUY",
  "quantity": 5,
  "filled_quantity": 5,
  "avg_fill_price": "190.37",
  "timestamp": "2025-12-27T..."
}
```

---

## 📊 Test Flow Summary

**Endpoints testati**:
1. ✅ Health check → sistema funzionante
2. ✅ Market data → prezzi real-time
3. ✅ Order proposal → validazione intent
4. ✅ Order simulation → calcolo costi/fees
5. ✅ **Create proposal → salva proposal per approvazione** (NEW)
6. ✅ Request approval → richiede approvazione
7. ✅ Grant approval → approva ordine
8. ✅ Submit order → invia a broker
9. ✅ Kill switch → emergency stop

**Workflow completo**: 
```
PROPOSE → SIMULATE → RISK → CREATE → REQUEST → GRANT → SUBMIT
```

---

## 🛠️ Test Scripts Automatici

Per testare il flusso completo in modo automatico, usa lo script PowerShell:

```powershell
# Test flusso completo (tutti gli step da 1 a 7)
.\test_complete_flow.ps1
```

Lo script `test_complete_flow.ps1` esegue automaticamente:
1. Propose order
2. Get market snapshot
3. Simulate execution
4. Evaluate risk
5. **Create proposal** (NEW)
6. Request approval
7. Grant approval

E mostra un summary colorato dei risultati.

---

## 🔍 Troubleshooting

### Errore "Proposal not found"
❌ **Problema**: Hai provato a richiedere approval senza prima creare la proposal.  
✅ **Soluzione**: Usa prima `POST /api/v1/proposals/create` per creare la proposal.

### Errore "Cannot create proposal for rejected order"
❌ **Problema**: La valutazione del rischio ha rejected l'ordine.  
✅ **Soluzione**: Controlla i `violated_rules` nella risposta del risk evaluation e aggiusta l'ordine.

### Errore "Token expired"
❌ **Problema**: Il token di approvazione è scaduto (15 minuti).  
✅ **Soluzione**: Richiedi una nuova approvazione (step 6-7).

### Server non risponde
❌ **Problema**: Il server non è in esecuzione.  
✅ **Soluzione**:
```powershell
# Avvia il server
uvicorn apps.assistant_api.main:app --reload --port 8000
```

---

## 🎭 Test Scenari Avanzati

### ❌ Test Order Rejection (Position Size)

Prova a proporre un ordine TROPPO GRANDE:

```json
{
  "account_id": "DU123456",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "MKT",
  "quantity": 100,
  "exchange": "SMART",
  "currency": "USD",
  "instrument_type": "STK",
  "reason": "Test rejection for position size limit",
  "strategy_tag": "test"
}
```

**Expected**: Risk decision = `REJECT`
**Reason**: "R2: Position size XX% exceeds limit 10.0%"

---

### ⏰ Test After-Hours Rejection (R5)

Il fake broker genera orari casuali. Se l'ordine viene rifiutato per "Trading outside allowed market hours", è normale - il sistema sta funzionando correttamente!

---

### 💸 Test Insufficient Cash

Prova a comprare troppo:

```json
{
  "account_id": "DU123456",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "MKT",
  "quantity": 300,
  "exchange": "SMART",
  "currency": "USD",
  "instrument_type": "STK",
  "reason": "Test insufficient cash scenario with large order",
  "strategy_tag": "test"
}
```

**Expected**: Simulation status = `INSUFFICIENT_CASH`

---

## 📊 Query Audit Log

### Via Python

```python
from packages.audit_store import AuditStore

store = AuditStore('data/audit.db')
events = store.query_events(limit=20)

print('📜 Recent Events:')
for evt in events:
    print(f'{evt.timestamp} | {evt.event_type:30} | {evt.correlation_id[:12]}')
```

### Via SQL

```bash
sqlite3 data/audit.db "SELECT timestamp, event_type, correlation_id FROM audit_events ORDER BY timestamp DESC LIMIT 10"
```

---

## 🧹 Cleanup

### Stop API Server

Chiudi la finestra PowerShell con il server uvicorn, oppure:

```bash
# Trova processo
Get-Process | Where-Object {$_.ProcessName -like "*python*"} | Select-Object Id, ProcessName

# Kill processo
Stop-Process -Id <PID>
```

### Clean Database (Opzionale)

```bash
Remove-Item data/audit.db -Force
```

---

## ✅ Checklist Test Completati

- [ ] Health check
- [ ] Market snapshot
- [ ] Order proposal (validation)
- [ ] Order simulation
- [ ] Risk evaluation
- [ ] **Create proposal** (NEW)
- [ ] Request approval
- [ ] Grant approval
- [ ] Order submission (submit to broker)
- [ ] Kill switch activate/deactivate
- [ ] Order status check
- [ ] Order rejection (size limit)
- [ ] Insufficient cash scenario

---

## 🚀 Prossimi Step

1. **Testa il flow completo** con lo script automatico: `.\test_complete_flow.ps1`
2. **Esplora altri endpoint** in Swagger UI
3. **Testa instrument search**: `/api/v1/instruments/search?q=AAPL`
4. **Testa resolve**: `/api/v1/instruments/resolve` (symbol → contract)
5. **Avvia Dashboard**: `streamlit run apps/dashboard/main.py`
6. **Testa MCP Server**: `python apps/mcp_server/main.py`

---

## 🐛 Troubleshooting

**Port già in uso**:
```bash
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**API non risponde**:
- Controlla console PowerShell per errori
- Verifica che database sia attivo: `docker ps`

**502/503 Errors**:
- Kill switch attivo? Deactivate
- Broker disconnesso? Restart API

---

## 📚 Documentazione Completa

- **QUICKSTART.md** - Setup e test rapidi (5 minuti)
- **docs/testing-guide.md** - Guida completa al testing (unit, integration, E2E)
- **AGENTS.md** - Comandi di sviluppo e architettura
- **ROADMAP.md** - Piano di sviluppo completo

---

**Buon testing! 🎉**

Documenta i tuoi risultati e apri issues su GitHub per qualsiasi bug trovato.

