# Connessione IBKR Reale

Guida per collegare il sistema al tuo conto Interactive Brokers reale (DU0369590).

## Prerequisiti

1. **Conto IBKR attivo** con API abilitata
2. **IB Gateway** o **TWS** (Trader Workstation) installato
3. **Python 3.12+** con dipendenze installate

## Step 1: Avviare IB Gateway/TWS

### Opzione A: IB Gateway (Raccomandato per uso automatizzato)

1. Scarica **IB Gateway** da: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
2. Installa e avvia IB Gateway
3. Seleziona **Paper Trading** (porta 7497) o **Live Trading** (porta 7496)
4. Inserisci username e password IBKR
5. Vai a **Configure → Settings → API → Settings**:
   - ✅ **Enable ActiveX and Socket Clients**
   - ✅ **Allow connections from localhost only** (o specifica IP)
   - ✅ **Read-Only API** (opzionale, per sicurezza)
   - Porta: **7497** (paper) o **7496** (live)
   - ✅ **Download open orders on connection**
   - ❌ **Master API client ID** (lascia vuoto per permettere connessioni multiple)

### Opzione B: TWS (Trader Workstation)

1. Avvia TWS desktop application
2. Login con credenziali IBKR
3. **Edit → Global Configuration → API → Settings**:
   - ✅ **Enable ActiveX and Socket Clients**
   - Porta: **7497** (paper) o **7496** (live)
   - ✅ **Allow connections from localhost**

## Step 2: Configurare l'Applicazione

### Copia file di configurazione:

```powershell
cd 'C:\GIT-Project\AI\IBKR AI Broker'
copy .env.ibkr .env
```

### Modifica `.env` se necessario:

```env
# Broker type (ibkr = real, fake = simulated)
BROKER_TYPE=ibkr

# IBKR Connection
IBKR_HOST=127.0.0.1
IBKR_PORT=7497          # 7497 = paper, 7496 = live
IBKR_CLIENT_ID=1
IBKR_MODE=paper         # paper o live

# Safety
IBKR_READONLY_MODE=false  # true per impedire ordini
```

## Step 3: Testare la Connessione

```powershell
# Test connessione
python -c "from packages.broker_ibkr.real import IBKRBrokerAdapter; broker = IBKRBrokerAdapter(); print('✅ Connesso!'); broker.disconnect()"
```

**Output atteso**:
```
{"event": "ibkr_connecting", "host": "127.0.0.1", "port": 7497, ...}
{"event": "ibkr_connected", ...}
✅ Connesso!
{"event": "ibkr_disconnected", ...}
```

## Step 4: Avviare il Server con Broker Reale

```powershell
# Termina server fake (se attivo)
taskkill /F /IM python.exe

# Avvia server con broker reale
cd 'C:\GIT-Project\AI\IBKR AI Broker'
.\.venv\Scripts\python.exe -m uvicorn apps.assistant_api.main:app --host 0.0.0.0 --port 8001
```

**Verifica nei log**:
```
{"event": "broker_selected", "type": "ibkr", "reason": "explicit", ...}
{"event": "ibkr_connected", ...}
{"event": "broker_connected", "type": "IBKRBrokerAdapter", ...}
```

## Step 5: Testare API con Dati Reali

```powershell
# Test portfolio
Invoke-RestMethod "http://localhost:8001/api/v1/portfolio?account_id=DU0369590" | ConvertTo-Json

# Test posizioni
Invoke-RestMethod "http://localhost:8001/api/v1/positions?account_id=DU0369590" | ConvertTo-Json

# Test market data
Invoke-RestMethod "http://localhost:8001/api/v1/market/snapshot?instrument=AAPL" | ConvertTo-Json
```

**Output atteso**:
- Portfolio: **€1.000.083,26** cash, 0 posizioni (dati reali dal tuo conto)
- Posizioni: Array vuoto `[]` (nessuna posizione aperta)
- Market data: Prezzi di mercato reali AAPL

## Step 6: Testare in Open WebUI

1. Apri Open WebUI: http://localhost:3000
2. Chiedi: **"Mostrami il mio portfolio"**
3. Verifica: Dovrebbe mostrare **€1.000.083,26** disponibili

## Troubleshooting

### Errore: "Connection refused"

**Causa**: IB Gateway/TWS non in esecuzione o API non abilitata

**Soluzione**:
1. Verifica IB Gateway/TWS sia avviato
2. Controlla API Settings → Enable ActiveX and Socket Clients
3. Verifica porta corretta (7497 paper, 7496 live)

### Errore: "Client ID already in use"

**Causa**: Altra applicazione già connessa con stesso Client ID

**Soluzione**:
- Cambia `IBKR_CLIENT_ID=2` (o 3, 4, ..., max 32)
- Oppure disconnetti altre applicazioni (API Debugger, altre istanze)

### Errore: "Not connected"

**Causa**: Timeout connessione o crash TWS/Gateway

**Soluzione**:
1. Aumenta timeout: `IBKR_CONNECT_TIMEOUT=30`
2. Riavvia IB Gateway/TWS
3. Controlla firewall non blocchi porta

### Warning: "Market data not subscribed"

**Causa**: Conto non ha sottoscrizione dati di mercato

**Soluzione**:
- Usa dati **delayed** (gratuiti, ritardo 15-20 min)
- Oppure attiva sottoscrizione dati real-time in IBKR Account Management

## Sicurezza

### Modalità Read-Only

Per testare senza rischio ordini accidentali:

```env
IBKR_READONLY_MODE=true
```

Questo permette solo lettura portfolio/posizioni/market data, **blocca** tutti gli ordini.

### Kill Switch

Se qualcosa va storto durante trading automatizzato:

```python
from packages.kill_switch import get_kill_switch
kill_switch = get_kill_switch()
kill_switch.activate(reason="Emergency stop", activated_by="operator")
```

Tutti gli ordini verranno bloccati fino a `kill_switch.deactivate()`.

## Riferimenti

- [IBKR API Documentation](https://interactivebrokers.github.io/tws-api/)
- [AGENTS.md](AGENTS.md) - Development guide
- [LIVE_TRADING.md](LIVE_TRADING.md) - Live trading procedures

---

**⚠️ ATTENZIONE**: Prima di passare a **LIVE TRADING** (porta 7496), esegui **TUTTI** i test in paper trading (porta 7497).
