# Test Connessione IBKR Reale
# Prima di eseguire:
# 1. Avvia IB Gateway/TWS sulla porta 7497 (paper trading)
# 2. Copia .env.ibkr -> .env
# 3. Esegui: powershell -File test_ibkr_connection.ps1

Write-Host "`n=== Test Connessione IBKR Reale ===" -ForegroundColor Cyan
Write-Host "Account: DU0369590`n" -ForegroundColor Yellow

# Test 1: Verifica variabili d'ambiente
Write-Host "1. Verifica configurazione..." -ForegroundColor Green
if (Test-Path ".env") {
    $envContent = Get-Content ".env" | Where-Object { $_ -match "BROKER_TYPE" }
    if ($envContent -match "BROKER_TYPE=ibkr") {
        Write-Host "   ✅ BROKER_TYPE=ibkr configurato" -ForegroundColor Green
    } else {
        Write-Host "   ❌ BROKER_TYPE non configurato. Esegui: copy .env.ibkr .env" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "   ⚠️  File .env non trovato. Esegui: copy .env.ibkr .env" -ForegroundColor Yellow
}

# Test 2: Test connessione Python
Write-Host "`n2. Test connessione broker..." -ForegroundColor Green
$testScript = @"
import os
os.environ['BROKER_TYPE'] = 'ibkr'
from packages.broker_ibkr.real import IBKRBrokerAdapter
from packages.ibkr_config import get_ibkr_config

try:
    config = get_ibkr_config()
    print(f'   Connessione a {config.get_connection_string()}')
    
    broker = IBKRBrokerAdapter(config=config)
    print('   ✅ Broker connesso!')
    
    broker.disconnect()
    print('   ✅ Disconnesso')
except Exception as e:
    print(f'   ❌ Errore: {e}')
    exit(1)
"@

.\.venv\Scripts\python.exe -c $testScript

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n⚠️  Verifica che IB Gateway/TWS sia avviato sulla porta 7497" -ForegroundColor Yellow
    Write-Host "   Vedi: docs/IBKR_REAL_CONNECTION.md per istruzioni" -ForegroundColor Gray
    exit 1
}

# Test 3: Avvia server e testa API
Write-Host "`n3. Avvio server con broker reale..." -ForegroundColor Green
$env:BROKER_TYPE = "ibkr"

# Termina processi esistenti
taskkill /F /IM python.exe 2>$null | Out-Null

# Avvia server in background
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","apps.assistant_api.main:app","--host","0.0.0.0","--port","8001" -NoNewWindow -PassThru | Out-Null
Write-Host "   Server avviato, attendo startup..." -ForegroundColor Gray
Start-Sleep -Seconds 8

# Test 4: Test API con dati reali
Write-Host "`n4. Test API con account DU0369590..." -ForegroundColor Green

try {
    # Test portfolio
    Write-Host "   → Portfolio..." -ForegroundColor Gray
    $portfolio = Invoke-RestMethod "http://localhost:8001/api/v1/portfolio?account_id=DU0369590"
    Write-Host "      Total Value: EUR $($portfolio.total_value)" -ForegroundColor Green
    Write-Host "      Positions: $($portfolio.positions.Count)" -ForegroundColor Green
    Write-Host "      Cash: EUR $($portfolio.cash[0].balance)" -ForegroundColor Green
    
    # Test posizioni
    Write-Host "`n   → Posizioni..." -ForegroundColor Gray
    $positions = Invoke-RestMethod "http://localhost:8001/api/v1/positions?account_id=DU0369590"
    if ($positions.positions.Count -eq 0) {
        Write-Host "      Nessuna posizione aperta (corretto)" -ForegroundColor Cyan
    } else {
        Write-Host "      Posizioni: $($positions.positions.Count)" -ForegroundColor Green
        foreach ($pos in $positions.positions) {
            Write-Host "         - $($pos.symbol): $($pos.quantity) @ EUR $($pos.average_cost)" -ForegroundColor White
        }
    }
    
    # Test market data
    Write-Host "`n   → Market Data AAPL..." -ForegroundColor Gray
    $market = Invoke-RestMethod "http://localhost:8001/api/v1/market/snapshot?instrument=AAPL"
    Write-Host "      ✅ Bid: $($market.bid)" -ForegroundColor Green
    Write-Host "      ✅ Ask: $($market.ask)" -ForegroundColor Green
    Write-Host "      ✅ Last: $($market.last)" -ForegroundColor Green
    
    Write-Host "`nSUCCESSO! Broker reale connesso e funzionante" -ForegroundColor Green
    Write-Host "`nPuoi ora testare in Open WebUI:" -ForegroundColor Cyan
    Write-Host "  -> 'Mostrami il mio portfolio' - vedra EUR 1M+ disponibili" -ForegroundColor White
    Write-Host "  -> 'Quali posizioni ho?' - vedra posizioni reali o nessuna" -ForegroundColor White
    Write-Host "  -> 'Qual e il prezzo di AAPL?' - vedra prezzi di mercato reali" -ForegroundColor White
    
} catch {
    Write-Host "   Errore API: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "`n   Controlla log server per dettagli" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n=== Test completato ===" -ForegroundColor Cyan
Write-Host "Server in esecuzione su http://localhost:8001" -ForegroundColor Gray
Write-Host "Premi Ctrl+C per terminare il server" -ForegroundColor Gray
