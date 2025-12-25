# Dashboard Quick Start Guide

Quick guide to test the approval dashboard with the API.

## Prerequisites

1. API server running on port 8000
2. Streamlit installed (`pip install streamlit requests` or `uv pip install streamlit requests`)

## Step 1: Start the API Server

```bash
# In terminal 1
cd "C:\GIT-Project\AI\IBKR AI Broker"
uvicorn apps.assistant_api.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

## Step 2: Start the Dashboard

```bash
# In terminal 2
cd "C:\GIT-Project\AI\IBKR AI Broker"
streamlit run apps/dashboard/main.py
```

Dashboard will open in your browser at: http://localhost:8501

## Step 3: Create Test Proposals via API

Since the approval service is in-memory, you can create test proposals by calling the API endpoints directly.

### Option A: Using curl (Windows PowerShell)

```powershell
# Create a simple order intent
$intent = @{
    instrument = @{
        type = "STK"
        symbol = "AAPL"
        exchange = "SMART"
        currency = "USD"
    }
    side = "BUY"
    quantity = 10
    order_type = "MKT"
    time_in_force = "DAY"
    reason = "Test order"
    strategy_tag = "test"
} | ConvertTo-Json -Depth 10

# Simulate the order
$simulation = @{
    status = "SUCCESS"
    execution_price = "150.00"
    gross_notional = "1500.00"
    estimated_fee = "1.00"
    estimated_slippage = "0.75"
    net_notional = "1501.75"
    cash_before = "100000.00"
    cash_after = "98498.25"
    exposure_before = "0.00"
    exposure_after = "1500.00"
    warnings = @()
    error_message = $null
} | ConvertTo-Json -Depth 10

# Note: You'll need to manually create and store proposals
# via the approval service. This is a limitation of in-memory storage.
```

### Option B: Using Python

```python
import requests
import json
from decimal import Decimal

# Create test proposal data
intent = {
    "instrument": {"type": "STK", "symbol": "AAPL", "exchange": "SMART", "currency": "USD"},
    "side": "BUY",
    "quantity": 10,
    "order_type": "MKT",
    "time_in_force": "DAY",
    "reason": "Test",
}

simulation = {
    "status": "SUCCESS",
    "execution_price": "150.00",
    "gross_notional": "1500.00",
    "estimated_fee": "1.00",
    "estimated_slippage": "0.75",
    "net_notional": "1501.75",
    "cash_before": "100000.00",
    "cash_after": "98498.25",
    "exposure_before": "0.00",
    "exposure_after": "1500.00",
    "warnings": [],
    "error_message": None,
}

# Note: Direct proposal creation not exposed via API
# You need to go through the full flow: propose → simulate → risk evaluate
```

### Option C: Full API Flow (Recommended)

```python
import requests

BASE_URL = "http://localhost:8000"

# 1. Propose order
proposal = {
    "account_id": "DU123456",
    "symbol": "AAPL",
    "side": "BUY",
    "quantity": "10",
    "order_type": "MKT",
    "time_in_force": "DAY",
    "reason": "Test order",
    "strategy_tag": "test",
    "exchange": "SMART",
    "currency": "USD",
}

response = requests.post(f"{BASE_URL}/api/v1/propose", json=proposal)
print("Propose:", response.json())

# 2. Simulate order
# (You'll need the OrderIntent from step 1 response)

# 3. Risk evaluate
# (You'll need both OrderIntent and SimulationResult)

# Note: This creates OrderIntent but doesn't create proposals in approval service
# The approval service integration is not yet complete in the API flow
```

## Step 4: Test Dashboard Features

### View Proposals
- Should show "No pending proposals" initially
- When proposals exist, see list with details

### Request Approval
1. Find proposal in RISK_APPROVED state
2. Click "📋 Request Approval"
3. State changes to APPROVAL_REQUESTED

### Approve Proposal
1. Find proposal in APPROVAL_REQUESTED state
2. Click "✅ Approve"
3. (Optional) Enter reason
4. Click "Confirm Approval"
5. Token displayed (copy it!)

### Deny Proposal
1. Find proposal in APPROVAL_REQUESTED state
2. Click "❌ Deny"
3. Enter reason (required)
4. Click "Confirm Denial"

### Kill Switch
1. Go to sidebar
2. Toggle "Kill Switch Active"
3. See warning banner
4. Or click "🛑 Emergency Stop"

### Filters & Sorting
1. Use "Filter by state" dropdown
2. Use "Sort by" dropdown
3. List updates automatically

### Auto-Refresh
1. Enable "Auto-refresh" checkbox
2. Adjust refresh interval slider
3. Dashboard reloads automatically

## Step 5: Monitor API Logs

Watch terminal 1 for API logs:
- Request approval: `APPROVAL_REQUESTED` event
- Grant approval: `APPROVAL_GRANTED` event with token
- Deny approval: `APPROVAL_DENIED` event

## Troubleshooting

### Dashboard shows "API Disconnected"
- Check API is running: http://localhost:8000/api/v1/health
- Verify port 8000 not blocked

### No proposals showing
- Proposals are in-memory only
- Lost on API restart
- Need to create via API each session

### Actions not working
- Check browser console (F12) for errors
- Verify API returns 200 status
- Check correlation_id in responses

### Token not showing after approval
- Check if approval_service is initialized in API
- Verify grant endpoint returns token
- Check API logs for errors

## Integration Note

⚠️ **Important**: The approval service is currently in-memory only. This means:

1. **Proposals lost on restart**: When API restarts, all proposals are lost
2. **No persistence**: Proposals are not saved to database
3. **Testing limitation**: Must create proposals via code injection or API integration

### Future Enhancement

To fully integrate:
1. Add proposal creation to risk evaluation endpoint
2. Store proposals in database
3. Load proposals on API startup
4. Add proposal listing endpoint with filtering

## Next Steps

After testing dashboard:
1. Review Sprint 7 (order submission to broker)
2. Implement kill switch backend logic
3. Add proposal persistence
4. Integrate full flow: propose → simulate → risk → store → dashboard

## Questions?

- See `apps/dashboard/README.md` for full documentation
- Check `ROADMAP.md` for known limitations
- Review `AGENTS.md` for development guidance
