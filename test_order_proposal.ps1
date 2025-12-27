# Test Order Proposal - PowerShell version

$body = @{
    account_id = "DU123456"
    symbol = "AAPL"
    side = "BUY"
    order_type = "MKT"
    quantity = 5
    exchange = "SMART"
    currency = "USD"
    instrument_type = "STK"
    reason = "Test order from PowerShell"
    strategy_tag = "manual_test"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/propose" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
