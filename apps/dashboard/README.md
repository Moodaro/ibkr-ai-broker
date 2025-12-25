# IBKR AI Broker - Approval Dashboard

Visual dashboard for managing order proposals and approvals.

## Features

- **Pending Proposals View**: Real-time list of proposals awaiting approval
- **Proposal Details**: Full view of intent, simulation results, and risk decisions
- **One-Click Actions**: Approve or deny proposals with optional reasons
- **Kill Switch**: Emergency stop for all trading operations
- **Statistics**: Real-time counts by state
- **Auto-Refresh**: Configurable refresh interval (2-30 seconds)

## Installation

The dashboard is already included in the project. Ensure dependencies are installed:

```bash
pip install streamlit requests
# or with uv:
uv pip install streamlit requests
```

## Running the Dashboard

### 1. Start the API Server

```bash
# In one terminal
uvicorn apps.assistant_api.main:app --reload --port 8000
```

### 2. Start the Dashboard

```bash
# In another terminal
streamlit run apps/dashboard/main.py
```

The dashboard will open in your browser at `http://localhost:8501`.

## Usage

### Viewing Proposals

The main view shows all pending proposals with:
- **Symbol** and **Side** (BUY/SELL)
- **Quantity** and **Notional Value**
- **Current State** (with emoji indicator)
- **Risk Decision** (APPROVE/REJECT/MANUAL_REVIEW)
- **Created Timestamp**

### State Indicators

- 🔵 PROPOSED / SIMULATED
- 🟢 RISK_APPROVED
- 🔴 RISK_REJECTED
- 🟡 APPROVAL_REQUESTED
- ✅ APPROVAL_GRANTED / FILLED
- ❌ APPROVAL_DENIED
- 🚀 SUBMITTED
- ⚫ CANCELLED

### Approving a Proposal

1. Proposal must be in **RISK_APPROVED** state first
2. Click **"📋 Request Approval"** button
3. State changes to **APPROVAL_REQUESTED**
4. Click **"✅ Approve"** button
5. (Optional) Enter approval reason
6. Click **"Confirm Approval"**
7. Token generated and displayed (copy before it expires!)

### Denying a Proposal

1. Proposal must be in **APPROVAL_REQUESTED** state
2. Click **"❌ Deny"** button
3. Enter denial reason (required)
4. Click **"Confirm Denial"**

### Kill Switch

Located in the sidebar:
- **Checkbox**: Activate/deactivate kill switch
- **Emergency Stop Button**: Quick activation
- **Status Indicator**: Shows current state

When active:
- ⚠️ ALL TRADING BLOCKED message displayed
- No approvals can be granted
- All trading operations halted

### Statistics

Sidebar shows:
- **Total Pending**: Count of all pending proposals
- **By State**: Breakdown by each state

### Filters and Sorting

- **Filter by State**: Show only specific states
- **Sort Order**: Newest first / Oldest first

### Auto-Refresh

- **Enable/Disable**: Checkbox in sidebar
- **Refresh Interval**: Slider (2-30 seconds)
- Dashboard automatically reloads to show latest data

## API Connectivity

Dashboard connects to API at `http://localhost:8000`.

**Connection Status**: Shown in top-right corner
- ✅ Green = Connected
- ❌ Red = Disconnected

If disconnected:
1. Check API server is running
2. Check port 8000 is not blocked
3. Check no firewall issues

## Keyboard Shortcuts

Streamlit provides these shortcuts:
- **R**: Rerun/refresh
- **C**: Clear cache
- **Ctrl+K**: Open command palette

## Configuration

Edit `apps/dashboard/main.py` to change:

```python
API_BASE_URL = "http://localhost:8000"  # API endpoint
AUTO_REFRESH_SECONDS = 5                 # Default refresh interval
```

## Troubleshooting

### Dashboard won't start
- Ensure Streamlit is installed: `pip list | grep streamlit`
- Check Python version: Python 3.10+ required

### API connection errors
- Verify API is running: `curl http://localhost:8000/api/v1/health`
- Check correct port in API_BASE_URL

### Proposals not showing
- Click refresh or wait for auto-refresh
- Check API has proposals: `curl http://localhost:8000/api/v1/approval/pending`

### Actions not working
- Check browser console for errors
- Verify API endpoints return 200 status
- Check correlation_id in API logs

## Development

### Adding New Features

1. Add API method to `DashboardAPI` class
2. Create UI component function (e.g., `render_xyz()`)
3. Call from `main()` function
4. Test with live API

### Styling

Custom CSS in `st.markdown()` at top of file:
- Modify colors, fonts, spacing
- Add new CSS classes as needed

### State Management

Streamlit session state used for:
- Dialog visibility (`approving_{proposal_id}`)
- Kill switch state
- Filter selections

## Security Notes

- Dashboard is for **local use only** (no authentication)
- Do not expose to internet without adding auth
- Token displayed briefly - copy immediately
- Denial reasons are required for audit trail

## Next Steps

Future enhancements:
- [ ] Historical proposals view
- [ ] Audit trail browser
- [ ] Risk rule configuration UI
- [ ] Batch approval/denial
- [ ] WebSocket live updates
- [ ] Multi-user authentication
- [ ] Mobile-responsive layout

## Support

For issues or questions:
1. Check API logs in terminal
2. Check browser console for errors
3. Review ROADMAP.md for known limitations
4. See AGENTS.md for development guidance
