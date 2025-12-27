try {
    $response = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/portfolio?account_id=DU1234567" -Method GET
    Write-Host "SUCCESS! Portfolio recuperato:" -ForegroundColor Green
    Write-Host "  Total Value: $($response.total_value)" -ForegroundColor Yellow
    Write-Host "  Positions: $($response.positions.Count)" -ForegroundColor Yellow
    foreach ($pos in $response.positions) {
        Write-Host "    - $($pos.symbol): $($pos.quantity) shares = `$$($pos.market_value)" -ForegroundColor Cyan
    }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}
