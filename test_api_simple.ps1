# Simple Open WebUI Integration Test
# Tests all API endpoints

$baseUrl = "http://localhost:8001"
$account = "DU1234567"
Write-Host "`nIBKR AI Broker - API Integration Test`n" -ForegroundColor Cyan

# Test 1: Health
Write-Host "Test 1: Health Check" -ForegroundColor Yellow
$health = Invoke-RestMethod "$baseUrl/"
Write-Host "  Service: $($health.service) v$($health.version) - $($health.status)`n" -ForegroundColor Green

# Test 2: Portfolio  
Write-Host "Test 2: Portfolio" -ForegroundColor Yellow
$portfolio = Invoke-RestMethod "$baseUrl/api/v1/portfolio?account_id=$account"
Write-Host "  Total: $($portfolio.total_value) | Cash: $($portfolio.cash) | Positions: $($portfolio.positions.Count)`n" -ForegroundColor Green

# Test 3: Market Data
Write-Host "Test 3: Market Data (AAPL)" -ForegroundColor Yellow
$market = Invoke-RestMethod "$baseUrl/api/v1/market/snapshot?instrument=AAPL"
Write-Host "  $($market.symbol): Last=$($market.last_price) Bid=$($market.bid) Ask=$($market.ask)`n" -ForegroundColor Green

# Test 4: Instrument Search
Write-Host "Test 4: Instrument Search" -ForegroundColor Yellow
$instruments = Invoke-RestMethod "$baseUrl/api/v1/instruments/search?limit=3"
Write-Host "  Found $($instruments.Count) instruments:" -ForegroundColor Green
$instruments | ForEach-Object { Write-Host "    - $($_.symbol): $($_.name)" -ForegroundColor Gray }
Write-Host ""

# Test 5: Simulation
Write-Host "Test 5: Order Simulation (BUY 10 AAPL)" -ForegroundColor Yellow
$simBody = @{
    account_id = $account
    symbol = "AAPL"
    side = "BUY"
    quantity = 10
    order_type = "MKT"
} | ConvertTo-Json
$sim = Invoke-RestMethod -Method POST -Uri "$baseUrl/api/v1/simulate" -Body $simBody -ContentType "application/json"
Write-Host "  Cost: $($sim.estimated_cost) | New Cash: $($sim.new_cash) | Impact: $($sim.impact_pct)%`n" -ForegroundColor Green

# Test 6: Risk Evaluation
Write-Host "Test 6: Risk Evaluation" -ForegroundColor Yellow
$risk = Invoke-RestMethod -Method POST -Uri "$baseUrl/api/v1/risk/evaluate" -Body $simBody -ContentType "application/json"
$riskColor = if($risk.decision -eq 'APPROVE'){'Green'}else{'Red'}
Write-Host "  Decision: $($risk.decision) - $($risk.reason)`n" -ForegroundColor $riskColor

# Test 7: Proposal
Write-Host "Test 7: Create Proposal (BUY 5 MSFT LMT)" -ForegroundColor Yellow
$propBody = @{
    account_id = $account
    symbol = "MSFT"
    side = "BUY"
    quantity = 5
    order_type = "LMT"
    limit_price = "350.00"
    reason = "Integration test"
} | ConvertTo-Json
$proposal = Invoke-RestMethod -Method POST -Uri "$baseUrl/api/v1/proposals/create" -Body $propBody -ContentType "application/json"
Write-Host "  Proposal ID: $($proposal.proposal_id) | State: $($proposal.state)`n" -ForegroundColor Green

Write-Host "All tests completed successfully!" -ForegroundColor Green
Write-Host "`nOpen WebUI Configuration:" -ForegroundColor Cyan
Write-Host "  URL: http://host.docker.internal:8001" -ForegroundColor White
Write-Host "  OpenAPI Spec: http://host.docker.internal:8001/openapi.json" -ForegroundColor White
Write-Host "`nExample prompts:" -ForegroundColor Cyan
Write-Host "  - Mostrami il mio portfolio" -ForegroundColor Gray
Write-Host "  - Qual e il prezzo di AAPL?" -ForegroundColor Gray
Write-Host "  - Simula acquisto di 10 azioni MSFT" -ForegroundColor Gray
Write-Host "  - Valuta rischio di comprare 50 azioni TSLA" -ForegroundColor Gray
