# Test con account reale DU0369590
Write-Host "`nTesting con account DU0369590..." -ForegroundColor Cyan

# Portfolio
try {
    $portfolio = Invoke-RestMethod "http://localhost:8001/api/v1/portfolio?account_id=DU0369590"
    Write-Host "SUCCESS - Portfolio:" -ForegroundColor Green
    Write-Host "  Total Value: $($portfolio.total_value)" -ForegroundColor Yellow
    Write-Host "  Positions: $($portfolio.positions.Count)" -ForegroundColor Yellow
} catch {
    Write-Host "FAILED Portfolio: $($_.Exception.Message)" -ForegroundColor Red
}

# Market Data
try {
    $market = Invoke-RestMethod "http://localhost:8001/api/v1/market/snapshot?instrument=AAPL"
    Write-Host "`nSUCCESS - Market Data AAPL:" -ForegroundColor Green
    Write-Host "  Bid: $($market.bid)" -ForegroundColor Yellow
    Write-Host "  Ask: $($market.ask)" -ForegroundColor Yellow
} catch {
    Write-Host "FAILED Market: $($_.Exception.Message)" -ForegroundColor Red
}

# Search
try {
    $search = Invoke-RestMethod "http://localhost:8001/api/v1/instruments/search?limit=3"
    Write-Host "`nSUCCESS - Instrument Search:" -ForegroundColor Green
    Write-Host "  Found: $($search.candidates.Count) instruments" -ForegroundColor Yellow
} catch {
    Write-Host "FAILED Search: $($_.Exception.Message)" -ForegroundColor Red
}
