# Roadmap completa: IBKR Paper→Live + Assistente LLM + MCP

> **Scopo**: costruire un sistema affidabile che usa Interactive Brokers (IBKR) in **paper trading** per leggere dati e simulare ordini, con un assistente LLM che **propone** azioni in formato strutturato, un **Risk Gate deterministico** che **decide**, e un flusso **two-step commit** che evita esecuzioni accidentali. Solo dopo mesi di evidenza e guardrail si abilita il live per azioni "banali" (es. ribilanciamento periodico entro soglie).

---

## 1) Principi non negoziabili

### 1.1 Separazione dei ruoli

* **LLM = consigliere**: analisi, spiegazione, proposta.
* **Codice deterministico = esecutore**: validazione, simulazione, controllo rischio, invio ordini.
* **Umano = autorità finale** (almeno finché non è dimostrata l'affidabilità): approvazione esplicita e/o policy di auto-commit limitatissima.

### 1.2 Safety by design

* Nessun ordine viene inviato senza:

  1. proposta strutturata validata
  2. simulazione (dry-run)
  3. Risk Gate APPROVE
  4. commit (approvazione o policy consentita)
* **Kill switch** sempre disponibile.
* **Audit log append-only**: ogni decisione è ricostruibile.

### 1.3 Test prima del live

* Paper trading per settimane/mesi con log, metriche e post-mortem.
* Live solo quando:

  * test E2E stabili
  * error budget sotto soglia
  * regole rischio "provate" e monitorate

---

## 2) Ambito e non-ambito

### 2.1 In scope (MVP → v1)

* Integrazione IBKR (Paper): posizioni, cash, ordini, market data di base.
* Proposte ordini in JSON (schema rigido).
* Simulazione ordini deterministica.
* Risk Gate v1.
* Two-step commit con dashboard minima.
* MCP server per esporre tool read-only e tool gated.

### 2.2 Out of scope (per evitare disastri)

* Scalping/high-frequency.
* Strategie ML "black box" in produzione senza risk model e validazione.
* Auto-trading completo senza supervisione umana.

---

## 3) Architettura consigliata

### 3.1 Vista ad alto livello

* **Assistant API (FastAPI)**

  * orchestration: richieste utente → chiamate tool → proposta ordine → simulazione → risk → richiesta commit
* **Broker Adapter (IBKR)**

  * implementa: read-only + trade endpoints
* **Trade Simulator**

  * calcola impatti pre-trade (cash, esposizione, concentrazione, slippage)
* **Risk Engine**

  * regole deterministiche + limiti + kill switch
* **Approval Service / Dashboard**

  * UI per approvare/rifiutare, vedere diff e motivazioni
* **Audit Store**

  * DB (SQLite → Postgres) + file log strutturati
* **MCP Server**

  * espone tool LLM: `broker.read_*`, `trade.simulate`, `risk.evaluate`, `trade.commit_request` (gated)

### 3.2 Regola d'oro dei tool

* Tutto ciò che **scrive** (ordini, cancellazioni, modifiche) deve passare per **Risk Gate + Commit**.
* Tool "write" non devono essere chiamabili direttamente dal modello senza gate.

---

## 4) Stack tecnologico (ottimizzato per VS Code + Copilot)

### 4.1 Linguaggi e framework

* **Python 3.12+**
* **FastAPI** (API + dashboard minimale) + **Pydantic v2** (schema e validazioni)
* DB: **SQLite** in dev → **PostgreSQL** in staging/prod
* Migrazioni: Alembic (o SQLModel + Alembic)
* Logging: structlog (o logging JSON)
* Test: pytest + coverage + hypothesis (per property-based testing su risk rules)

### 4.2 Dev Experience

* **Dev Containers** (VS Code) + docker-compose (db, redis opzionale)
* `pre-commit`: ruff, format, import sorting, mypy/pyright
* GitHub Actions: lint/test + security baseline

### 4.3 Agent/coding guidance

* File **AGENTS.md** in root (istruzioni per agent e Copilot)
* `.github/copilot-instructions.md` (istruzioni globali)
* PR template + issue template per lavoro incrementalissimo

---

## 5) Layout repository (mono-repo)

```
repo/
  AGENTS.md
  README.md
  ROADMAP.md (questo file)
  .github/
    copilot-instructions.md
    PULL_REQUEST_TEMPLATE.md
    workflows/
      ci.yml
  apps/
    assistant_api/
    mcp_server/
    dashboard/
  packages/
    broker_ibkr/
    risk_engine/
    trade_sim/
    schemas/
    audit_store/
  infra/
    docker-compose.yml
    devcontainer/
  docs/
    adr/
    threat-model.md
    runbook.md
```

---

## 6) File guida per Copilot (da mettere subito)

### 6.1 AGENTS.md (root) — versione iniziale (adatta a Copilot)

> **Nota**: tienilo conciso ma "operabile". Questo è un esempio completo ma puoi ridurlo.

```md
# AGENTS.md — Trading Assistant (IBKR + LLM + MCP)

## Project overview
- Goal: IBKR paper trading assistant. LLM proposes orders; deterministic gate validates/simulates/approves; two-step commit.
- Safety: NO direct LLM-to-broker writes. All writes go through RiskGate and explicit approval.

## Commands
- Install: `uv sync` (or `poetry install`)
- Lint: `ruff check .`
- Format: `ruff format .`
- Typecheck: `pyright` (or `mypy`)
- Tests: `pytest -q`
- Run API: `uvicorn apps.assistant_api.main:app --reload`
- Run MCP: `python apps/mcp_server/main.py`

## Code style
- Python 3.12+, type hints everywhere.
- Use Pydantic models for all IO.
- No business logic in FastAPI routes; keep in packages.

## Testing rules
- Every new feature must include unit tests.
- Risk rules must include property-based tests (Hypothesis) when feasible.
- Add integration tests using mocked broker responses.

## Boundaries (hard rules)
- Never submit live orders unless `ENV=live` and approval step passes.
- Never store secrets in repo. Use env vars.
- Any function named `submit_*` must require an explicit `ApprovalToken`.

## Security
- Treat all user inputs + LLM outputs as untrusted.
- Validate JSON strictly against schemas.
- Log all decisions as audit events.
```

### 6.2 .github/copilot-instructions.md (globale)

```md
# Copilot instructions

- Prefer small PRs (<=300 LOC) and incremental changes.
- Always add/update tests for any behavior change.
- Do not change public schemas without updating docs and migrations.
- Keep all trade-writing paths behind RiskGate + ApprovalToken.
- Before implementing new broker endpoints, add adapter interface + fake/mocked implementation.
- Use structured logging and emit an AuditEvent for every state transition.
```

### 6.3 Issue template (consigliato)

* "Definition of Done" ripetibile:

  * test pass
  * lint pass
  * audit events emessi
  * docs aggiornate

---

## 7) Modello di dominio e schemi (fondamenta)

### 7.1 Concetti principali

* **PortfolioSnapshot**: posizioni + cash + margine + timestamp
* **MarketSnapshot**: prezzo bid/ask/last + timestamp
* **OrderIntent**: proposta ordine (strumento, side, qty, tipo ordine, prezzo)
* **SimResult**: impatto stimato (cash, exposure, concentration, margin)
* **RiskDecision**: APPROVE/REJECT + motivi + regole violate
* **ApprovalToken**: token monouso generato dalla UI per "commit"

### 7.2 JSON Schema (approccio)

* Definisci JSON Schema in `packages/schemas/`.
* Genera Pydantic models dai JSON Schema (o viceversa) per garantire coerenza.

#### 7.2.1 OrderIntent (esempio)

Campi minimi:

* `account_id`
* `instrument`: `{ type: "STK|ETF|FUT|FX|CRYPTO", symbol, exchange?, currency }`
* `side`: `BUY|SELL`
* `quantity`: numero (con unità)
* `order_type`: `MKT|LMT|STP|STP_LMT`
* `limit_price?`, `stop_price?`
* `time_in_force`: `DAY|GTC|IOC`...
* `reason`: stringa breve
* `strategy_tag`: es. `rebal_monthly_v1`
* `constraints`: es. max slippage, max notional

#### 7.2.2 RiskDecision (esempio)

* `decision`: `APPROVE|REJECT|REVIEW`
* `violations`: lista di `{rule_id, severity, message, data}`
* `computed`: { exposure_before, exposure_after, cash_after, margin_after, ... }

---

## 8) Audit: event sourcing "leggero"

### 8.1 Perché

* Debug, compliance personale, post-mortem.
* Senza audit serio, l'automazione diventa "mistero" e i misteri bruciano soldi.

### 8.2 Eventi minimi (obbligatori)

* `PortfolioSnapshotTaken`
* `MarketSnapshotTaken`
* `OrderProposed`
* `OrderSimulated`
* `RiskGateEvaluated`
* `ApprovalRequested`
* `ApprovalGranted|ApprovalDenied`
* `OrderSubmitted`
* `OrderConfirmed` (se IBKR richiede conferma)
* `OrderFilled|OrderCancelled|OrderRejected`
* `KillSwitchActivated|KillSwitchReleased`

### 8.3 Persistenza

* Dev: SQLite (`audit.db`) + file log JSON.
* Prod: Postgres + retention policy.

---

## 9) Broker Adapter IBKR (Paper first)

### 9.1 Interfaccia comune (BrokerAdapter)

Definisci in `packages/broker_core/` (o dentro broker_ibkr) un protocollo:

* `get_accounts()`
* `get_portfolio(account_id)`
* `get_positions(account_id)`
* `get_cash(account_id)`
* `get_open_orders(account_id)`
* `get_market_snapshot(instrument)`
* `submit_order(order_intent) -> broker_order_id` (solo dopo gate)
* `cancel_order(broker_order_id)` (solo dopo gate)

### 9.2 Strategia implementativa

* Implementa prima **read-only**.
* Poi implementa submit in paper.
* Mantieni una **FakeBrokerAdapter** per test.

### 9.3 Gestione sessioni e resilienza

* Reconnect automatico.
* Retry con backoff.
* Rate limit.
* Circuit breaker se IBKR risponde errori ripetuti.

### 9.4 Conferma ordini (se richiesta)

* Prevedi uno stato intermedio: `PENDING_CONFIRMATION`.
* Il sistema deve supportare un endpoint "reply/confirm" e trattare eventuali warning.

---

## 10) Simulatore ordini (TradeSim)

### 10.1 Obiettivi

* Deterministico.
* Rapido.
* Sufficientemente realistico per il risk gate.

### 10.2 Input

* `PortfolioSnapshot`
* `MarketSnapshot`
* `OrderIntent`
* Parametri: slippage model, fee model (inizialmente semplice)

### 10.3 Output (SimResult)

* cash_after
* notional
* exposure_by_symbol_after
* concentration_after (max weight)
* estimated_slippage_cost
* margin_impact_estimate (se disponibile)

### 10.4 Modelli iniziali (semplici)

* Slippage: `max(spread/2, k * notional/liquidity_proxy)`
* Fee: flat o percentuale

---

## 11) Risk Engine (Risk Gate) — regole v1

### 11.1 Filosofia

* Regole semplici, esplicite, auditabili.
* Default: REJECT.

### 11.2 Config (risk_policy.yml)

Esempio parametri:

* `max_notional_per_trade`
* `max_position_weight`
* `max_total_positions`
* `allowed_instruments`
* `allowed_exchanges`
* `max_daily_loss`
* `max_drawdown`
* `max_leverage`
* `trade_window_hours`
* `require_limit_orders`

### 11.3 Regole base (implementazione)

* R1: Notional <= soglia
* R2: Peso post-trade <= soglia
* R3: Numero posizioni <= soglia
* R4: Strumento in allowlist
* R5: Order type consentito
* R6: Se kill switch attivo → REJECT
* R7: Daily loss limit → REJECT
* R8: Market data staleness (snapshot troppo vecchio) → REVIEW/REJECT

### 11.4 Severità

* `BLOCKER`: mai bypassabile
* `MAJOR`: richiede override manuale + reason
* `MINOR`: warning

### 11.5 Property-based tests

* Genera portafogli casuali e verifica invarianti:

  * mai superare max_position_weight se decision=APPROVE
  * notional sempre <= max_notional

---

## 12) Two-step commit (Approval)

### 12.1 Stati

* PROPOSED
* SIMULATED
* RISK_APPROVED / RISK_REJECTED
* APPROVAL_REQUESTED
* APPROVAL_GRANTED
* SUBMITTED
* CONFIRMED (se serve)
* FILLED/CANCELLED/REJECTED

### 12.2 ApprovalToken

* Generato dalla dashboard.
* Monouso, scadenza breve (es. 5 minuti).
* Legato all'hash dell'OrderIntent (anti-tamper).

### 12.3 Policy auto-commit (solo più avanti)

* Ammessa solo per:

  * ribilanciamento su ETF specifici
  * entro soglie minime (es. <0.5% NAV per trade)
  * solo ordini LIMIT
  * solo durante finestra oraria

---

## 13) MCP Server

### 13.1 Obiettivo

Esporre tool in modo standardizzato:

* `broker.read_portfolio`
* `broker.read_positions`
* `broker.read_market_snapshot`
* `trade.simulate`
* `risk.evaluate`
* `trade.request_commit`

### 13.2 Sicurezza MCP

* Tool write separati e gated.
* Autorizzazione: OAuth/PKCE (quando passi da prototipo a v1).
* Allowlist dei tool e dei parametri.

### 13.3 Prototipo vs produzione

* Prototipo locale: MCP su localhost con token statico.
* Produzione: OAuth resource server + audit + rate limit.

---

## 14) Assistant Orchestration (LLM)

### 14.1 Pattern "Planner → Proposer → Critic" (senza magia)

* **Planner**: chiarisce obiettivo e vincoli
* **Proposer**: emette `OrderIntent` conforme schema
* **Critic**: verifica coerenza logica (non sostituisce risk gate)

### 14.2 Output strutturato obbligatorio

* Ordini sempre come JSON conforme schema.
* Niente "testo libero" per parametri ordine.

### 14.3 Prompting pratico

* Includi sempre:

  * policy risk
  * contesto portafoglio
  * obiettivo utente
  * regole di default (LIMIT, size minima, ecc.)

---

## 15) Dashboard (minima ma salva-vita)

### 15.1 Feature MVP

* Lista proposte (stato + timestamp)
* Vista dettaglio: ordine + reason + simulazione + decisione risk
* Diff esposizioni prima/dopo
* Pulsanti: Approva / Rifiuta
* Kill switch
* Ricerca audit

### 15.2 Implementazione veloce

Opzioni:

* FastAPI + Jinja/HTMX (semplice, zero build)
* Streamlit (rapidissimo)
* Next.js (più lavoro, più UX)

---

## 16) Testing strategy (seria)

### 16.1 Unit

* Schemi e validazioni
* Risk rules
* Simulator

### 16.2 Integration

* Broker adapter con stub/mock
* Parser risposte IBKR
* Gestione errori e riconnessione

### 16.3 E2E (paper)

* Flusso completo: propose → simulate → risk → approve → submit → status

### 16.4 "Replay tests"

* Registra risposte IBKR (sanitize) e riproduci per test deterministici.

---

## 17) Observability e runbook

### 17.1 Logging

* JSON logs con correlation id
* Redazione dati sensibili

### 17.2 Metriche

* numero proposte
* % reject per regola
* latenza broker
* errori per endpoint
* drawdown giornaliero

### 17.3 Alert

* disconnessione broker
* order rejected
* daily loss threshold vicino

### 17.4 Runbook

* procedure kill switch
* procedure ripristino
* procedure "stuck order"

---

## 18) Threat model (minimo indispensabile)

Minacce principali:

* Prompt injection: input malevolo induce a chiamare tool pericolosi
* Tool misuse: tool write invocati fuori policy
* Credential theft
* Replay di ApprovalToken
* Data poisoning (market data)

Mitigazioni:

* Schema validation
* Tool allowlist
* ApprovalToken anti-tamper
* Secrets solo server-side
* Audit immutabile

---

## 19) Roadmap per sprint (dettagliata, con acceptance criteria)

### Sprint 0 — Bootstrap (1–2 giorni)

**Goal**: repo pronto per sviluppo agentico.

* [ ] crea struttura mono-repo
* [ ] aggiungi AGENTS.md + copilot-instructions.md
* [ ] devcontainer + docker-compose (db)
* [ ] pre-commit + ruff + pytest
* [ ] CI GitHub Actions (lint+test)

**Done**: `pytest`, `ruff`, build CI green.

### Sprint 1 — Audit foundation (2–4 giorni)

* [ ] definisci AuditEvent model
* [ ] storage SQLite + API `append_event()`
* [ ] middleware correlation id
* [ ] test unit su audit

**Done**: ogni endpoint emette almeno un audit event.

### Sprint 2 — IBKR read-only (Paper) (1–2 settimane)

* [ ] implementa BrokerAdapter + FakeBroker
* [ ] IBKR adapter: accounts, positions, cash, open orders
* [ ] market snapshot base
* [ ] integration test con FakeBroker

**Done**: endpoint `/portfolio` mostra dati paper reali; audit per ogni fetch.

### Sprint 3 — Schemi ordini + proposta strutturata (1 settimana)

* [ ] JSON Schema OrderIntent + Pydantic
* [ ] endpoint `POST /propose` che genera OrderIntent (mock LLM iniziale)
* [ ] validazione schema + error handling
* [ ] audit `OrderProposed`

**Done**: OrderIntent validato end-to-end.

### Sprint 4 — Simulatore v1 (1 settimana)

* [ ] trade_sim: calcolo notional, cash_after, exposure_after
* [ ] slippage/fee semplice
* [ ] test con casi noti
* [ ] endpoint `POST /simulate`

**Done**: sim deterministica, ripetibile, audit `OrderSimulated`.

### Sprint 5 — Risk Engine v1 (1 settimana)

* [ ] risk_policy.yml + loader
* [ ] regole R1–R8
* [ ] output RiskDecision strutturato
* [ ] property-based tests su invarianti
* [ ] endpoint `POST /risk/evaluate`

**Done**: gate blocca casi ovvi, logga motivi.

### Sprint 6 — Two-step commit + dashboard MVP (1–2 settimane)

* [ ] state machine per ordine
* [ ] ApprovalToken monouso
* [ ] UI lista proposte + dettaglio + approve/reject
* [ ] kill switch

**Done**: nessun submit senza token; UX sufficiente a operare quotidianamente.

### Sprint 7 — Submit order in paper (1–2 settimane)

* [ ] implementa `submit_order()` su IBKR paper
* [ ] gestisci conferma/warning (stato PENDING_CONFIRMATION)
* [ ] polling status ordini
* [ ] E2E test completo

**Done**: ordine paper eseguito con audit completo fino a FILLED.

### Sprint 8 — MCP server (read-only) (1 settimana)

* [ ] MCP server espone tool read-only
* [ ] limiti parametri, rate limit
* [ ] audit ogni tool call

**Done**: host LLM può leggere portafoglio senza possibilità di trade.

### Sprint 9 — MCP tool gated (1 settimana)

* [ ] aggiungi `trade.simulate` e `risk.evaluate` come tool
* [ ] `trade.request_commit` crea richiesta approval (non invia ordini)

**Done**: LLM può arrivare fino a "richiedere approvazione", ma non oltre.

### Sprint 10 — Hardening + go-live "banale" (2–6 settimane)

* [ ] logging/metrics/alert
* [ ] backup audit
* [ ] runbook completo
* [ ] live feature flag + doppio controllo
* [ ] policy auto-commit SOLO ribilanciamento minimo (opzionale)

**Done**: live attivo solo per azioni consentite, con monitoraggio e kill switch.

---

## 20) Checklist per passare da Paper a Live

### Prerequisiti

* 200+ ordini simulati in paper
* 50+ submit paper con successo
* 0 incidenti di "ordine non intenzionale"
* reject rate spiegabile

### Live fase 1

* size minime
* solo LIMIT
* solo strumenti super liquidi
* approvazione umana obbligatoria

### Live fase 2

* introdurre gradualità (nuovi strumenti, nuove regole)
* nessuna strategia "creativa" finché non hai metriche robuste

---

## 21) Prompt pack per Copilot (uso pratico)

### 21.1 Prompt "crea modulo"

* "Implementa `risk_engine` con regole R1–R8, config yaml, output RiskDecision, e test unit + property-based. Non toccare i path write del broker. Aggiorna AGENTS.md se aggiungi comandi."

### 21.2 Prompt "refactor sicuro"

* "Sposta la logica di simulazione fuori dalle route FastAPI in `packages/trade_sim`. Aggiungi test. Mantieni API invariata."

### 21.3 Prompt "integrazione IBKR"

* "Aggiungi metodo `get_open_orders(account_id)` all'adapter e aggiornare FakeBroker con dati finti coerenti. Aggiungi integration test."

---

## 22) Definizione di "successo" (metriche)

* Tempo medio da richiesta a proposta valida < 2s (read-only)
* 0 submit senza approval
* Audit coverage 100% per transizioni
* Percentuale di errori broker < 1% su 30 giorni

---

## 23) Note finali (per mantenere il sistema sano)

* Ogni volta che aggiungi un nuovo tool write: **aggiungi prima** una regola di risk e un test che lo blocchi.
* Se il modello "allucina" una cosa, non "promptare di più": aggiungi **schema più stretto**, validazioni, e fallback deterministici.
* Il lavoro vero è il risk management e l'osservabilità. Il resto è plumbing.

---

## 24) Link utili

### Documentazione IBKR

* [IBKR API Documentation](https://interactivebrokers.github.io/)
* [TWS API Guide](https://ibkrcampus.com/ibkr-api-page/twsapi-doc/)

### Best Practices Trading Systems

* [Safe AI Trading Patterns](https://github.com/topics/trading-bot)
* [Risk Management in Automated Trading](https://www.investopedia.com/articles/active-trading/090415/risk-management-techniques-active-traders.asp)

### MCP & LLM Integration

* [Model Context Protocol Specification](https://modelcontextprotocol.io/)
* [Structured Output Best Practices](https://platform.openai.com/docs/guides/structured-outputs)

---

**Versione**: 1.0  
**Ultima revisione**: 24 dicembre 2025  
**Prossima revisione**: dopo Sprint 3 o quando necessario
