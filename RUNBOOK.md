# RUNBOOK.md — Operational Procedures

**IBKR AI Broker - Trading Assistant**

This runbook provides step-by-step procedures for operating, monitoring, and troubleshooting the IBKR AI Trading Broker system in production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Startup Procedures](#startup-procedures)
3. [Shutdown Procedures](#shutdown-procedures)
4. [Kill Switch Operations](#kill-switch-operations)
5. [Stuck Order Resolution](#stuck-order-resolution)
6. [Database Backup and Recovery](#database-backup-and-recovery)
7. [Monitoring and Alerting](#monitoring-and-alerting)
8. [Feature Flag Management](#feature-flag-management)
9. [Troubleshooting](#troubleshooting)
10. [Disaster Recovery](#disaster-recovery)

---

## Prerequisites

### Required Software
- Python 3.12+
- IBKR TWS or IB Gateway (configured for paper trading or live)
- PostgreSQL 15+ (production) or SQLite (development)
- Docker and Docker Compose (optional, for containerized deployment)

### Environment Variables

**Critical (Required)**:
```bash
# Broker connection
IBKR_HOST=localhost              # IBKR Gateway host
IBKR_PORT=7497                   # 7497=paper, 7496=live
IBKR_CLIENT_ID=1                 # Unique client ID

# Database
DATABASE_URL=sqlite:///data/audit.db  # Or postgresql://...

# Environment mode
ENV=paper                        # dev, paper, or live
```

**Optional (Recommended for Production)**:
```bash
# Logging
LOG_LEVEL=INFO                   # DEBUG, INFO, WARNING, ERROR

# Alerting (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASSWORD=secret_password
SMTP_FROM=ibkr-alerts@example.com
EMAIL_RECIPIENTS=admin@example.com,ops@example.com

# Alerting (Webhook)
WEBHOOK_URL=https://example.com/webhook
WEBHOOK_AUTH_TOKEN=Bearer token123
ALERT_RATE_LIMIT=300             # Seconds between duplicate alerts

# Feature Flags
LIVE_TRADING_MODE=false          # Enable live trading
AUTO_APPROVAL=false              # Auto-approve low-risk orders
AUTO_APPROVAL_MAX_NOTIONAL=1000  # Max notional for auto-approval
STRICT_VALIDATION=true           # Schema validation
ENABLE_DASHBOARD=true            # Dashboard feature
ENABLE_MCP_SERVER=true           # MCP server feature

# Kill Switch
KILL_SWITCH_ENABLED=false        # Emergency trading halt
```

---

## Startup Procedures

### 1. Pre-Flight Checks

**Verify IBKR Gateway is running**:
```bash
# Check connection (Linux/Mac)
nc -zv localhost 7497

# Check connection (Windows)
Test-NetConnection -ComputerName localhost -Port 7497
```

**Verify database accessibility**:
```bash
# SQLite
ls -lh data/audit.db

# PostgreSQL
psql $DATABASE_URL -c "SELECT 1;"
```

**Verify Python environment**:
```bash
python --version  # Should be 3.12+
pip list | grep -E "fastapi|pydantic|structlog"
```

### 2. Start Assistant API

**Development Mode**:
```bash
# With uvicorn auto-reload
uvicorn apps.assistant_api.main:app --reload --port 8000 --log-level info
```

**Production Mode**:
```bash
# With gunicorn + multiple workers
gunicorn apps.assistant_api.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --log-level info \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
```

**Docker Compose**:
```bash
docker-compose up -d assistant_api
```

### 3. Start MCP Server (Optional)

```bash
# Direct execution
python apps/mcp_server/main.py

# With environment
ENV=paper python apps/mcp_server/main.py
```

### 4. Start Dashboard (Optional)

**Streamlit**:
```bash
streamlit run apps/dashboard/main.py --server.port 8080
```

**FastAPI (if implemented)**:
```bash
uvicorn apps.dashboard.main:app --reload --port 8080
```

### 5. Verify Services

**Health Check**:
```bash
curl http://localhost:8000/api/v1/health

# Expected output:
# {
#   "status": "healthy",
#   "timestamp": "2025-12-25T08:30:00.123456Z",
#   "components": {
#     "kill_switch": {"status": "ok", "enabled": false},
#     "audit_store": {"status": "ok"},
#     "broker": {"status": "ok", "connected": true},
#     "approval_service": {"status": "ok"},
#     "risk_engine": {"status": "ok"},
#     "simulator": {"status": "ok"},
#     "order_submitter": {"status": "ok"}
#   }
# }
```

**Kill Switch Status**:
```bash
curl http://localhost:8000/api/v1/kill-switch/status

# Expected (normal operation):
# {
#   "enabled": false,
#   "reason": null,
#   "activated_at": null,
#   "activated_by": null
# }
```

**Feature Flags**:
```bash
curl http://localhost:8000/api/v1/feature-flags

# Expected:
# {
#   "live_trading_mode": false,
#   "auto_approval": false,
#   "auto_approval_max_notional": 1000.0,
#   "new_risk_rules": false,
#   "strict_validation": true,
#   "enable_dashboard": true,
#   "enable_mcp_server": true
# }
```

**Metrics Endpoint**:
```bash
curl http://localhost:8000/api/v1/metrics

# Expected (Prometheus format):
# # HELP ibkr_proposal_total Total number of proposals
# # TYPE ibkr_proposal_total counter
# ibkr_proposal_total{symbol="AAPL",state="PENDING"} 0
# ...
```

---

## Shutdown Procedures

### 1. Graceful Shutdown

**Stop accepting new requests** (activate kill switch):
```bash
curl -X POST http://localhost:8000/api/v1/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Planned maintenance shutdown",
    "activated_by": "admin@example.com"
  }'
```

**Wait for in-flight orders to complete** (check active orders):
```bash
curl http://localhost:8000/api/v1/orders?status=PENDING

# Wait until empty or manually cancel orders
```

**Create backup before shutdown**:
```bash
python -c "
from packages.audit_backup import AuditBackupManager
manager = AuditBackupManager(db_path='data/audit.db')
backup_path = manager.create_backup()
print(f'Backup created: {backup_path}')
"
```

### 2. Stop Services

**Stop Assistant API** (if running with uvicorn):
```bash
# Send SIGTERM
pkill -f "uvicorn apps.assistant_api"

# Or Ctrl+C in terminal
```

**Stop Dashboard** (if running):
```bash
pkill -f "streamlit run apps/dashboard"
```

**Stop MCP Server** (if running):
```bash
pkill -f "python apps/mcp_server"
```

**Docker Compose**:
```bash
docker-compose down
```

### 3. Post-Shutdown Verification

**Verify all processes stopped**:
```bash
ps aux | grep -E "uvicorn|streamlit|mcp_server"
# Should return empty
```

**Verify backup created**:
```bash
ls -lht backups/ | head -5
# Should show recent backup file
```

**Check logs for errors**:
```bash
tail -100 logs/assistant_api.log | grep -i error
```

---

## Kill Switch Operations

### When to Activate Kill Switch

Activate kill switch in these scenarios:

1. **Critical Broker Error**: Broker connection lost or inconsistent state
2. **Risk Policy Violation**: Repeated risk rule failures or suspicious activity
3. **Compliance Issue**: Regulatory requirement or audit finding
4. **System Degradation**: Database corruption, high error rate, latency spike
5. **Planned Maintenance**: Controlled shutdown for upgrades
6. **Manual Override**: Admin decision for any reason

### Activation Methods

**Method 1: API (Recommended)**:
```bash
curl -X POST http://localhost:8000/api/v1/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Broker connection lost - emergency halt",
    "activated_by": "ops@example.com"
  }'

# Response:
# {
#   "status": "activated",
#   "reason": "Broker connection lost - emergency halt",
#   "activated_by": "ops@example.com",
#   "timestamp": "2025-12-25T08:45:00.123456Z"
# }
```

**Method 2: Environment Variable**:
```bash
# Set environment variable and restart
export KILL_SWITCH_ENABLED=true
export KILL_SWITCH_REASON="Emergency halt via env var"

# Restart service
systemctl restart ibkr-assistant
```

**Method 3: Manual State File** (Emergency Fallback):
```bash
# Create or edit state file
cat > packages/kill_switch/state.json <<EOF
{
  "enabled": true,
  "reason": "Manual emergency halt",
  "activated_at": "$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)",
  "activated_by": "admin-manual"
}
EOF
```

### Verification

**Check status after activation**:
```bash
curl http://localhost:8000/api/v1/kill-switch/status

# Expected:
# {
#   "enabled": true,
#   "reason": "Broker connection lost - emergency halt",
#   "activated_at": "2025-12-25T08:45:00.123456Z",
#   "activated_by": "ops@example.com"
# }
```

**Test order submission is blocked**:
```bash
curl -X POST http://localhost:8000/api/v1/orders/submit/test-order-1 \
  -H "Content-Type: application/json"

# Expected:
# {
#   "error": "Kill switch is enabled",
#   "reason": "Broker connection lost - emergency halt",
#   "status": 503
# }
```

### Deactivation

**Only deactivate after**:
1. Root cause identified and resolved
2. System health verified (GET /api/v1/health)
3. Broker connection stable
4. Risk engine operational
5. Post-incident review completed (optional for minor issues)

**Deactivation command**:
```bash
curl -X POST http://localhost:8000/api/v1/kill-switch/deactivate \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Issue resolved - broker connection restored"
  }'

# Response:
# {
#   "status": "deactivated",
#   "reason": "Issue resolved - broker connection restored",
#   "timestamp": "2025-12-25T09:00:00.123456Z"
# }
```

### Post-Activation Checklist

- [ ] Verify health check shows all components healthy
- [ ] Review logs for errors during kill switch period
- [ ] Check for stuck orders (see next section)
- [ ] Test small order submission to verify system operational
- [ ] Document incident in runbook or incident log
- [ ] Send all-clear alert to team

---

## Stuck Order Resolution

### Identify Stuck Orders

**List all pending orders**:
```bash
curl http://localhost:8000/api/v1/orders?status=PENDING

# Returns:
# {
#   "orders": [
#     {
#       "proposal_id": "order-123",
#       "symbol": "AAPL",
#       "state": "PENDING",
#       "created_at": "2025-12-25T08:00:00Z"
#     }
#   ]
# }
```

**Get specific order details**:
```bash
curl http://localhost:8000/api/v1/orders/order-123

# Returns detailed order info including approval token status
```

### Check Broker Status

**Verify broker connection**:
```bash
curl http://localhost:8000/api/v1/health | jq '.components.broker'

# Expected:
# {
#   "status": "ok",
#   "connected": true
# }
```

**Check broker for order status** (if IBKR connection available):
```python
from packages.broker_ibkr import get_ibkr_adapter
adapter = get_ibkr_adapter()
open_orders = adapter.get_open_orders(account_id="DU12345")
# Review orders to find stuck order
```

### Resolution Steps

**Step 1: Attempt normal cancellation**:
```bash
curl -X POST http://localhost:8000/api/v1/orders/order-123/cancel
```

**Step 2: If cancellation fails, check approval token**:
```bash
curl http://localhost:8000/api/v1/approvals/order-123/status

# If token expired or invalid:
curl -X POST http://localhost:8000/api/v1/approvals/order-123/invalidate
```

**Step 3: Manual broker cancellation** (if order reached broker):
```python
from packages.broker_ibkr import get_ibkr_adapter
adapter = get_ibkr_adapter()
# Find order by symbol + timestamp
# Use broker API to cancel order directly
```

**Step 4: Update internal state**:
```python
# Mark order as cancelled in database
from packages.audit_store import append_event, AuditEvent
from datetime import datetime

append_event(AuditEvent(
    type="OrderManualCancellation",
    correlation_id="order-123",
    timestamp=datetime.utcnow(),
    data={
        "reason": "Manual cancellation - order stuck",
        "cancelled_by": "admin@example.com"
    }
))
```

### Verify Resolution

```bash
# Verify order no longer pending
curl http://localhost:8000/api/v1/orders/order-123

# Check audit log for cancellation event
curl http://localhost:8000/api/v1/audit/correlation_id/order-123
```

---

## Database Backup and Recovery

### Automated Backup

**Create backup manually**:
```python
from packages.audit_backup import AuditBackupManager

manager = AuditBackupManager(
    db_path="data/audit.db",
    backup_dir="backups",
    retention_days=30
)

# Create backup
backup_path = manager.create_backup()
print(f"Backup created: {backup_path}")

# Returns:
# Backup created: backups/audit_20251225_083000.db
```

**Schedule automated backups** (cron example):
```bash
# Add to crontab (daily at 2 AM)
0 2 * * * cd /path/to/ibkr-broker && python -c "from packages.audit_backup import AuditBackupManager; AuditBackupManager(db_path='data/audit.db').create_backup()" >> logs/backup.log 2>&1
```

### List and Verify Backups

**List all backups**:
```python
from packages.audit_backup import AuditBackupManager
manager = AuditBackupManager(db_path="data/audit.db")

backups = manager.list_backups()
for backup in backups:
    print(f"Backup: {backup}")

# Output (newest first):
# Backup: backups/audit_20251225_083000.db
# Backup: backups/audit_20251224_083000.db
# Backup: backups/audit_20251223_083000.db
```

**Verify backup integrity**:
```python
from packages.audit_backup import AuditBackupManager
manager = AuditBackupManager(db_path="data/audit.db")

backup_path = "backups/audit_20251225_083000.db"
is_valid = manager.verify_backup(backup_path)

if is_valid:
    print("✅ Backup is valid and intact")
else:
    print("❌ Backup is corrupted or invalid")
```

**Get backup info**:
```python
manager = AuditBackupManager(db_path="data/audit.db")
info = manager.get_backup_info("backups/audit_20251225_083000.db")

# Returns:
# {
#   "path": "backups/audit_20251225_083000.db",
#   "size_bytes": 524288,
#   "timestamp": "2025-12-25T08:30:00",
#   "is_valid": True
# }
```

### Cleanup Old Backups

```python
from packages.audit_backup import AuditBackupManager
manager = AuditBackupManager(
    db_path="data/audit.db",
    retention_days=30  # Keep last 30 days
)

deleted_count = manager.cleanup_old_backups()
print(f"Deleted {deleted_count} old backups")
```

### Database Recovery

**Restore from backup**:

⚠️ **WARNING**: This will replace the current database. A pre-restore backup is automatically created.

```python
from packages.audit_backup import AuditBackupManager
manager = AuditBackupManager(db_path="data/audit.db")

# Step 1: List available backups
backups = manager.list_backups()
print("Available backups:")
for i, backup in enumerate(backups):
    info = manager.get_backup_info(backup)
    print(f"{i}: {backup} ({info['size_bytes']} bytes, {info['timestamp']})")

# Step 2: Verify backup before restore
backup_path = backups[0]  # Use most recent
if not manager.verify_backup(backup_path):
    raise Exception(f"Backup {backup_path} is corrupted!")

# Step 3: Stop services (CRITICAL)
# Ensure no processes are accessing data/audit.db

# Step 4: Restore
manager.restore_backup(
    backup_path=backup_path,
    target_path="data/audit.db"
)
print(f"✅ Restored from {backup_path}")

# Step 5: Verify data
import sqlite3
conn = sqlite3.connect("data/audit.db")
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM events")
count = cursor.fetchone()[0]
print(f"Database contains {count} events")
conn.close()

# Step 6: Restart services
```

**Recovery Checklist**:
- [ ] Services stopped
- [ ] Backup verified as valid
- [ ] Pre-restore backup created (automatic)
- [ ] Restore completed successfully
- [ ] Data verified (event count, recent events)
- [ ] Services restarted
- [ ] Health check passed
- [ ] Test order flow

---

## Monitoring and Alerting

### Metrics Endpoint

**Prometheus scraping**:
```bash
# Add to prometheus.yml
scrape_configs:
  - job_name: 'ibkr-broker'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/v1/metrics'
    scrape_interval: 15s
```

**Manual metrics check**:
```bash
curl http://localhost:8000/api/v1/metrics

# Key metrics to monitor:
# - ibkr_proposal_total{symbol, state} - Proposal count by symbol/state
# - ibkr_risk_rejection_total{rule} - Risk rejections by rule
# - ibkr_broker_error_total - Broker errors
# - ibkr_daily_pnl_usd - Current daily P&L
# - ibkr_submission_latency_seconds - Order submission latency (p50, p95, p99)
# - ibkr_fill_latency_seconds - Order fill latency (p50, p95, p99)
```

### Log Locations

**Structured logs** (JSON format with correlation IDs):
- **Assistant API**: `logs/assistant_api.log`
- **MCP Server**: `logs/mcp_server.log`
- **Dashboard**: `logs/dashboard.log`

**Search logs by correlation ID**:
```bash
# Find all events for a specific order
grep "correlation_id.*order-123" logs/assistant_api.log | jq .

# Find all errors in last hour
grep "level.*error" logs/assistant_api.log | tail -100 | jq .
```

### Alert Configuration

**Email alerts** (SMTP):
```bash
# Set environment variables
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=alerts@example.com
export SMTP_PASSWORD=secret
export SMTP_FROM=ibkr-alerts@example.com
export EMAIL_RECIPIENTS=admin@example.com,ops@example.com
```

**Webhook alerts**:
```bash
export WEBHOOK_URL=https://example.com/webhook
export WEBHOOK_AUTH_TOKEN=Bearer token123
```

**Rate limiting**:
```bash
export ALERT_RATE_LIMIT=300  # 5 minutes between same alert type
```

### Alert Scenarios

**1. Broker Disconnect** (CRITICAL):
- **Trigger**: Broker connection lost
- **Action**: Alert sent immediately
- **Response**: 
  - Check IBKR Gateway status
  - Restart Gateway if needed
  - Verify connection: `curl http://localhost:8000/api/v1/health`
  - If prolonged, activate kill switch

**2. Order Rejection** (WARNING):
- **Trigger**: Risk engine rejects order
- **Action**: Alert with rule details
- **Response**:
  - Review rejected order details
  - Check if rule violation is legitimate
  - Adjust risk rules if needed (via feature flag)
  - Monitor for repeated rejections

**3. Daily Loss Threshold** (ERROR):
- **Trigger**: Daily P&L exceeds loss threshold (default: -$5000)
- **Action**: Alert with current P&L
- **Response**:
  - Review open positions
  - Consider activating kill switch
  - Review trading strategy
  - Adjust threshold if needed: `export DAILY_LOSS_THRESHOLD=10000`

**4. Kill Switch Activated** (CRITICAL):
- **Trigger**: Kill switch enabled (any method)
- **Action**: Alert immediately (bypasses rate limit)
- **Response**:
  - Review reason for activation
  - Resolve underlying issue
  - Follow kill switch deactivation checklist

### Test Alerts

**Send test email**:
```python
from packages.alerting import get_alert_manager

manager = get_alert_manager()
manager.send_alert(
    alert_type="test",
    severity="info",
    message="Test alert from IBKR AI Broker",
    details={"test": True, "timestamp": "2025-12-25T08:00:00Z"}
)
```

**Send test webhook**:
```python
manager = get_alert_manager()
manager.alert_broker_disconnect(error="Test disconnect alert")
```

---

## Feature Flag Management

### List All Flags

```bash
curl http://localhost:8000/api/v1/feature-flags

# Returns:
# {
#   "live_trading_mode": false,
#   "auto_approval": false,
#   "auto_approval_max_notional": 1000.0,
#   "new_risk_rules": false,
#   "strict_validation": true,
#   "enable_dashboard": true,
#   "enable_mcp_server": true
# }
```

### Enable/Disable Flags at Runtime

**Enable flag**:
```bash
curl -X POST http://localhost:8000/api/v1/feature-flags/auto_approval/enable

# Response:
# {
#   "flag": "auto_approval",
#   "enabled": true,
#   "timestamp": "2025-12-25T08:00:00Z"
# }
```

**Disable flag**:
```bash
curl -X POST http://localhost:8000/api/v1/feature-flags/auto_approval/disable

# Response:
# {
#   "flag": "auto_approval",
#   "enabled": false,
#   "timestamp": "2025-12-25T08:00:00Z"
# }
```

### Flag Usage Guide

**1. live_trading_mode** (CRITICAL):
- **Default**: `false` (paper trading)
- **Purpose**: Enable real broker trading
- **⚠️ WARNING**: Only enable in production after thorough testing
- **Enable**: Set env var `LIVE_TRADING_MODE=true`
- **Use case**: Transitioning from paper to live trading

**2. auto_approval** (HIGH RISK):
- **Default**: `false` (manual approval required)
- **Purpose**: Automatically approve low-risk orders
- **Threshold**: `auto_approval_max_notional` (default: $1000)
- **Enable**: Set env var `AUTO_APPROVAL=true`
- **Use case**: Low-value orders, high-frequency trading
- **⚠️ WARNING**: Ensure risk rules are robust before enabling

**3. auto_approval_max_notional**:
- **Default**: `1000.0` (USD)
- **Purpose**: Max notional value for auto-approval
- **Configure**: `AUTO_APPROVAL_MAX_NOTIONAL=5000`
- **Use case**: Adjust based on account size and risk tolerance

**4. new_risk_rules** (EXPERIMENTAL):
- **Default**: `false`
- **Purpose**: Enable experimental risk rules
- **Enable**: Set env var `NEW_RISK_RULES=true`
- **Use case**: A/B testing new risk policies

**5. strict_validation**:
- **Default**: `true`
- **Purpose**: Strict schema validation (reject invalid fields)
- **Disable**: Set env var `STRICT_VALIDATION=false`
- **⚠️ WARNING**: Only disable for debugging

**6. enable_dashboard**:
- **Default**: `true`
- **Purpose**: Enable approval dashboard UI
- **Disable**: `ENABLE_DASHBOARD=false`
- **Use case**: Headless deployment, API-only mode

**7. enable_mcp_server**:
- **Default**: `true`
- **Purpose**: Enable MCP server for LLM integration
- **Disable**: `ENABLE_MCP_SERVER=false`
- **Use case**: Disable LLM interface if not needed

### Configuration Priority

**Priority order** (highest to lowest):
1. **Environment variables** - Runtime overrides (no restart needed)
2. **Config file** (`feature_flags.json`) - Team shared settings
3. **Code defaults** - Fallback values

**Example**:
```bash
# Config file has: {"live_trading_mode": false}
# Env var set: LIVE_TRADING_MODE=true
# Result: live_trading_mode = true (env var wins)
```

---

## Troubleshooting

### Common Issues

#### 1. Broker Connection Failed

**Symptoms**:
- Health check shows `broker.status = "error"`
- Logs show `Connection refused` or `Timeout`

**Diagnosis**:
```bash
# Check IBKR Gateway is running
netstat -an | grep 7497  # Paper trading port
netstat -an | grep 7496  # Live trading port

# Check environment variables
echo $IBKR_HOST
echo $IBKR_PORT
echo $IBKR_CLIENT_ID
```

**Solutions**:
1. Start IBKR TWS or IB Gateway
2. Enable API connections in IBKR Gateway settings
3. Add localhost (127.0.0.1) to trusted IPs in Gateway
4. Verify port matches environment (7497=paper, 7496=live)
5. Ensure client ID is unique (no other apps using same ID)

#### 2. Database Lock Error

**Symptoms**:
- `database is locked` error in logs
- Write operations fail

**Diagnosis**:
```bash
# Check for other processes accessing database
lsof data/audit.db  # Linux/Mac
# Windows: Use Process Explorer

# Check database journal files
ls -la data/audit.db*
```

**Solutions**:
1. Stop all services accessing database
2. Delete journal files if stale: `rm data/audit.db-journal`
3. For production, use PostgreSQL instead of SQLite
4. Ensure proper connection cleanup in code

#### 3. Risk Engine Rejecting All Orders

**Symptoms**:
- All orders rejected with `REJECTED` state
- Logs show `RiskDecision: REJECT`

**Diagnosis**:
```bash
# Check metrics for rejection reasons
curl http://localhost:8000/api/v1/metrics | grep risk_rejection

# Review recent rejections in logs
grep "RiskDecision.*REJECT" logs/assistant_api.log | tail -20 | jq .
```

**Solutions**:
1. Review risk policy file: `cat risk_policy.yml`
2. Check violated rules in rejection logs
3. Adjust risk rules if too strict
4. Verify portfolio data is accurate
5. Test with minimal risk rules (feature flag)

#### 4. High Order Submission Latency

**Symptoms**:
- Order submission takes >5 seconds
- Metrics show `submission_latency_seconds{quantile="0.95"} > 5.0`

**Diagnosis**:
```bash
# Check latency metrics
curl http://localhost:8000/api/v1/metrics | grep submission_latency

# Review slow requests in logs
grep "submission_latency" logs/assistant_api.log | jq 'select(.submission_latency > 5)'
```

**Solutions**:
1. Check broker connection latency: `ping $IBKR_HOST`
2. Verify database performance (query times)
3. Review risk engine evaluation time
4. Check for thread contention (metrics Lock)
5. Scale horizontally (multiple workers)

#### 5. Memory Leak

**Symptoms**:
- Process memory grows unbounded
- System becomes unresponsive over time

**Diagnosis**:
```bash
# Monitor process memory
ps aux | grep uvicorn  # Check RSS column

# Use memory profiler
python -m memory_profiler apps/assistant_api/main.py
```

**Solutions**:
1. Review metrics collection (ensure no unbounded growth)
2. Check for leaked connections (database, broker)
3. Restart service periodically (temporary fix)
4. Profile with `tracemalloc` to find leak source

#### 6. Kill Switch Won't Deactivate

**Symptoms**:
- Deactivate API call succeeds but switch remains enabled
- State file shows `enabled: true`

**Diagnosis**:
```bash
# Check environment variable
echo $KILL_SWITCH_ENABLED

# Check state file
cat packages/kill_switch/state.json

# Check API response
curl -X POST http://localhost:8000/api/v1/kill-switch/deactivate
```

**Solutions**:
1. Environment variable overrides state file - unset: `unset KILL_SWITCH_ENABLED`
2. Manually edit state file: `packages/kill_switch/state.json`
3. Restart service after changing environment
4. Check for file permission issues on state.json

### Log Analysis with Correlation IDs

**Find all events for a proposal**:
```bash
grep "correlation_id.*proposal-123" logs/assistant_api.log | jq .

# Returns chronological sequence:
# 1. ProposalCreated
# 2. RiskEvaluated
# 3. ApprovalRequested
# 4. ApprovalGranted
# 5. OrderSubmitted
# 6. OrderFilled
```

**Find all errors in last hour**:
```bash
grep "level.*error" logs/assistant_api.log | tail -100 | jq .
```

**Find slowest requests**:
```bash
grep "submission_latency" logs/assistant_api.log | \
  jq -r '[.correlation_id, .submission_latency] | @tsv' | \
  sort -k2 -rn | head -10
```

---

## Disaster Recovery

### Complete System Restore

**Scenario**: Database corrupted, service unrecoverable, need full restore.

**Recovery Steps**:

**1. Stop all services**:
```bash
docker-compose down
# Or manually stop all processes
pkill -f "uvicorn|streamlit|mcp_server"
```

**2. Identify most recent valid backup**:
```python
from packages.audit_backup import AuditBackupManager
manager = AuditBackupManager(db_path="data/audit.db")

# List backups (newest first)
backups = manager.list_backups()
for backup in backups[:5]:
    info = manager.get_backup_info(backup)
    is_valid = manager.verify_backup(backup)
    print(f"{backup}: {info['timestamp']}, Valid: {is_valid}")

# Select most recent valid backup
backup_to_restore = backups[0]  # Adjust index if needed
```

**3. Backup current state** (even if corrupted):
```bash
mv data/audit.db data/audit.db.corrupted-$(date +%Y%m%d_%H%M%S)
mv data/audit.db-journal data/audit.db-journal.corrupted-$(date +%Y%m%d_%H%M%S) 2>/dev/null
```

**4. Restore from backup**:
```python
manager.restore_backup(
    backup_path=backup_to_restore,
    target_path="data/audit.db"
)
print(f"✅ Restored from {backup_to_restore}")
```

**5. Verify restored database**:
```python
import sqlite3
conn = sqlite3.connect("data/audit.db")
cursor = conn.cursor()

# Check event count
cursor.execute("SELECT COUNT(*) FROM events")
total_events = cursor.fetchone()[0]
print(f"Total events: {total_events}")

# Check most recent event
cursor.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT 1")
recent = cursor.fetchone()
print(f"Most recent event: {recent}")

conn.close()
```

**6. Restart services**:
```bash
docker-compose up -d
# Or manually start services
```

**7. Verify system health**:
```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/kill-switch/status
curl http://localhost:8000/api/v1/feature-flags
```

**8. Test order flow**:
```bash
# Submit test order (will be rejected by risk engine in paper mode)
curl -X POST http://localhost:8000/api/v1/proposals \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "quantity": 1,
    "side": "BUY",
    "reason": "Disaster recovery test"
  }'

# Verify proposal appears in logs
tail -20 logs/assistant_api.log | jq .
```

### Data Loss Scenarios

**Scenario 1: Last backup is 24 hours old**
- **Data Loss**: All events in last 24 hours
- **Impact**: Recent orders, approvals, audit trail lost
- **Mitigation**: More frequent backups (every 6 hours)
- **Recovery**: Manual reconstruction from broker records if critical

**Scenario 2: All backups corrupted**
- **Data Loss**: Complete audit history
- **Impact**: Compliance issues, no audit trail
- **Mitigation**: 
  - Offsite backup replication
  - Multiple backup locations (S3, NAS, etc.)
- **Recovery**: Reconstruct from broker trade history (incomplete)

**Scenario 3: Broker and database out of sync**
- **Data Loss**: Order state inconsistency
- **Impact**: System believes order is filled but broker shows pending
- **Mitigation**: Regular reconciliation (future feature)
- **Recovery**:
  1. Export broker order history
  2. Compare with audit log
  3. Manually create reconciliation events

### Rollback Procedures

**Rollback to previous code version**:
```bash
# View recent commits
git log --oneline -10

# Rollback to specific commit
git checkout <commit-hash>

# Or revert specific commit
git revert <commit-hash>

# Rebuild and restart
pip install -e .
docker-compose up -d --build
```

**Rollback risk policy changes**:
```bash
# View previous version
git show HEAD~1:risk_policy.yml > risk_policy.yml.previous

# Restore previous version
mv risk_policy.yml risk_policy.yml.new
mv risk_policy.yml.previous risk_policy.yml

# Restart service to reload policy
systemctl restart ibkr-assistant
```

---

## Emergency Contacts

**Primary On-Call**: [Your Name] - [email] - [phone]  
**Secondary On-Call**: [Backup Name] - [email] - [phone]  
**IBKR Support**: 1-877-442-2757 (US), +41 41 726 9686 (International)  
**Infrastructure Team**: [email/slack channel]  

---

## Appendix

### Useful Scripts

**Quick health check**:
```bash
#!/bin/bash
# health_check.sh
curl -s http://localhost:8000/api/v1/health | jq '.status'
if [ $? -eq 0 ]; then
  echo "✅ Service is healthy"
else
  echo "❌ Service is unhealthy"
  exit 1
fi
```

**Automated backup**:
```python
#!/usr/bin/env python
# scripts/backup_audit_db.py
from packages.audit_backup import AuditBackupManager
from datetime import datetime

manager = AuditBackupManager(db_path="data/audit.db")
backup_path = manager.create_backup()
print(f"{datetime.now()}: Backup created at {backup_path}")

# Cleanup old backups
deleted = manager.cleanup_old_backups()
print(f"Cleaned up {deleted} old backups")
```

**Activate kill switch** (emergency script):
```python
#!/usr/bin/env python
# scripts/activate_kill_switch.py
import requests
import sys

reason = sys.argv[1] if len(sys.argv) > 1 else "Emergency manual activation"
response = requests.post(
    "http://localhost:8000/api/v1/kill-switch/activate",
    json={"reason": reason, "activated_by": "admin-script"}
)
print(response.json())
```

### Monitoring Dashboard

**Example Grafana queries**:

```promql
# Proposal rate by symbol
rate(ibkr_proposal_total[5m])

# Risk rejection rate by rule
rate(ibkr_risk_rejection_total[5m])

# Submission latency p95
ibkr_submission_latency_seconds{quantile="0.95"}

# Daily P&L
ibkr_daily_pnl_usd
```

---

**Last Updated**: 2025-12-25  
**Version**: 1.0.0  
**Sprint**: 10 (Hardening Phase)
