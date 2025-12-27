$baseUrl = "http://localhost:8001"

Write-Host "`n===== TESTING API ENDPOINTS ====="

# Test 1: Health
Write-Host "`n[1] Testing Health Check..."
try {
    $health = Invoke-RestMethod -Uri "$baseUrl/" -Method GET
    Write-Host "SUCCESS: $($health.service) v$($health.version) - $($health.status)"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

# Test 2: Portfolio
Write-Host "`n[2] Testing Portfolio..."
try {
    $portfolio = Invoke-RestMethod -Uri "$baseUrl/api/v1/portfolio?account_id=DU1234567" -Method GET
    Write-Host "SUCCESS: Total Value = $($portfolio.total_value), Positions = $($portfolio.positions.Count)"
    Write-Host "  Positions:"
    foreach ($pos in $portfolio.positions) {
        Write-Host "    - $($pos.symbol): qty=$($pos.quantity), value=$($pos.market_value)"
    }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

# Test 3: Positions
Write-Host "`n[3] Testing Positions..."
try {
    $positions = Invoke-RestMethod -Uri "$baseUrl/api/v1/positions?account_id=DU1234567" -Method GET
    Write-Host "SUCCESS: Found $($positions.positions.Count) positions"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

# Test 4: Market Data
Write-Host "`n[4] Testing Market Data (AAPL)..."
try {
    $market = Invoke-RestMethod -Uri "$baseUrl/api/v1/market/snapshot?instrument=AAPL" -Method GET
    Write-Host "SUCCESS: instrument=$($market.instrument), bid=$($market.bid), ask=$($market.ask)"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

# Test 5: Search Instruments (now optional parameter)
Write-Host "`n[5] Testing Instrument Search (no query)..."
try {
    $search = Invoke-RestMethod -Uri "$baseUrl/api/v1/instruments/search" -Method GET
    Write-Host "SUCCESS: Found $($search.candidates.Count) instruments"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host "`n===== TESTS COMPLETE ====="
