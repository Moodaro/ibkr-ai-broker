# Complete Approval Flow Test Script (FORCE APPROVE)
# For testing: bypasses trading hours check by mocking APPROVE decision

$baseUrl = "http://localhost:8000"
$correlationId = [guid]::NewGuid().ToString()

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "COMPLETE APPROVAL FLOW TEST (FORCED)" -ForegroundColor Cyan
Write-Host "Correlation ID: $correlationId" -ForegroundColor Yellow
Write-Host "WARNING: This test forces APPROVE for demo purposes" -ForegroundColor Yellow
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

# Step 4: Force APPROVE decision (bypassing actual risk evaluation for demo)
Write-Host "[4/7] Creating forced APPROVE decision..." -ForegroundColor Green
$forcedRiskDecision = @{
    decision = "APPROVE"
    reason = "All risk checks passed (FORCED for test)"
    violated_rules = @()
    warnings = @()
    metrics = @{}
}

Write-Host "RESULT: Risk decision forced" -ForegroundColor Yellow
Write-Host "  Decision: APPROVE (forced)" -ForegroundColor Green
Write-Host "  NOTE: Actual risk evaluation would run R1-R12 checks`n" -ForegroundColor Gray

# Step 5: Create proposal
Write-Host "[5/7] Creating proposal..." -ForegroundColor Green
$createProposalBody = @{
    intent = $proposeResponse.intent
    simulation = $simulateResponse.result
    risk_decision = $forcedRiskDecision
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
Write-Host "  [SKIP] Risk rules evaluation (forced APPROVE)" -ForegroundColor Yellow
Write-Host "  [PASS] Proposal created and stored" -ForegroundColor Green
Write-Host "  [PASS] Approval requested" -ForegroundColor Green
Write-Host "  [PASS] Approval granted" -ForegroundColor Green
Write-Host ""
Write-Host "All steps completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "NOTE: This test bypassed actual risk evaluation (R1-R12)." -ForegroundColor Yellow
Write-Host "      In production, use the normal flow with real risk checks." -ForegroundColor Yellow
