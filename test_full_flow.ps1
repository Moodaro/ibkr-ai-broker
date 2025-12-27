# Test Full Order Flow
# Propose -> Simulate -> Risk Evaluate -> Request Approval

Write-Host ""
Write-Host "FULL ORDER FLOW TEST" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Propose Order
Write-Host "1. Proposing Order..." -ForegroundColor Yellow
$proposeBody = @{
    account_id = "DU123456"
    symbol = "AAPL"
    side = "BUY"
    order_type = "MKT"
    quantity = 5
    exchange = "SMART"
    currency = "USD"
    instrument_type = "STK"
    reason = "Test full flow from PowerShell script"
    strategy_tag = "test_flow"
} | ConvertTo-Json

$proposeResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/propose" `
    -Method Post `
    -ContentType "application/json" `
    -Body $proposeBody

Write-Host "   Order proposed" -ForegroundColor Green
Write-Host "   Correlation ID: $($proposeResponse.correlation_id)" -ForegroundColor Gray

# Step 2: Get Market Snapshot
Write-Host ""
Write-Host "2. Getting Market Data..." -ForegroundColor Yellow

$symbol = $proposeResponse.intent.instrument.symbol
$marketSnapshot = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/market/snapshot?instrument=$symbol" `
    -Method Get

Write-Host "   Market snapshot retrieved" -ForegroundColor Green
Write-Host "   Last Price: $($marketSnapshot.last)" -ForegroundColor Gray
Write-Host "   Bid/Ask: $($marketSnapshot.bid) / $($marketSnapshot.ask)" -ForegroundColor Gray

# Step 3: Simulate Order
Write-Host ""
Write-Host "3. Simulating Order..." -ForegroundColor Yellow
$simulateBody = @{
    intent = $proposeResponse.intent
    account_id = "DU123456"
    market_price = $marketSnapshot.last
} | ConvertTo-Json -Depth 10

$simulateResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/simulate" `
    -Method Post `
    -ContentType "application/json" `
    -Body $simulateBody

Write-Host "   Simulation complete" -ForegroundColor Green
Write-Host "   Status: $($simulateResponse.simulation.status)" -ForegroundColor Gray
Write-Host "   Execution Price: $($simulateResponse.simulation.execution_price)" -ForegroundColor Gray
Write-Host "   Net Cost: $($simulateResponse.simulation.net_notional)" -ForegroundColor Gray
Write-Host "   Cash After: $($simulateResponse.simulation.cash_after)" -ForegroundColor Gray

# Step 4: Risk Evaluation
Write-Host ""
Write-Host "4. Evaluating Risk..." -ForegroundColor Yellow
$riskBody = @{
    intent = $proposeResponse.intent
    simulation = $simulateResponse.simulation
    account_id = "DU123456"
    portfolio_value = "105500.00"
} | ConvertTo-Json -Depth 10

$riskResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/risk/evaluate" `
    -Method Post `
    -ContentType "application/json" `
    -Body $riskBody

Write-Host "   Risk evaluation complete" -ForegroundColor Green
Write-Host "   Decision: $($riskResponse.decision.decision)" -ForegroundColor $(if($riskResponse.decision.decision -eq "APPROVE"){"Green"}else{"Red"})
Write-Host "   Reason: $($riskResponse.decision.reason)" -ForegroundColor Gray

if ($riskResponse.decision.violated_rules.Count -gt 0) {
    Write-Host "   Violated Rules: $($riskResponse.decision.violated_rules -join ', ')" -ForegroundColor Red
}

# Step 5: Request Approval (only if APPROVED by risk)
if ($riskResponse.decision.decision -eq "APPROVE") {
    Write-Host ""
    Write-Host "5. Requesting Approval..." -ForegroundColor Yellow
    
    $approvalBody = @{
        proposal_id = $riskResponse.proposal_id
        reason = "Automated test flow - risk checks passed"
    } | ConvertTo-Json
    
    $approvalResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/approval/request" `
        -Method Post `
        -ContentType "application/json" `
        -Body $approvalBody
    
    Write-Host "   Approval requested" -ForegroundColor Green
    Write-Host "   Approval ID: $($approvalResponse.approval_id)" -ForegroundColor Gray
    Write-Host "   Status: $($approvalResponse.status)" -ForegroundColor Gray
    Write-Host "   Expires: $($approvalResponse.expires_at)" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "Next Steps:" -ForegroundColor Cyan
    Write-Host "   To grant approval, use the approval_id above in Swagger UI" -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "Order REJECTED by risk engine" -ForegroundColor Red
    Write-Host "   Cannot proceed to approval" -ForegroundColor Gray
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "Full flow test completed!" -ForegroundColor Green
Write-Host ""
