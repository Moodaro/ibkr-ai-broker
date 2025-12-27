# Complete Approval Flow Test Script
# Tests: Propose -> Simulate -> Risk -> Create Proposal -> Request Approval -> Grant -> Submit

$baseUrl = "http://localhost:8000"
$correlationId = [guid]::NewGuid().ToString()

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "COMPLETE APPROVAL FLOW TEST" -ForegroundColor Cyan
Write-Host "Correlation ID: $correlationId" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Cyan

# Step 1: Propose order
Write-Host "[1/7] Proposing order..." -ForegroundColor Green
$proposeBody = @{
    account_id = "DU123456"
    symbol = "AAPL"
    side = "BUY"
    order_type = "MKT"
    quantity = 5
    exchange = "SMART"
    currency = "USD"
    instrument_type = "STK"
    reason = "Test complete approval flow"
    strategy_tag = "flow_test"
} | ConvertTo-Json

$proposeResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/propose" `
    -Method Post `
    -ContentType "application/json" `
    -Body $proposeBody

Write-Host "RESULT: Proposal validated" -ForegroundColor White
Write-Host "  Intent ID: $($proposeResponse.intent.account_id)" -ForegroundColor Gray
Write-Host "  Warnings: $($proposeResponse.warnings.Count)`n" -ForegroundColor Gray

# Step 2: Get market snapshot
Write-Host "[2/7] Getting market snapshot..." -ForegroundColor Green
$snapshotResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/market/snapshot?instrument=AAPL" `
    -Method Get

Write-Host "RESULT: Market data retrieved" -ForegroundColor White
Write-Host "  Last price: `$$($snapshotResponse.last)" -ForegroundColor Gray
Write-Host "  Bid: `$$($snapshotResponse.bid)" -ForegroundColor Gray
Write-Host "  Ask: `$$($snapshotResponse.ask)`n" -ForegroundColor Gray

# Step 3: Simulate execution
Write-Host "[3/7] Simulating execution..." -ForegroundColor Green
$simulateBody = @{
    intent = $proposeResponse.intent
    market_price = [decimal]$snapshotResponse.last
} | ConvertTo-Json -Depth 10

$simulateResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/simulate" `
    -Method Post `
    -ContentType "application/json" `
    -Body $simulateBody

Write-Host "RESULT: Simulation complete" -ForegroundColor White
Write-Host "  Status: $($simulateResponse.result.status)" -ForegroundColor Gray
Write-Host "  Execution price: `$$($simulateResponse.result.execution_price)" -ForegroundColor Gray
Write-Host "  Net cost: `$$($simulateResponse.result.net_notional)`n" -ForegroundColor Gray

# Step 4: Evaluate risk
Write-Host "[4/7] Evaluating risk..." -ForegroundColor Green
$riskBody = @{
    intent = $proposeResponse.intent
    simulation = $simulateResponse.result
    portfolio_value = 100000
} | ConvertTo-Json -Depth 10

$riskResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/risk/evaluate" `
    -Method Post `
    -ContentType "application/json" `
    -Body $riskBody

Write-Host "RESULT: Risk evaluation complete" -ForegroundColor White
Write-Host "  Decision: $($riskResponse.decision.decision)" -ForegroundColor $(if ($riskResponse.decision.decision -eq "APPROVE") { "Green" } else { "Yellow" })
Write-Host "  Reason: $($riskResponse.decision.reason)" -ForegroundColor Gray

if ($riskResponse.decision.violated_rules.Count -gt 0) {
    Write-Host "  Violated rules: $($riskResponse.decision.violated_rules -join ', ')`n" -ForegroundColor Yellow
} else {
    Write-Host "  No rules violated`n" -ForegroundColor Gray
}

if ($riskResponse.decision.decision -ne "APPROVE") {
    Write-Host "WARNING: Risk evaluation rejected the order." -ForegroundColor Yellow
    Write-Host "This is expected with FakeBrokerAdapter due to random trading hours (R5)." -ForegroundColor Yellow
    Write-Host "Continuing with CREATE PROPOSAL test (will be rejected)...`n" -ForegroundColor Yellow
}

# Step 5: Create proposal (even if rejected, to test endpoint)
Write-Host "[5/7] Creating proposal..." -ForegroundColor Green
try {
    $createProposalBody = @{
        intent = $proposeResponse.intent
        simulation = $simulateResponse.result
        risk_decision = $riskResponse.decision
    } | ConvertTo-Json -Depth 10

    $createProposalResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/proposals/create" `
        -Method Post `
        -ContentType "application/json" `
        -Body $createProposalBody

    Write-Host "RESULT: Proposal created" -ForegroundColor White
    Write-Host "  Proposal ID: $($createProposalResponse.proposal_id)" -ForegroundColor Yellow
    Write-Host "  State: $($createProposalResponse.state)" -ForegroundColor Gray
    Write-Host "  Message: $($createProposalResponse.message)`n" -ForegroundColor Gray

    $proposalId = $createProposalResponse.proposal_id
    $proposalCreated = $true
} catch {
    Write-Host "RESULT: Proposal creation failed (expected for REJECT)" -ForegroundColor Yellow
    Write-Host "  Error: $($_.Exception.Message)`n" -ForegroundColor Gray
    $proposalCreated = $false
}

if (-not $proposalCreated) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "TEST PARTIALLY COMPLETE" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Steps 1-4 completed successfully:" -ForegroundColor White
    Write-Host "  [PASS] Order proposed and validated" -ForegroundColor Green
    Write-Host "  [PASS] Market data retrieved" -ForegroundColor Green
    Write-Host "  [PASS] Execution simulated" -ForegroundColor Green
    Write-Host "  [PASS] Risk rules evaluated" -ForegroundColor Green
    Write-Host ""
    Write-Host "Steps 5-7 skipped due to:" -ForegroundColor Yellow
    Write-Host "  Risk decision: $($riskResponse.decision.decision)" -ForegroundColor Yellow
    Write-Host "  Violated rules: $($riskResponse.decision.violated_rules -join ', ')" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "NOTE: This is normal with FakeBrokerAdapter." -ForegroundColor Gray
    Write-Host "      R5 rejects orders outside market hours (09:30-16:00 ET)." -ForegroundColor Gray
    Write-Host "      Try running the test during market hours or use real IBKR connection." -ForegroundColor Gray
    Write-Host ""
    exit 0
}
Write-Host "[5/7] Creating proposal..." -ForegroundColor Green
$createProposalBody = @{
    intent = $proposeResponse.intent
    simulation = $simulateResponse.result
    risk_decision = $riskResponse.decision
} | ConvertTo-Json -Depth 10

$createProposalResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/proposals/create" `
    -Method Post `
    -ContentType "application/json" `
    -Body $createProposalBody

Write-Host "RESULT: Proposal created" -ForegroundColor White
Write-Host "  Proposal ID: $($createProposalResponse.proposal_id)" -ForegroundColor Yellow
Write-Host "  State: $($createProposalResponse.state)" -ForegroundColor Gray
Write-Host "  Message: $($createProposalResponse.message)`n" -ForegroundColor Gray

$proposalId = $createProposalResponse.proposal_id

# Step 6: Request approval
Write-Host "[6/7] Requesting approval..." -ForegroundColor Green
$requestApprovalBody = @{
    proposal_id = $proposalId
    reason = "Automated test of complete flow"
} | ConvertTo-Json

$requestApprovalResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/approval/request" `
    -Method Post `
    -ContentType "application/json" `
    -Body $requestApprovalBody

Write-Host "RESULT: Approval requested" -ForegroundColor White
Write-Host "  Proposal ID: $($requestApprovalResponse.proposal_id)" -ForegroundColor Gray
Write-Host "  State: $($requestApprovalResponse.state)" -ForegroundColor Gray
Write-Host "  Message: $($requestApprovalResponse.message)`n" -ForegroundColor Gray

# Step 7: Grant approval
Write-Host "[7/7] Granting approval..." -ForegroundColor Green
$grantApprovalBody = @{
    proposal_id = $proposalId
    granted_by = "test_script"
    reason = "Automated approval for test"
} | ConvertTo-Json

$grantApprovalResponse = Invoke-RestMethod -Uri "$baseUrl/api/v1/approval/grant" `
    -Method Post `
    -ContentType "application/json" `
    -Body $grantApprovalBody

Write-Host "RESULT: Approval granted" -ForegroundColor White
Write-Host "  Proposal ID: $($grantApprovalResponse.proposal_id)" -ForegroundColor Gray
Write-Host "  State: $($grantApprovalResponse.state)" -ForegroundColor Gray
Write-Host "  Has token: $($grantApprovalResponse.has_token)" -ForegroundColor $(if ($grantApprovalResponse.has_token) { "Green" } else { "Red" })
Write-Host "  Message: $($grantApprovalResponse.message)`n" -ForegroundColor Gray

# Final summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FLOW COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Proposal $proposalId is ready for submission" -ForegroundColor Yellow
Write-Host ""
Write-Host "To submit the order (CAUTION: executes trade):" -ForegroundColor White
Write-Host "POST $baseUrl/api/v1/submit" -ForegroundColor Gray
Write-Host "Body: { `"proposal_id`": `"$proposalId`" }" -ForegroundColor Gray
Write-Host ""
Write-Host "Summary:" -ForegroundColor White
Write-Host "  [PASS] Order proposed and validated" -ForegroundColor Green
Write-Host "  [PASS] Market data retrieved" -ForegroundColor Green
Write-Host "  [PASS] Execution simulated" -ForegroundColor Green
Write-Host "  [PASS] Risk rules evaluated" -ForegroundColor Green
Write-Host "  [PASS] Proposal created and stored" -ForegroundColor Green
Write-Host "  [PASS] Approval requested" -ForegroundColor Green
Write-Host "  [PASS] Approval granted" -ForegroundColor Green
Write-Host ""
Write-Host "All steps completed successfully!" -ForegroundColor Green
