# Test Integration with Open WebUI
# Simulates API calls that Open WebUI would make

Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  IBKR AI Broker - Open WebUI Integration Test          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

$baseUrl = "http://localhost:8001"
$accountId = "DU1234567"
$testsPassed = 0
$testsFailed = 0

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = "GET",
        [string]$Body = $null
    )
    
    Write-Host "`n$Name" -ForegroundColor Yellow
    try {
        if ($Method -eq "POST") {
            $response = Invoke-RestMethod -Method POST -Uri $Url -Body $Body -ContentType "application/json" -ErrorAction Stop
        } else {
            $response = Invoke-RestMethod -Uri $Url -ErrorAction Stop
        }
        Write-Host "   SUCCESS" -ForegroundColor Green
        $script:testsPassed++
        return $response
    } catch {
        Write-Host "   FAILED: $($_.Exception.Message)" -ForegroundColor Red
        $script:testsFailed++
        return $null
    }
}

# Test 1: Health Check
Write-Host "`n━━━ Test 1: Health Check ━━━" -ForegroundColor Cyan
$health = Test-Endpoint "Health Check" "$baseUrl/"
if ($health) {
    Write-Host "   Service: $($health.service)" -ForegroundColor White
    Write-Host "   Version: $($health.version)" -ForegroundColor White
    Write-Host "   Status: $($health.status)" -ForegroundColor White
}

# Test 2: Portfolio
Write-Host "`n━━━ Test 2: Portfolio Management ━━━" -ForegroundColor Cyan
$portfolio = Test-Endpoint "Get Portfolio" "$baseUrl/api/v1/portfolio?account_id=$accountId"
if ($portfolio) {
    Write-Host "   Total Value: `$$($portfolio.total_value)" -ForegroundColor White
    Write-Host "   Cash: `$$($portfolio.cash)" -ForegroundColor White
    Write-Host "   Positions: $($portfolio.positions.Count)" -ForegroundColor White
    if ($portfolio.positions.Count -gt 0) {
        Write-Host "   Top position: $($portfolio.positions[0].symbol) ($($portfolio.positions[0].quantity) shares)" -ForegroundColor Gray
    }
}

# Test 3: Positions
Write-Host "`n━━━ Test 3: Positions ━━━" -ForegroundColor Cyan
$positions = Test-Endpoint "Get Positions" "$baseUrl/api/v1/positions?account_id=$accountId"
if ($positions -and $positions.Count -gt 0) {
    Write-Host "   Found $($positions.Count) positions:" -ForegroundColor White
    $positions | ForEach-Object {
        Write-Host "   - $($_.symbol): $($_.quantity) @ `$$($_.avg_cost)" -ForegroundColor Gray
    }
}

# Test 4: Market Data
Write-Host "`n━━━ Test 4: Market Data ━━━" -ForegroundColor Cyan
$symbols = @("AAPL", "MSFT", "TSLA")
foreach ($symbol in $symbols) {
    $snapshot = Test-Endpoint "Market Snapshot $symbol" "$baseUrl/api/v1/market/snapshot?instrument=$symbol"
    if ($snapshot) {
        Write-Host "   $($snapshot.symbol): Last=`$$($snapshot.last_price) Bid=`$$($snapshot.bid) Ask=`$$($snapshot.ask) Vol=$($snapshot.volume)" -ForegroundColor White
    }
}

# Test 5: Instrument Search
Write-Host "`n━━━ Test 5: Instrument Search ━━━" -ForegroundColor Cyan
$instruments = Test-Endpoint "Search All Instruments" "$baseUrl/api/v1/instruments/search?limit=5"
if ($instruments) {
    Write-Host "   Top 5 instruments:" -ForegroundColor White
    $instruments | ForEach-Object {
        Write-Host "   - $($_.symbol): $($_.name) ($($_.type))" -ForegroundColor Gray
    }
}

$searchApple = Test-Endpoint "Search 'AAPL'" "$baseUrl/api/v1/instruments/search?q=AAPL"
if ($searchApple) {
    Write-Host "   Found: $($searchApple[0].symbol) - $($searchApple[0].name)" -ForegroundColor White
}

# Test 6: Order Simulation
Write-Host "`n━━━ Test 6: Order Simulation ━━━" -ForegroundColor Cyan
$orderIntent = @{
    account_id = $accountId
    symbol = "AAPL"
    side = "BUY"
    quantity = 10
    order_type = "MKT"
} | ConvertTo-Json

$simulation = Test-Endpoint "Simulate BUY 10 AAPL" "$baseUrl/api/v1/simulate" "POST" $orderIntent
if ($simulation) {
    Write-Host "   Estimated Cost: `$$($simulation.estimated_cost)" -ForegroundColor White
    Write-Host "   New Cash: `$$($simulation.new_cash)" -ForegroundColor White
    Write-Host "   New Total Value: `$$($simulation.new_total_value)" -ForegroundColor White
    Write-Host "   Impact: $($simulation.impact_pct)%" -ForegroundColor White
}

# Test 7: Risk Evaluation
Write-Host "`n━━━ Test 7: Risk Evaluation ━━━" -ForegroundColor Cyan
$riskEval = Test-Endpoint "Risk Evaluation" "$baseUrl/api/v1/risk/evaluate" "POST" $orderIntent
if ($riskEval) {
    $color = if ($riskEval.decision -eq "APPROVE") { "Green" } else { "Red" }
    Write-Host "   Decision: $($riskEval.decision)" -ForegroundColor $color
    Write-Host "   Reason: $($riskEval.reason)" -ForegroundColor White
    if ($riskEval.violated_rules -and $riskEval.violated_rules.Count -gt 0) {
        Write-Host "   Violated Rules: $($riskEval.violated_rules -join ', ')" -ForegroundColor Yellow
    }
    Write-Host "   Metrics:" -ForegroundColor White
    Write-Host "     - Position Size: `$$($riskEval.metrics.position_size)" -ForegroundColor Gray
    Write-Host "     - Portfolio %: $($riskEval.metrics.position_size_pct)%" -ForegroundColor Gray
}

# Test 8: Proposal Creation
Write-Host "`n━━━ Test 8: Proposal Creation ━━━" -ForegroundColor Cyan
$proposalReq = @{
    account_id = $accountId
    symbol = "MSFT"
    side = "BUY"
    quantity = 5
    order_type = "LMT"
    limit_price = "350.00"
    reason = "Test proposal from integration script"
} | ConvertTo-Json

$proposal = Test-Endpoint "Create Proposal" "$baseUrl/api/v1/proposals/create" "POST" $proposalReq
if ($proposal) {
    Write-Host "   Proposal ID: $($proposal.proposal_id)" -ForegroundColor White
    Write-Host "   State: $($proposal.state)" -ForegroundColor White
    Write-Host "   Created: $($proposal.created_at)" -ForegroundColor White
}

# Test 9: List Orders
Write-Host "`n━━━ Test 9: Orders ━━━" -ForegroundColor Cyan
$orders = Test-Endpoint "List Orders" "$baseUrl/api/v1/orders?account_id=$accountId"
if ($orders) {
    Write-Host "   Found $($orders.Count) orders" -ForegroundColor White
    if ($orders.Count -gt 0) {
        $orders | Select-Object -First 3 | ForEach-Object {
            Write-Host "   - $($_.symbol) $($_.side) $($_.quantity) @ $($_.status)" -ForegroundColor Gray
        }
    }
}

# Test 10: Instruments by Type
Write-Host "`n━━━ Test 10: Instruments by Type ━━━" -ForegroundColor Cyan
$stocks = Test-Endpoint "Search STK" "$baseUrl/api/v1/instruments/search?type=STK&limit=3"
if ($stocks) {
    Write-Host "   Stocks:" -ForegroundColor White
    $stocks | ForEach-Object { Write-Host "   - $($_.symbol)" -ForegroundColor Gray }
}

# Summary
Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Test Summary                                           ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host "`n   ✅ Passed: $testsPassed" -ForegroundColor Green
Write-Host "   ❌ Failed: $testsFailed" -ForegroundColor $(if($testsFailed -gt 0){"Red"}else{"Gray"})
$total = $testsPassed + $testsFailed
$successRate = if($total -gt 0){[math]::Round(($testsPassed / $total) * 100, 2)}else{0}
Write-Host "   📊 Success Rate: $successRate%" -ForegroundColor $(if($successRate -gt 80){"Green"}elseif($successRate -gt 50){"Yellow"}else{"Red"})

if ($testsFailed -eq 0) {
    Write-Host "`n🎉 ALL TESTS PASSED! Open WebUI integration is working correctly." -ForegroundColor Green
} else {
    Write-Host "`n⚠️  Some tests failed. Check the output above for details." -ForegroundColor Yellow
}

Write-Host "`n💡 To use with Open WebUI:" -ForegroundColor Cyan
Write-Host "   URL: http://host.docker.internal:8001" -ForegroundColor White
Write-Host "   OpenAPI Spec: http://host.docker.internal:8001/openapi.json" -ForegroundColor White
Write-Host "`n📝 Example prompts to try:" -ForegroundColor Cyan
Write-Host "   - 'Mostrami il mio portfolio'" -ForegroundColor Gray
Write-Host "   - 'Qual è il prezzo di AAPL?'" -ForegroundColor Gray
Write-Host "   - 'Simula l'acquisto di 10 azioni MSFT'" -ForegroundColor Gray
Write-Host "   - 'Valuta il rischio di comprare 50 azioni TSLA'" -ForegroundColor Gray
