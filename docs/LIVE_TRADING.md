# Live Trading Operations Guide

**⚠️ CRITICAL: This document contains mandatory procedures for live trading activation.**

**Status**: Ready for review (26/12/2025)

## Overview

This guide provides step-by-step procedures for safely transitioning from paper trading to live trading, and for operating the system in production.

## Safety Principles

1. **Never skip validation steps** - Each checklist item exists because of a potential failure mode
2. **Test in paper first** - All changes must be validated in paper trading before live
3. **Human approval required** - No automated live order submission without explicit human consent
4. **Kill switch always available** - Emergency stop must be accessible at all times
5. **Audit everything** - Every state transition must generate an audit event
6. **Default to reject** - When uncertain, the system must reject the order

## Pre-Flight Checklist (Paper → Live)

### Phase 1: Environment Validation

**Before changing ENV from paper to live:**

- [ ] **ENV variable verification**
  - [ ] Current ENV is set to `paper`
  - [ ] IBKR_PORT is `7497` (paper) or `7496` (live) - verify matches ENV
  - [ ] Database backups are enabled and tested
  - [ ] Log level is appropriate (INFO or WARNING for live, not DEBUG)

- [ ] **Credentials and connections**
  - [ ] IBKR API credentials for live account are secured (not in code)
  - [ ] Live account ID matches expected value (not paper account DU...)
  - [ ] TWS or IB Gateway connected to **live** mode (not paper)
  - [ ] Connection test successful: `python scripts/test_connection.py --env=live`
  - [ ] Portfolio fetch works: Can retrieve live positions and cash balance

- [ ] **Database and audit**
  - [ ] DATABASE_URL points to production database (not dev/test)
  - [ ] Audit store is writable and tested
  - [ ] Audit backup is configured and running
  - [ ] Disk space sufficient (>10GB recommended for audit logs)

### Phase 2: Risk Configuration Validation

- [ ] **Risk limits review**
  - [ ] risk_policy.yml reviewed by human (not just accepted defaults)
  - [ ] R1-R8 basic rules appropriate for live account size
  - [ ] R9-R12 advanced rules calibrated for live volatility
  - [ ] Position size limits match account size (not paper trading test values)
  - [ ] Max single trade value < 5% of portfolio
  - [ ] Max total exposure < 95% of portfolio value

- [ ] **Trading hours**
  - [ ] Market hours set correctly for your timezone
  - [ ] Pre-market and after-hours trading disabled (unless explicitly intended)
  - [ ] Holiday schedule reviewed (no trading on market holidays)

- [ ] **Volatility configuration**
  - [ ] volatility_provider type set to `historical` (not `mock`)
  - [ ] Fallback provider configured for degraded mode
  - [ ] Cache TTL appropriate for live trading (3600s = 1 hour default OK)
  - [ ] Symbol overrides removed (unless intentional)

### Phase 3: Kill Switch Validation

- [ ] **Kill switch functionality**
  - [ ] Kill switch triggers successfully in paper mode: `python scripts/test_kill_switch.py`
  - [ ] Kill switch state persists across restarts
  - [ ] Kill switch blocks all order submission paths
  - [ ] Dashboard kill switch button accessible and tested
  - [ ] Manual trigger via API works: `POST /api/v1/kill-switch/activate`
  - [ ] Audit events logged on trigger and reset

- [ ] **Automatic triggers configured**
  - [ ] Drawdown limit configured (R11: max_drawdown_pct, default 10%)
  - [ ] High water mark tracking enabled
  - [ ] Connection loss detection active
  - [ ] Error rate threshold set (recommended: 5 errors in 10 minutes → kill switch)

### Phase 4: Code and Test Validation

- [ ] **Test suite**
  - [ ] All tests passing: `pytest` (no skipped critical tests)
  - [ ] Integration tests with FakeBrokerAdapter passing
  - [ ] Risk engine tests passing (R1-R12, volatility)
  - [ ] Live readiness tests passing: `pytest tests/test_live_readiness.py`

- [ ] **Code review**
  - [ ] No hardcoded credentials in codebase: `grep -r "IBKR_PASSWORD" .`
  - [ ] No debug mode enabled in production code
  - [ ] All `submit_order()` calls require ApprovalToken
  - [ ] No `extra="allow"` in Pydantic schemas (strict validation)
  - [ ] Error handling: No silent exception catches

### Phase 5: Monitoring and Alerts

- [ ] **Monitoring setup**
  - [ ] Dashboard accessible and shows live data
  - [ ] Performance metrics being collected
  - [ ] Health check endpoint responding: `GET /api/v1/health`
  - [ ] Alert notifications configured (email, SMS, etc.)
  - [ ] Log aggregation working (if using centralized logging)

- [ ] **Alert conditions**
  - [ ] Drawdown exceeds threshold
  - [ ] Kill switch triggered
  - [ ] Risk violation count exceeds limit
  - [ ] Broker connection lost
  - [ ] Disk space low (<1GB)
  - [ ] Order rejection rate > 20%

### Phase 6: Operational Readiness

- [ ] **Documentation**
  - [ ] AGENTS.md reviewed by operator
  - [ ] LIVE_TRADING.md (this document) reviewed
  - [ ] Emergency contact information available
  - [ ] Broker support phone number available

- [ ] **Procedures documented**
  - [ ] Startup procedure (see below)
  - [ ] Shutdown procedure (see below)
  - [ ] Emergency response procedure (see below)
  - [ ] Incident handling process

- [ ] **Backup and recovery**
  - [ ] Database backup tested and verified
  - [ ] Audit log backup configured
  - [ ] Recovery procedure documented
  - [ ] Rollback plan available

### Phase 7: Final Go/No-Go Decision

**Decision maker**: [NAME] **Date**: [DATE] **Time**: [TIME]

- [ ] All checklist items above are ✅
- [ ] Team has reviewed and approved
- [ ] Broker account funded appropriately
- [ ] Market conditions are normal (not during major volatility event)
- [ ] Operator is available for monitoring (not on vacation, not EOD Friday)

**ENV change authorization**:
```bash
# Only execute after all checks pass
export ENV=live
export IBKR_PORT=7496

# Restart services
docker-compose restart assistant_api
docker-compose restart mcp_server
docker-compose restart dashboard
```

**First trade validation**:
- Start with minimum position size (1 share or $100)
- Verify order submission, approval, execution, and audit logging
- Confirm portfolio update reflects executed trade
- If any step fails: **Trigger kill switch immediately**

---

## Startup Procedure

### 1. Pre-start checks
```bash
# Check environment
echo $ENV  # Should be "live"
echo $IBKR_PORT  # Should be 7496
echo $DATABASE_URL  # Should be production DB

# Check TWS/Gateway
# Manually verify TWS or IB Gateway is running in LIVE mode (not paper)
# Login to live account, not paper account

# Check kill switch state
cat data/kill_switch_state.txt  # Should be "ACTIVE"
```

### 2. Start services
```bash
# Start database (if not already running)
docker-compose up -d postgres

# Start core services
docker-compose up -d assistant_api
docker-compose up -d mcp_server

# Start dashboard for monitoring
docker-compose up -d dashboard

# Verify all services healthy
curl http://localhost:8000/api/v1/health
curl http://localhost:8080/health
```

### 3. Verify connectivity
```bash
# Test broker connection
python scripts/test_connection.py --env=live

# Fetch portfolio (should show live positions)
curl http://localhost:8000/api/v1/portfolio

# Check audit store
python scripts/check_audit_store.py
```

### 4. Enable monitoring
- Open dashboard: http://localhost:8080
- Verify real-time data is updating
- Check alert configuration in dashboard settings

---

## Shutdown Procedure

### 1. Graceful shutdown
```bash
# Stop accepting new proposals (via kill switch)
curl -X POST http://localhost:8000/api/v1/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{"reason": "manual", "message": "Planned shutdown", "activated_by": "operator"}'

# Wait for pending approvals to be processed or expired
# Check approval service for pending items
curl http://localhost:8000/api/v1/approvals/pending
```

### 2. Cancel pending orders (optional)
```bash
# If immediate shutdown needed, cancel all open orders
# Use dashboard or API to cancel each pending order
# This requires approval for each cancellation (safety check)
```

### 3. Stop services
```bash
# Stop application services
docker-compose stop assistant_api
docker-compose stop mcp_server
docker-compose stop dashboard

# Database can stay running (or stop if maintenance needed)
# docker-compose stop postgres
```

### 4. Backup audit logs
```bash
# Backup audit store before long shutdown
python scripts/backup_audit_store.py --output=backups/audit_$(date +%Y%m%d_%H%M%S).db
```

---

## Emergency Response Procedure

### Scenario 1: Unexpected Loss / Drawdown

**Symptoms**: Portfolio value drops rapidly, R11 drawdown alert triggered

**Actions**:
1. **Trigger kill switch immediately** via dashboard or API
2. Review audit log for recent trades: `python scripts/audit_report.py --last=1h`
3. Check open positions in TWS/Gateway
4. If error in risk engine: Do NOT reset kill switch until fixed and tested
5. If market event: Evaluate position closure via TWS (manual, not via assistant)

### Scenario 2: Kill Switch Triggered Automatically

**Symptoms**: Kill switch triggered, audit log shows automatic trigger reason

**Actions**:
1. **Do not reset immediately** - Understand root cause first
2. Check trigger reason: `python scripts/check_kill_switch.py`
3. Investigate:
   - Drawdown: Review recent trades, check portfolio value
   - Error rate: Check logs for repeated errors
   - Connection loss: Verify TWS/Gateway status, network connectivity
   - Risk violation: Review rejected orders, check if risk limits too tight
4. Fix root cause
5. Test fix in paper trading environment
6. Only after validation: Reset kill switch via dashboard (requires human approval)

### Scenario 3: Broker Connection Lost

**Symptoms**: Cannot fetch portfolio, orders failing, connection errors

**Actions**:
1. Kill switch should auto-trigger on connection loss
2. Verify TWS/IB Gateway status (check if logged out, network issue)
3. Check broker status page: https://www.interactivebrokers.com/en/index.php?f=2225
4. If TWS crashed: Restart TWS/Gateway, reconnect
5. If network issue: Resolve network connectivity
6. Test connection: `python scripts/test_connection.py --env=live`
7. Only after stable connection: Reset kill switch

### Scenario 4: Rogue Order Submitted

**Symptoms**: Order executed that violates policy or was not approved

**Actions**:
1. **Trigger kill switch immediately**
2. Reverse position via TWS (manual trade, not via assistant)
3. Audit log forensics: `python scripts/audit_report.py --event=order_submitted --last=24h`
4. Identify approval bypass or bug
5. Fix code vulnerability
6. Add test case to prevent recurrence
7. Review all code paths that call `broker.submit_order()`

### Scenario 5: Disk Space Exhausted

**Symptoms**: Audit log writes failing, database errors

**Actions**:
1. Trigger kill switch (cannot operate without audit trail)
2. Free disk space: Archive old audit logs, clean up temp files
3. Verify audit store writable: `python scripts/check_audit_store.py`
4. Resume operations only after sufficient space (>5GB free)

---

## Incident Handling Process

### 1. Detection
- Automated alert (email, SMS, dashboard notification)
- Manual observation (dashboard, logs, broker platform)

### 2. Triage
- **Severity 1 (Critical)**: Loss of money, data corruption, kill switch triggered
  - Response time: Immediate (< 5 minutes)
  - Escalation: Notify team lead immediately
- **Severity 2 (High)**: Service degraded, orders failing, high error rate
  - Response time: < 30 minutes
  - Escalation: Notify team lead within 1 hour
- **Severity 3 (Medium)**: Performance issues, non-critical warnings
  - Response time: < 4 hours
  - Escalation: Log issue, address during next maintenance window

### 3. Response
- Trigger kill switch if trading risk exists
- Collect diagnostic data (logs, audit events, portfolio state)
- Identify root cause
- Implement fix or workaround
- Test fix in paper environment

### 4. Recovery
- Deploy fix to live environment
- Validate fix with minimum position size test trade
- Reset kill switch only after successful validation
- Resume normal operations

### 5. Post-Incident Review
- Document incident: `docs/incidents/YYYYMMDD_incident_summary.md`
- Root cause analysis
- Action items to prevent recurrence
- Update this document with lessons learned

---

## Monitoring Checklist (Daily)

### Morning (before market open)
- [ ] All services running and healthy
- [ ] Kill switch is ACTIVE (not triggered from previous day)
- [ ] No pending alerts or warnings
- [ ] Portfolio value matches expected (no overnight changes)
- [ ] Audit log backup successful
- [ ] Disk space sufficient (>5GB)

### Intraday (periodic checks)
- [ ] Dashboard shows real-time updates
- [ ] No unusual error rate (< 5% rejection rate is normal)
- [ ] Kill switch still ACTIVE
- [ ] No unexpected drawdown alerts

### Evening (after market close)
- [ ] Review day's trades: `python scripts/daily_trade_report.py`
- [ ] Portfolio reconciliation: Compare assistant vs broker positions
- [ ] Audit log review: Check for any anomalies
- [ ] Backup audit logs
- [ ] Check for pending approvals (should be none)

---

## Rollback Plan

If live trading must be reverted to paper trading:

1. **Trigger kill switch** (stop all trading immediately)
2. Close all open positions via TWS (manual)
3. Change environment:
   ```bash
   export ENV=paper
   export IBKR_PORT=7497
   ```
4. Restart all services
5. Verify connection to paper account
6. Test with paper account before resetting kill switch

---

## Contact Information

| Role | Name | Phone | Email |
|------|------|-------|-------|
| System Operator | [NAME] | [PHONE] | [EMAIL] |
| Backup Operator | [NAME] | [PHONE] | [EMAIL] |
| Team Lead | [NAME] | [PHONE] | [EMAIL] |
| IBKR Support | - | +1-312-542-6901 | - |

---

## Lessons Learned (Update after incidents)

### [DATE] - Incident: [SHORT DESCRIPTION]
- **Root cause**: [DESCRIPTION]
- **Impact**: [DESCRIPTION]
- **Resolution**: [DESCRIPTION]
- **Prevention**: [CHECKLIST ITEM ADDED / CODE CHANGE]

---

**Last Updated**: 26/12/2025
**Next Review**: [DATE] (quarterly review recommended)
**Document Owner**: [NAME]
