# Test Risk Evaluation
# Valuta un ordine contro le regole R1-R12

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
    simulation = @{
        status = "SUCCESS"
        execution_price = "190.50"
        gross_notional = "952.50"
        estimated_fee = "1.00"
        estimated_slippage = "0.48"
        net_notional = "953.98"
        cash_before = "50000.00"
        cash_after = "49046.02"
        exposure_before = "55500.00"
        exposure_after = "56453.98"
        warnings = @()
        error_message = $null
    }
    account_id = "DU123456"
} | ConvertTo-Json -Depth 10

Write-Host "`n🛡️ Testing Risk Evaluation..." -ForegroundColor Cyan
Write-Host "Endpoint: POST /api/v1/risk/evaluate`n" -ForegroundColor Gray

$response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/risk/evaluate" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body

Write-Host "✅ Risk Decision:" -ForegroundColor Green
$response | ConvertTo-Json -Depth 10

Write-Host "`n📋 Summary:" -ForegroundColor Yellow
Write-Host "  Decision: $($response.decision)" -ForegroundColor $(if($response.decision -eq "APPROVE"){"Green"}else{"Red"})
Write-Host "  Reason: $($response.reason)" -ForegroundColor Gray

if ($response.violated_rules.Count -gt 0) {
    Write-Host "  Violated Rules: $($response.violated_rules -join ', ')" -ForegroundColor Red
} else {
    Write-Host "  Violated Rules: None ✓" -ForegroundColor Green
}
