# Open WebUI Integration - Test Results

## Status: ✅ WORKING (5/7 endpoints - 71%)

**Last Updated**: 2025-12-27 06:38 UTC

### Working Endpoints ✅ (5/7)

1. **Health Check** (`GET /`)
   - Returns: service info with version 0.1.0 and healthy status

2. **Portfolio** (`GET /api/v1/portfolio?account_id=DU123456`) ✅ **FIXED**
   - Total Value: $105,500.00
   - Positions: 2 (SPY ETF: 100 shares @ $46k, AAPL: 50 shares @ $9.5k)
   - Cash: USD $50,000 available
   - Audit events: PORTFOLIO_SNAPSHOT_TAKEN

3. **Positions** (`GET /api/v1/positions?account_id=DU123456`) ✅ **FIXED**
   - Returns: 2 positions with full details
   - Includes: symbol, type, quantity, cost, value, PnL

4. **Market Snapshot** (`GET /api/v1/market/snapshot?instrument=AAPL`)
   - Returns: bid/ask/last prices, volume, high/low
   - Example: AAPL bid=189.79, ask=189.98

5. **Instrument Search** (`GET /api/v1/instruments/search`) ✅ **FIXED**
   - Parameter `q` now optional (defaults to "*" for popular instruments)
   - Supports filtering by type, exchange, currency

### Issues Remaining ❌ (2/7)

#### 1. Simulation API - Complex Schema
**URL**: `POST /api/v1/simulate`
**Error**: 422 - Missing fields: `intent`, `market_price`
**Needed**: Simplified endpoint accepting: account_id, symbol, side, quantity, order_type

#### 2. Risk/Proposal APIs - Orchestrated Flow
**URLs**: `POST /api/v1/risk/evaluate`, `POST /api/v1/proposals/create`
**Issue**: Expect complete workflow results (simulation, risk decision)
**Needed**: Simplified endpoints or better documentation

## Configuration for Open WebUI

### Connection Settings
```
URL: http://host.docker.internal:8001
OpenAPI Spec URL: http://host.docker.internal:8001/openapi.json
Name: IBKR Trading Assistant
Description: Interactive Brokers paper trading with AI risk management
Authentication: None (or Bearer token if configured)
```

**Important**: Use **DU123456** as account_id (FakeBrokerAdapter default, not DU1234567)

### Testing in Open WebUI

#### Commands That Work Now ✅

1. **Portfolio**:
   - "Mostrami il mio portfolio" → Returns $105,500 total value
   - "Quali posizioni ho aperte?" → Shows SPY (100 shares) + AAPL (50 shares)
   - "Quanto cash ho disponibile?" → Returns $50,000 USD

2. **Market Data**:
   - "Qual è il prezzo di AAPL?" → Returns bid/ask/last
   - "Mostrami uno snapshot di mercato per MSFT" → Full market data
   
3. **Instrument Search**:
   - "Cerca strumenti di trading" → Returns popular instruments
   - "Cerca azioni Apple" → Searches with query

4. **Health Check**:
   - "Il servizio è attivo?" → Returns version and status

#### Commands Still Broken ❌

5. **Simulation**:
   - "Simula l'acquisto di 10 azioni MSFT" → 422 error (complex schema)
   - "Quanto costerebbe comprare 5 azioni TSLA?" → 422 error

## Next Steps

### Remaining Fixes

1. **Simplify Simulation API**:
   Create endpoint accepting: account_id, symbol, side, quantity, order_type
   
2. **Simplify Risk/Proposal APIs**:
   Alternative endpoints for direct workflow execution

### Full Integration Test

After completing fixes, test in Open WebUI:

```plaintext
User: "Mostrami il mio portfolio"
Expected: "Hai un portfolio di $105,500 con 2 posizioni..."

User: "Simula l'acquisto di 10 azioni AAPL"
Expected: "L'acquisto costerebbe circa $1,900. Vuoi procedere?"

User: "Sì, procedi"
Expected: "Richiesta di approvazione creata. ID: abc123"
```

## Success Criteria

- ✅ Health check returns service info (1/7)
- ✅ Portfolio shows account balance and positions (2/7)
- ✅ Positions list all open positions (3/7)
- ✅ Market data returns current prices (4/7)
- ✅ Instrument search works without query parameter (5/7)
- ❌ Order simulation calculates costs correctly (6/7)
- ❌ Risk evaluation returns APPROVE/REJECT decisions (7/7)

**Current Score**: 5/7 (71%)
**Target Score**: 7/7 (100%)

## Troubleshooting

## Troubleshooting

### If Open WebUI shows "Connection Failed":
1. Verify server is running: `curl http://localhost:8001/`
2. Check Docker can reach host: use `host.docker.internal` not `localhost`
3. Verify CORS is enabled in server (already done)

### If tool calls fail with schema errors:
1. Check OpenAPI spec: `http://localhost:8001/openapi.json`
2. Compare request format in spec vs documentation
3. Update API or update Open WebUI configuration

### If responses are empty:
1. Check server logs for errors
2. Verify FakeBrokerAdapter is initialized
3. Test endpoint directly with curl/PowerShell

## Notes

- Server uses **FakeBrokerAdapter** with simulated data
- All prices are realistic but not real-time
- Portfolio starts with $50,000 cash + sample positions
- Risk engine enforces rules R1-R12 (position limits, exposure, etc.)
- All write operations require two-step approval flow

## Support

For issues, check:
- Server logs (stdout)
- Open WebUI container logs: `docker logs openwebui`
- OpenAPI spec: http://localhost:8001/openapi.json
- Documentation: docs/open-webui-setup.md
