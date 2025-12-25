# MCP Server for IBKR AI Broker

Model Context Protocol (MCP) server exposing read-only tools for LLM interaction with the trading system.

## Overview

The MCP server provides a standardized interface for Large Language Models to query portfolio data, simulate trades, and evaluate risk **without the ability to execute orders**.

### Security Model

🔒 **Critical Safety Features:**
- ✅ Read-only tools for data access (no direct order execution)
- ✅ Gated write tool (`request_approval`) creates proposals but does NOT execute
- ✅ Human approval required via dashboard for all order execution
- ✅ All tool calls audited with correlation_id
- ✅ Parameter validation on all inputs
- ✅ FakeBrokerAdapter for testing (no real broker access)

### Gated AI Pattern

The MCP server implements the **gated AI pattern**:
- LLM can **READ** portfolio data (get_portfolio, get_positions, etc.)
- LLM can **ANALYZE** trades (simulate_order, evaluate_risk)
- LLM can **PROPOSE** orders (request_approval) ← Creates proposal, awaits human
- LLM **CANNOT EXECUTE** orders (no token access, no submit endpoint)

Human retains full control: proposals are created but require explicit dashboard approval before execution.

## Available Tools

### Read-Only Tools

#### 1. `get_portfolio`
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

#### 2. `get_positions`
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

#### 3. `get_cash`
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

#### 4. `get_open_orders`
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

#### 5. `simulate_order`
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

#### 6. `evaluate_risk`
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

### Gated Write Tool

#### 7. `request_approval` (GATED)
**Create order proposal and request human approval.**

This is the ONLY write operation exposed to LLMs. It creates a proposal but does NOT execute the order. Human approval via dashboard is required before order submission.

**Security:**
- ✅ Validates all parameters (including reason length ≥ 10 chars)
- ✅ Simulates order BEFORE creating proposal
- ✅ Evaluates risk BEFORE creating proposal
- ✅ Returns proposal_id (NOT approval token)
- ✅ Instructs user to use dashboard for approval
- ✅ Full audit trail with correlation_id

**Parameters:**
- `account_id` (string, required): Account identifier
- `symbol` (string, required): Stock symbol
- `side` (string, required): "BUY" or "SELL"
- `quantity` (string, required): Quantity as decimal string
- `order_type` (string): "MKT" or "LMT" (default: "MKT")
- `limit_price` (string, optional): Required for LMT orders
- `market_price` (string, required): Current market price
- `reason` (string, required): Justification for order (minimum 10 characters)

**Returns (Success):**
```json
{
  "status": "APPROVAL_REQUESTED",
  "proposal_id": "550e8400-e29b-41d4-a716-446655440000",
  "decision": "APPROVE",
  "reason": "Order approved by risk engine",
  "warnings": [],
  "symbol": "AAPL",
  "side": "BUY",
  "quantity": "10",
  "estimated_cost": "1905.00",
  "message": "Proposal created and awaiting human approval. Use dashboard to approve or deny."
}
```

**Returns (Risk Rejection):**
```json
{
  "status": "RISK_REJECTED",
  "decision": "REJECT",
  "reason": "R1: Notional exceeds maximum allowed ($100,000)",
  "violated_rules": ["R1"],
  "proposal_id": null
}
```

**Returns (Simulation Failure):**
```json
{
  "status": "SIMULATION_FAILED",
  "error": "Insufficient cash available for purchase",
  "proposal_id": null
}
```

**Workflow:**
1. LLM calls `request_approval` with order details + reason
2. MCP server validates parameters (reason must be ≥ 10 chars)
3. Server simulates order (checks if feasible)
4. Server evaluates risk (R1-R8 rules)
5. If simulation succeeds AND risk approves:
   - Creates proposal in ApprovalService
   - Requests approval (state → APPROVAL_REQUESTED)
   - Returns proposal_id to LLM
6. Human reviews proposal in dashboard
7. Human clicks "Approve" → generates approval token
8. Human (or system) calls POST /api/v1/orders/submit with token
9. Order submitted to broker

**Why Gated?**
- LLM can propose actionable orders with full context
- LLM provides reasoning (required field)
- Human retains final decision power
- System enforces security (no direct execution)
- Complete audit trail maintained

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

### Request Order Approval (Gated)

```
User: "Buy 10 shares of AAPL for portfolio rebalancing"
LLM calls: request_approval(
  account_id="DU123456",
  symbol="AAPL",
  side="BUY",
  quantity="10",
  market_price="190.00",
  reason="Portfolio rebalancing to target allocation"
)
Response: {
  "status": "APPROVAL_REQUESTED",
  "proposal_id": "550e8400-...",
  "message": "Proposal created and awaiting human approval..."
}
LLM: "I've created proposal 550e8400 for 10 shares of AAPL at estimated cost $1,905. 
     Please review in the dashboard to approve or deny."
```

Human then:
1. Opens dashboard
2. Reviews proposal 550e8400 with full details (intent, simulation, risk)
3. Clicks "Approve" → generates token
4. System submits order with token

## Important: Order Execution Flow

⚠️ **The MCP server can create proposals but CANNOT execute orders.**

### Complete Flow (with request_approval)

1. **LLM Analysis Phase:**
   - LLM uses `get_portfolio` to understand current holdings
   - LLM uses `simulate_order` to estimate impact
   - LLM uses `evaluate_risk` to check rules

2. **LLM Proposal Phase:**
   - LLM calls `request_approval` with order details + reason
   - MCP server validates, simulates, evaluates risk
   - If approved by risk engine: creates proposal
   - Returns proposal_id to LLM (NOT approval token)

3. **Human Approval Phase:**
   - Human opens dashboard
   - Reviews proposal with full context (intent, simulation, risk decision)
   - Decides: Approve or Deny

4. **Execution Phase (if approved):**
   - Dashboard generates approval token (on human approval)
   - System calls POST /api/v1/orders/submit with token
   - Token validated (expiration, single-use, hash)
   - Order submitted to broker

This ensures **human-in-the-loop** for all trade execution.

### Without request_approval (Manual Flow)

If not using `request_approval` tool:

1. LLM uses `simulate_order` + `evaluate_risk`
2. LLM provides recommendation to human
3. **Human** manually uses dashboard or API to:
   - Create proposal (POST /api/v1/propose)
   - Request approval (POST /api/v1/approval/request)
   - Grant approval (POST /api/v1/approval/{id}/grant)
   - Submit order (POST /api/v1/orders/submit with token)

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
┌──────────────────────────┐
│   MCP Server (main.py)   │
├──────────────────────────┤
│ Read Tools:              │
│ - get_portfolio          │ → Portfolio data
│ - get_positions          │ → Open positions
│ - get_cash               │ → Cash balances
│ - get_open_orders        │ → Pending orders
│ - simulate_order         │ → Pre-trade analysis
│ - evaluate_risk          │ → Risk rule check
│                          │
│ Gated Write Tool:        │
│ - request_approval 🔒    │ → Create proposal (NO execution)
└──────┬───────────────────┘
       │
       ↓
┌──────────────────────────┐
│  Service Layer           │
├──────────────────────────┤
│  FakeBrokerAdapter       │ → No real broker access
│  TradeSimulator          │ → Impact calculation
│  RiskEngine              │ → R1-R8 evaluation
│  ApprovalService         │ → Proposal storage
│  AuditStore              │ → Event logging
└──────────────────────────┘

      Human Approval Required
               ↓
┌──────────────────────────┐
│  Dashboard / API         │
│  POST /orders/submit     │ → WITH approval token
└──────────────────────────┘
               ↓
        Order Executed
```

## Security Notes

1. **Read + Analyze + Propose (but NOT Execute)**: 
   - MCP server exposes 6 read-only tools for data access
   - MCP server exposes 1 gated write tool (`request_approval`) that creates proposals
   - Proposals require human approval before execution
2. **Gated Execution**: Order submission requires:
   - Separate API endpoint (POST /api/v1/orders/submit)
   - Human approval with token
   - Token validation (expiration, single-use, hash)
3. **Audit Everything**: All tool calls logged with correlation_id
4. **Validation**: All parameters validated against schemas
5. **Fake Broker**: Uses FakeBrokerAdapter (no real broker connection in dev/test)
6. **Reason Required**: `request_approval` requires ≥ 10 char reason (prevents thoughtless requests)

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

Sprint 9 Complete ✅:
- Added gated tool `request_approval` (creates proposal but doesn't execute)
- LLM can now propose orders with reasoning
- Human retains full approval control

Future Sprints:
- Sprint 10: Add rate limiting and OAuth for production
- Sprint 11: Real IBKR broker integration

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Claude Desktop MCP Integration](https://docs.anthropic.com/en/docs/model-context-protocol)
