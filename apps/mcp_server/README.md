# MCP Server for IBKR AI Broker

Model Context Protocol (MCP) server exposing read-only tools for LLM interaction with the trading system.

## Overview

The MCP server provides a standardized interface for Large Language Models to query portfolio data, simulate trades, and evaluate risk **without the ability to execute orders**.

### Security Model

🔒 **Critical Safety Features:**
- ✅ All tools are **read-only** (no order submission exposed)
- ✅ Order execution requires out-of-band approval (dashboard or API)
- ✅ All tool calls audited with correlation_id
- ✅ Parameter validation on all inputs
- ✅ FakeBrokerAdapter for testing (no real broker access)

## Available Tools

### 1. `get_portfolio`
Get complete portfolio snapshot including positions and cash.

**Parameters:**
- `account_id` (string, required): Account identifier (e.g., "DU123456")

**Returns:**
```json
{
  "account_id": "DU123456",
  "total_value": "96000.00",
  "positions": [
    {
      "symbol": "SPY",
      "type": "ETF",
      "quantity": "100",
      "average_cost": "450.00",
      "market_value": "46000.00",
      "unrealized_pnl": "1000.00"
    }
  ],
  "cash": [
    {
      "currency": "USD",
      "available": "50000.00",
      "total": "50000.00"
    }
  ]
}
```

### 2. `get_positions`
Get list of open positions.

**Parameters:**
- `account_id` (string, required)

**Returns:**
```json
{
  "positions": [...],
  "count": 1
}
```

### 3. `get_cash`
Get cash balances by currency.

**Parameters:**
- `account_id` (string, required)

**Returns:**
```json
{
  "cash": [
    {
      "currency": "USD",
      "available": "50000.00",
      "total": "50000.00"
    }
  ]
}
```

### 4. `get_open_orders`
Get list of open orders.

**Parameters:**
- `account_id` (string, required)

**Returns:**
```json
{
  "orders": [
    {
      "broker_order_id": "MOCK1A2B3C4D",
      "symbol": "AAPL",
      "side": "BUY",
      "quantity": "10",
      "order_type": "MKT",
      "status": "SUBMITTED",
      "filled_quantity": "0"
    }
  ],
  "count": 1
}
```

### 5. `simulate_order`
Simulate order to estimate cash impact, fees, and slippage.

**Parameters:**
- `account_id` (string, required)
- `symbol` (string, required): Stock symbol
- `side` (string, required): "BUY" or "SELL"
- `quantity` (string, required): Quantity as decimal string
- `order_type` (string): "MKT" or "LMT" (default: "MKT")
- `limit_price` (string, optional): Required for LMT orders
- `market_price` (string, required): Current market price for simulation

**Returns:**
```json
{
  "status": "SUCCESS",
  "gross_notional": "1900.00",
  "estimated_slippage": "0.95",
  "estimated_fees": "1.00",
  "net_cash_impact": "-1901.95",
  "cash_before": "50000.00",
  "cash_after": "48098.05",
  "exposure_before": "46000.00",
  "exposure_after": "47900.00",
  "warnings": [],
  "error_message": null
}
```

### 6. `evaluate_risk`
Evaluate order against risk rules (R1-R8).

**Parameters:**
- Same as `simulate_order`

**Returns:**
```json
{
  "decision": "APPROVE",
  "reason": "All risk checks passed",
  "violated_rules": [],
  "warnings": [],
  "metrics": {
    "gross_notional": "1900.00",
    "position_pct": "49.7",
    "slippage_bps": "5.0"
  }
}
```

## Running the Server

### Option 1: Direct execution with PYTHONPATH

```bash
# PowerShell
$env:PYTHONPATH="C:\GIT-Project\AI\IBKR AI Broker"
python apps/mcp_server/main.py

# Bash
export PYTHONPATH="/path/to/ibkr-ai-broker"
python apps/mcp_server/main.py
```

### Option 2: Using run script

```bash
python apps/mcp_server/run.py
```

## Testing with MCP Inspector

MCP provides an inspector tool for testing:

```bash
# Install MCP inspector
npm install -g @modelcontextprotocol/inspector

# Run inspector
mcp-inspector apps/mcp_server/main.py
```

Open browser to http://localhost:5173 and test tools interactively.

## Integration with Claude Desktop

Add to Claude Desktop config (`~/.claude/config.json` or `%APPDATA%\Claude\config.json`):

```json
{
  "mcpServers": {
    "ibkr-ai-broker": {
      "command": "python",
      "args": [
        "C:\\GIT-Project\\AI\\IBKR AI Broker\\apps\\mcp_server\\run.py"
      ]
    }
  }
}
```

Restart Claude Desktop. The tools will appear in the MCP menu.

## Example Usage (via LLM)

### Query Portfolio

```
User: "What's my current portfolio?"
LLM calls: get_portfolio(account_id="DU123456")
Response: Shows positions, cash, total value
```

### Simulate Trade

```
User: "What would happen if I bought 10 shares of AAPL at $190?"
LLM calls: simulate_order(
  account_id="DU123456",
  symbol="AAPL",
  side="BUY",
  quantity="10",
  market_price="190.00"
)
Response: Cash impact, fees, slippage estimate
```

### Check Risk

```
User: "Would buying 100 shares of TSLA violate any risk rules?"
LLM calls: evaluate_risk(
  account_id="DU123456",
  symbol="TSLA",
  side="BUY",
  quantity="100",
  market_price="250.00"
)
Response: APPROVE or REJECT with reasons
```

## Important: Order Execution Flow

⚠️ **The MCP server CANNOT execute orders.**

To execute an order after LLM analysis:

1. LLM uses `simulate_order` + `evaluate_risk`
2. LLM provides recommendation
3. **Human** uses dashboard or API to:
   - Create proposal (POST /api/v1/propose)
   - Request approval (POST /api/v1/approval/request)
   - Grant approval (POST /api/v1/approval/{id}/grant)
   - Submit order (POST /api/v1/orders/submit with token)

This ensures **human-in-the-loop** for all trade execution.

## Audit Trail

All tool calls are audited:
- Tool name and parameters
- Result summary
- Errors (if any)
- Correlation ID for tracing

Check audit database:
```bash
sqlite3 mcp_audit.db "SELECT * FROM audit_events WHERE event_type = 'CUSTOM' AND metadata LIKE '%mcp_tool%' ORDER BY timestamp DESC LIMIT 10;"
```

## Architecture

```
┌─────────────┐
│     LLM     │
│  (Claude)   │
└──────┬──────┘
       │ MCP Protocol (stdio)
       ↓
┌─────────────────────┐
│   MCP Server        │
│   (main.py)         │
├─────────────────────┤
│ Tools:              │
│ - get_portfolio     │ → Read-only
│ - get_positions     │ → Read-only
│ - simulate_order    │ → Read-only
│ - evaluate_risk     │ → Read-only
└──────┬──────────────┘
       │
       ↓
┌─────────────────────┐
│  FakeBrokerAdapter  │ → No real broker access
│  TradeSimulator     │
│  RiskEngine         │
│  AuditStore         │
└─────────────────────┘
```

## Security Notes

1. **No Write Operations**: MCP server exposes ONLY read-only tools
2. **Gated Execution**: Order submission requires:
   - Separate API endpoint
   - Human approval with token
   - Token validation (expiration, single-use, hash)
3. **Audit Everything**: All tool calls logged with correlation_id
4. **Validation**: All parameters validated against schemas
5. **Fake Broker**: Uses FakeBrokerAdapter (no real broker connection)

## Development

### Adding New Tools

1. Define tool schema in `list_tools()`
2. Create handler function `async def handle_<tool_name>(arguments)`
3. Add to `call_tool()` dispatcher
4. Emit audit events
5. Add tests

### Running Tests

```bash
pytest tests/test_mcp_server.py -v
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'packages'"

Set PYTHONPATH to project root:
```bash
$env:PYTHONPATH="C:\GIT-Project\AI\IBKR AI Broker"
```

### "Broker not initialized"

Ensure `main()` runs before tool calls. Check server startup logs.

### "Account not found"

Use test account ID: "DU123456" (FakeBrokerAdapter)

## Next Steps

After Sprint 8:
- Sprint 9: Add gated tool `request_approval` (creates proposal but doesn't execute)
- Sprint 10: Add rate limiting and OAuth for production

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Claude Desktop MCP Integration](https://docs.anthropic.com/en/docs/model-context-protocol)
