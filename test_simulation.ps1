# Test Order Simulation
# Simula l'esecuzione di un ordine con calcolo di fees, slippage e cash impact

$body = @{
    intent = @{
        account_id = "DU123456"
        instrument = @{
            symbol = "AAPL"
            type = "STK"
            exchange = "SMART"
            currency = "USD"
        }
        side = "BUY"
        order_type = "MKT"
        quantity = 5
        reason = "Test order from PowerShell"
        strategy_tag = "manual_test"
        time_in_force = "DAY"
    }
    account_id = "DU123456"
} | ConvertTo-Json -Depth 10

Write-Host "`n📊 Testing Order Simulation..." -ForegroundColor Cyan
Write-Host "Endpoint: POST /api/v1/simulate`n" -ForegroundColor Gray

$response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/simulate" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body

Write-Host "✅ Simulation Result:" -ForegroundColor Green
$response | ConvertTo-Json -Depth 10
