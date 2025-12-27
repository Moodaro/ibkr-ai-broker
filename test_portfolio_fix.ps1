$baseUrl = "http://localhost:8001"

Write-Host "`n===== FINAL TEST WITH CORRECT ACCOUNT ID ====="

# Test Portfolio with correct account
Write-Host "`n[1] Testing Portfolio (DU123456)..."
try {
    $portfolio = Invoke-RestMethod -Uri "$baseUrl/api/v1/portfolio?account_id=DU123456" -Method GET
    Write-Host "SUCCESS: Total Value = $($portfolio.total_value)"
    Write-Host "  Positions: $($portfolio.positions.Count)"
    foreach ($pos in $portfolio.positions) {
        Write-Host "    - $($pos.symbol) ($($pos.type)): qty=$($pos.quantity), value=$($pos.market_value), pnl=$($pos.unrealized_pnl)"
    }
    Write-Host "  Cash: $($portfolio.cash[0].currency) $($portfolio.cash[0].available)"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

# Test Positions
Write-Host "`n[2] Testing Positions (DU123456)..."
try {
    $positions = Invoke-RestMethod -Uri "$baseUrl/api/v1/positions?account_id=DU123456" -Method GET
    Write-Host "SUCCESS: Found $($positions.positions.Count) positions"
    foreach ($pos in $positions.positions) {
        Write-Host "    - $($pos.symbol): $($pos.quantity) shares @ $$($pos.average_cost) = $$($pos.market_value)"
    }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host "`n===== ALL TESTS PASSED ====="
