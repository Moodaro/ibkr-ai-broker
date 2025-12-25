"""
IBKR AI Broker - Approval Dashboard

Streamlit dashboard for managing order proposals and approvals.
Provides visual interface for:
- Viewing pending proposals
- Approving/denying proposals
- Kill switch control
- Audit trail viewing
"""

import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import requests
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

# Configuration
API_BASE_URL = "http://localhost:8000"
AUTO_REFRESH_SECONDS = 5

# Page config
st.set_page_config(
    page_title="IBKR AI Broker - Approval Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
    <style>
    .stButton button {
        width: 100%;
    }
    .proposal-card {
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #ddd;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 0.5rem;
        border-radius: 0.25rem;
        margin: 0.25rem 0;
    }
    .risk-approve {
        color: #0f9d58;
        font-weight: bold;
    }
    .risk-reject {
        color: #db4437;
        font-weight: bold;
    }
    .risk-review {
        color: #f4b400;
        font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# API Client
class DashboardAPI:
    """Simple API client for dashboard."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def get_pending_proposals(self, limit: int = 100) -> dict:
        """Get pending proposals from API."""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/approval/pending",
                params={"limit": limit},
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Failed to fetch proposals: {e}")
            return {"proposals": [], "count": 0}

    def request_approval(self, proposal_id: str) -> dict:
        """Request approval for a proposal."""
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/approval/request",
                json={"proposal_id": proposal_id},
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Failed to request approval: {e}")
            return {}

    def grant_approval(self, proposal_id: str, reason: Optional[str] = None) -> dict:
        """Grant approval for a proposal."""
        try:
            payload = {"proposal_id": proposal_id}
            if reason:
                payload["reason"] = reason
            response = requests.post(
                f"{self.base_url}/api/v1/approval/grant",
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Failed to grant approval: {e}")
            return {}

    def deny_approval(self, proposal_id: str, reason: str) -> dict:
        """Deny approval for a proposal."""
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/approval/deny",
                json={"proposal_id": proposal_id, "reason": reason},
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Failed to deny approval: {e}")
            return {}

    def health_check(self) -> bool:
        """Check if API is healthy."""
        try:
            response = requests.get(f"{self.base_url}/api/v1/health", timeout=2)
            return response.status_code == 200
        except:
            return False


# Initialize API client
@st.cache_resource
def get_api_client() -> DashboardAPI:
    """Get cached API client."""
    return DashboardAPI(API_BASE_URL)


# Helper functions
def format_timestamp(ts_str: str) -> str:
    """Format ISO timestamp to readable string."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except:
        return ts_str


def format_decimal(value: Any) -> str:
    """Format decimal value for display."""
    if value is None:
        return "N/A"
    try:
        d = Decimal(str(value))
        return f"${d:,.2f}"
    except:
        return str(value)


def get_state_color(state: str) -> str:
    """Get color for proposal state."""
    colors = {
        "PROPOSED": "🔵",
        "SIMULATED": "🔵",
        "RISK_APPROVED": "🟢",
        "RISK_REJECTED": "🔴",
        "APPROVAL_REQUESTED": "🟡",
        "APPROVAL_GRANTED": "✅",
        "APPROVAL_DENIED": "❌",
        "SUBMITTED": "🚀",
        "FILLED": "✅",
        "CANCELLED": "⚫",
        "REJECTED": "🔴",
    }
    return colors.get(state, "⚪")


def get_risk_decision_html(decision: Optional[str]) -> str:
    """Get HTML for risk decision display."""
    if not decision:
        return "N/A"
    
    css_class = {
        "APPROVE": "risk-approve",
        "REJECT": "risk-reject",
        "MANUAL_REVIEW": "risk-review",
    }.get(decision, "")
    
    return f'<span class="{css_class}">{decision}</span>'


# Main UI Components

def render_header():
    """Render dashboard header."""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.title("🤖 IBKR AI Broker - Approval Dashboard")
        st.caption("Manage order proposals and approvals")
    
    with col2:
        api = get_api_client()
        if api.health_check():
            st.success("API Connected ✅")
        else:
            st.error("API Disconnected ❌")


def render_kill_switch_sidebar():
    """Render kill switch in sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.header("🚨 Kill Switch")
    
    # TODO: Implement actual kill switch state from API
    kill_switch_active = st.sidebar.checkbox(
        "Kill Switch Active",
        value=False,
        help="When active, all trading operations are blocked",
    )
    
    if kill_switch_active:
        st.sidebar.error("⚠️ ALL TRADING BLOCKED")
        st.sidebar.warning("Deactivate kill switch to resume trading")
    else:
        st.sidebar.info("✓ Trading operations enabled")
    
    if st.sidebar.button("🛑 Emergency Stop", type="primary", use_container_width=True):
        st.sidebar.warning("Kill switch activation not yet implemented")
    
    return kill_switch_active


def render_proposal_card(proposal: dict):
    """Render a proposal card with details and actions."""
    with st.container():
        # Header
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            st.markdown(f"### {get_state_color(proposal['state'])} {proposal.get('symbol', 'N/A')}")
            st.caption(f"Proposal ID: {proposal['proposal_id'][:12]}...")
        
        with col2:
            st.metric("Side", proposal.get("side", "N/A"))
        
        with col3:
            st.metric("Quantity", proposal.get("quantity", "N/A"))
        
        # Details
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Notional", format_decimal(proposal.get("gross_notional")))
        
        with col2:
            st.metric("State", proposal["state"])
        
        with col3:
            risk_html = get_risk_decision_html(proposal.get("risk_decision"))
            st.markdown(f"**Risk Decision**<br>{risk_html}", unsafe_allow_html=True)
        
        with col4:
            created = format_timestamp(proposal["created_at"])
            st.caption(f"**Created**<br>{created}")
        
        # Risk reason
        if proposal.get("risk_reason"):
            st.info(f"**Risk Engine**: {proposal['risk_reason']}")
        
        # Actions
        state = proposal["state"]
        proposal_id = proposal["proposal_id"]
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            # Request Approval button (only for RISK_APPROVED)
            if state == "RISK_APPROVED":
                if st.button("📋 Request Approval", key=f"request_{proposal_id}", use_container_width=True):
                    api = get_api_client()
                    result = api.request_approval(proposal_id)
                    if result:
                        st.success("✅ Approval requested!")
                        st.rerun()
        
        with col2:
            # Approve button (only for APPROVAL_REQUESTED)
            if state == "APPROVAL_REQUESTED":
                if st.button("✅ Approve", key=f"approve_{proposal_id}", type="primary", use_container_width=True):
                    st.session_state[f"approving_{proposal_id}"] = True
                    st.rerun()
        
        with col3:
            # Deny button (only for APPROVAL_REQUESTED)
            if state == "APPROVAL_REQUESTED":
                if st.button("❌ Deny", key=f"deny_{proposal_id}", use_container_width=True):
                    st.session_state[f"denying_{proposal_id}"] = True
                    st.rerun()
        
        # Approval dialog
        if st.session_state.get(f"approving_{proposal_id}"):
            with st.form(key=f"approve_form_{proposal_id}"):
                reason = st.text_input("Approval reason (optional)", key=f"approve_reason_{proposal_id}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("Confirm Approval", type="primary", use_container_width=True):
                        api = get_api_client()
                        result = api.grant_approval(proposal_id, reason or None)
                        if result and "token" in result:
                            st.success(f"✅ Approved! Token: {result['token'][:16]}...")
                            st.caption(f"Expires: {format_timestamp(result['expires_at'])}")
                            del st.session_state[f"approving_{proposal_id}"]
                            time.sleep(1)
                            st.rerun()
                with col2:
                    if st.form_submit_button("Cancel", use_container_width=True):
                        del st.session_state[f"approving_{proposal_id}"]
                        st.rerun()
        
        # Deny dialog
        if st.session_state.get(f"denying_{proposal_id}"):
            with st.form(key=f"deny_form_{proposal_id}"):
                reason = st.text_area("Denial reason (required)", key=f"deny_reason_{proposal_id}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("Confirm Denial", type="primary", use_container_width=True):
                        if not reason:
                            st.error("Denial reason is required")
                        else:
                            api = get_api_client()
                            result = api.deny_approval(proposal_id, reason)
                            if result:
                                st.success("✅ Proposal denied")
                                del st.session_state[f"denying_{proposal_id}"]
                                time.sleep(1)
                                st.rerun()
                with col2:
                    if st.form_submit_button("Cancel", use_container_width=True):
                        del st.session_state[f"denying_{proposal_id}"]
                        st.rerun()
        
        st.markdown("---")


def render_proposals_list():
    """Render list of pending proposals."""
    api = get_api_client()
    
    # Fetch proposals
    data = api.get_pending_proposals(limit=50)
    proposals = data.get("proposals", [])
    count = data.get("count", 0)
    
    if count == 0:
        st.info("No pending proposals")
        return
    
    st.subheader(f"📋 Pending Proposals ({count})")
    
    # Filters
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        state_filter = st.selectbox(
            "Filter by state",
            ["All", "RISK_APPROVED", "APPROVAL_REQUESTED", "APPROVAL_GRANTED"],
            key="state_filter",
        )
    
    with col2:
        sort_order = st.selectbox(
            "Sort by",
            ["Newest first", "Oldest first"],
            key="sort_order",
        )
    
    # Apply filters
    filtered_proposals = proposals
    if state_filter != "All":
        filtered_proposals = [p for p in proposals if p["state"] == state_filter]
    
    if sort_order == "Oldest first":
        filtered_proposals = list(reversed(filtered_proposals))
    
    # Render proposals
    if not filtered_proposals:
        st.warning(f"No proposals matching filter: {state_filter}")
    else:
        for proposal in filtered_proposals:
            render_proposal_card(proposal)


def render_statistics():
    """Render statistics sidebar."""
    st.sidebar.header("📊 Statistics")
    
    api = get_api_client()
    data = api.get_pending_proposals(limit=1000)
    proposals = data.get("proposals", [])
    
    if not proposals:
        st.sidebar.info("No data")
        return
    
    # Count by state
    state_counts = {}
    for p in proposals:
        state = p["state"]
        state_counts[state] = state_counts.get(state, 0) + 1
    
    st.sidebar.metric("Total Pending", len(proposals))
    
    for state, count in sorted(state_counts.items()):
        st.sidebar.metric(f"{get_state_color(state)} {state}", count)


# Main app
def main():
    """Main dashboard application."""
    render_header()
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        auto_refresh = st.checkbox("Auto-refresh", value=True)
        if auto_refresh:
            refresh_interval = st.slider(
                "Refresh interval (seconds)",
                min_value=2,
                max_value=30,
                value=AUTO_REFRESH_SECONDS,
            )
            st.caption(f"Next refresh in {refresh_interval}s")
        
        render_statistics()
        
        kill_switch = render_kill_switch_sidebar()
    
    # Main content
    if kill_switch:
        st.error("🚨 KILL SWITCH ACTIVE - ALL TRADING BLOCKED")
    
    render_proposals_list()
    
    # Auto-refresh
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()
