"""
Approval service for two-step commit.

Manages approval requests, tokens, and proposal lifecycle.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
import json
import uuid

from packages.schemas.approval import (
    ApprovalToken,
    OrderProposal,
    OrderState,
    PendingProposal,
)


class ApprovalService:
    """
    Manages approval requests and tokens for two-step commit.
    
    Provides:
    - In-memory storage of proposals (FIFO with max size)
    - ApprovalToken generation with expiration
    - Token validation and consumption
    - Anti-tamper hash verification
    """
    
    def __init__(self, max_proposals: int = 1000, token_ttl_minutes: int = 5):
        """
        Initialize approval service.
        
        Args:
            max_proposals: Maximum number of proposals to keep in memory
            token_ttl_minutes: Token time-to-live in minutes
        """
        self._proposals: dict[str, OrderProposal] = {}
        self._tokens: dict[str, ApprovalToken] = {}
        self._max_proposals = max_proposals
        self._token_ttl = timedelta(minutes=token_ttl_minutes)
    
    def store_proposal(self, proposal: OrderProposal) -> None:
        """
        Store a proposal for approval.
        
        If max_proposals is reached, removes oldest APPROVAL_DENIED/RISK_REJECTED proposals.
        
        Args:
            proposal: OrderProposal to store
        """
        # Check if we need to evict old proposals
        if len(self._proposals) >= self._max_proposals:
            self._evict_old_proposals()
        
        self._proposals[proposal.proposal_id] = proposal
    
    def create_and_store_proposal(
        self,
        intent,
        sim_result,
        risk_decision,
        correlation_id: Optional[str] = None
    ) -> OrderProposal:
        """
        Create OrderProposal from objects and store it.
        
        Helper method for tests and backwards compatibility.
        
        Args:
            intent: OrderIntent object
            sim_result: SimulationResult object
            risk_decision: RiskDecision object
            correlation_id: Optional correlation ID (generated if not provided)
            
        Returns:
            Created OrderProposal
        """
        proposal_id = str(uuid.uuid4())
        if correlation_id is None:
            correlation_id = f"test-{proposal_id[:8]}"
        
        # Determine state based on risk decision
        from packages.risk_engine.models import Decision
        if risk_decision.decision == Decision.APPROVE:
            state = OrderState.RISK_APPROVED
        else:
            state = OrderState.RISK_REJECTED
        
        proposal = OrderProposal(
            proposal_id=proposal_id,
            correlation_id=correlation_id,
            intent_json=intent.model_dump_json(exclude_none=True),
            simulation_json=sim_result.model_dump_json(exclude_none=True),
            risk_decision_json=risk_decision.model_dump_json(exclude_none=True),
            state=state,
        )
        
        self.store_proposal(proposal)
        return proposal
    
    def get_proposal(self, proposal_id: str) -> Optional[OrderProposal]:
        """Get proposal by ID."""
        return self._proposals.get(proposal_id)
    
    def get_token(self, token_id: str) -> Optional[ApprovalToken]:
        """Get token by ID.
        
        Args:
            token_id: Token ID to retrieve.
            
        Returns:
            ApprovalToken if found, None otherwise.
        """
        return self._tokens.get(token_id)
    
    def update_proposal(self, proposal: OrderProposal) -> None:
        """Update existing proposal."""
        if proposal.proposal_id not in self._proposals:
            raise ValueError(f"Proposal {proposal.proposal_id} not found")
        self._proposals[proposal.proposal_id] = proposal
    
    def request_approval(
        self,
        proposal_id: str,
        feature_flags=None,
        kill_switch=None,
        policy_checker=None,
        current_time: Optional[datetime] = None
    ) -> tuple[OrderProposal, Optional[ApprovalToken]]:
        """
        Mark proposal as APPROVAL_REQUESTED, or auto-approve if eligible.
        
        Auto-approval conditions (all must be true):
        1. feature_flags.auto_approval == True
        2. notional <= feature_flags.auto_approval_max_notional
        3. kill_switch.is_enabled() == False
        4. proposal.state == RISK_APPROVED
        5. policy_checker.check_all() passes (if provided)
        
        If auto-approval eligible:
            - Transitions directly to APPROVAL_GRANTED
            - Generates ApprovalToken automatically
            - Returns (updated_proposal, token)
        
        Otherwise:
            - Transitions to APPROVAL_REQUESTED (manual approval required)
            - Returns (updated_proposal, None)
        
        Args:
            proposal_id: ID of proposal to request approval for
            feature_flags: FeatureFlags instance (optional, for auto-approval check)
            kill_switch: KillSwitch instance (optional, for auto-approval check)
            policy_checker: PolicyChecker instance (optional, for advanced policy checks)
            current_time: Current time (defaults to now UTC)
            
        Returns:
            Tuple of (updated OrderProposal, optional ApprovalToken)
            Token is None if manual approval required, or ApprovalToken if auto-approved.
            
        Raises:
            ValueError: If proposal not found or not in RISK_APPROVED state
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        if proposal.state != OrderState.RISK_APPROVED:
            raise ValueError(
                f"Cannot request approval for proposal in state {proposal.state}. "
                "Must be RISK_APPROVED."
            )
        
        # Check auto-approval eligibility
        auto_approved = False
        approval_reason = "Manual approval required"
        
        if feature_flags is not None and kill_switch is not None:
            if (
                feature_flags.auto_approval
                and not kill_switch.is_enabled()
            ):
                # Parse intent and simulation JSON
                try:
                    intent_data = json.loads(proposal.intent_json)
                    simulation_data = json.loads(proposal.simulation_json)
                    notional = Decimal(str(simulation_data.get("gross_notional", "0")))
                    
                    # Notional threshold check
                    if notional <= Decimal(str(feature_flags.auto_approval_max_notional)):
                        # Check policy (if provided)
                        if policy_checker is not None:
                            from packages.approval_service.policy import DayOfWeek
                            
                            # Extract intent fields for policy check
                            symbol = intent_data.get("symbol", "")
                            sec_type = intent_data.get("sec_type", "STK")
                            side = intent_data.get("side", "")
                            order_type = intent_data.get("order_type", "")
                            
                            # Get current time and day for time window check
                            current_day = DayOfWeek[current_time.strftime("%A").upper()]
                            current_time_of_day = current_time.time()
                            
                            # Run all policy checks
                            policy_ok, policy_reasons = policy_checker.check_all(
                                symbol=symbol,
                                sec_type=sec_type,
                                side=side,
                                order_type=order_type,
                                notional=float(notional),
                                current_time=current_time_of_day,
                                current_day=current_day,
                                portfolio_nav=None,  # TODO: pass portfolio NAV if available
                            )
                            
                            if policy_ok:
                                auto_approved = True
                                approval_reason = "Auto-approved (below threshold, policy passed)"
                            else:
                                approval_reason = f"Policy check failed: {', '.join(policy_reasons)}"
                        else:
                            # No policy checker = only notional check
                            auto_approved = True
                            approval_reason = "Auto-approved (below threshold)"
                    else:
                        approval_reason = f"Notional ${notional} exceeds threshold ${feature_flags.auto_approval_max_notional}"
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    # If we can't parse, fall back to manual approval
                    auto_approved = False
                    approval_reason = f"Parse error: {str(e)}"
        
        if auto_approved:
            # Auto-approve: generate token and transition to APPROVAL_GRANTED
            token = self._generate_token(proposal, current_time)
            self._tokens[token.token_id] = token
            
            updated = proposal.with_state(
                OrderState.APPROVAL_GRANTED,
                approval_token=token.token_id,
                approval_reason=approval_reason
            )
            self.update_proposal(updated)
            return updated, token
        else:
            # Manual approval required
            updated = proposal.with_state(
                OrderState.APPROVAL_REQUESTED,
                approval_reason=approval_reason
            )
            self.update_proposal(updated)
            return updated, None
    
    def grant_approval(
        self,
        proposal_id: str,
        reason: Optional[str] = None,
        current_time: Optional[datetime] = None
    ) -> tuple[OrderProposal, ApprovalToken]:
        """
        Grant approval and generate token.
        
        Args:
            proposal_id: ID of proposal to approve
            reason: Optional approval reason
            current_time: Current time (defaults to now UTC)
            
        Returns:
            Tuple of (updated OrderProposal, ApprovalToken)
            
        Raises:
            ValueError: If proposal not found or not in APPROVAL_REQUESTED state
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        if proposal.state != OrderState.APPROVAL_REQUESTED:
            raise ValueError(
                f"Cannot grant approval for proposal in state {proposal.state}. "
                "Must be APPROVAL_REQUESTED."
            )
        
        # Generate token
        token = self._generate_token(proposal, current_time)
        self._tokens[token.token_id] = token
        
        # Update proposal
        updated = proposal.with_state(
            OrderState.APPROVAL_GRANTED,
            approval_token=token.token_id,
            approval_reason=reason
        )
        self.update_proposal(updated)
        
        return updated, token
    
    def deny_approval(
        self,
        proposal_id: str,
        reason: str
    ) -> OrderProposal:
        """
        Deny approval.
        
        Args:
            proposal_id: ID of proposal to deny
            reason: Required denial reason
            
        Returns:
            Updated OrderProposal
            
        Raises:
            ValueError: If proposal not found or not in APPROVAL_REQUESTED state
        """
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        if proposal.state != OrderState.APPROVAL_REQUESTED:
            raise ValueError(
                f"Cannot deny approval for proposal in state {proposal.state}. "
                "Must be APPROVAL_REQUESTED."
            )
        
        updated = proposal.with_state(
            OrderState.APPROVAL_DENIED,
            approval_reason=reason
        )
        self.update_proposal(updated)
        return updated
    
    def validate_token(
        self,
        token_id: str,
        intent_hash: str,
        current_time: Optional[datetime] = None
    ) -> bool:
        """
        Validate token: exists, not expired, not used, hash matches.
        
        Args:
            token_id: Token ID to validate
            intent_hash: Expected intent hash
            current_time: Current time (defaults to now UTC)
            
        Returns:
            True if valid, False otherwise
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        token = self._tokens.get(token_id)
        if token is None:
            return False
        
        if not token.is_valid(current_time):
            return False
        
        if token.intent_hash != intent_hash:
            return False
        
        return True
    
    def consume_token(
        self,
        token_id: str,
        current_time: Optional[datetime] = None
    ) -> ApprovalToken:
        """
        Consume (mark as used) a token.
        
        Args:
            token_id: Token ID to consume
            current_time: Current time (defaults to now UTC)
            
        Returns:
            Consumed ApprovalToken
            
        Raises:
            ValueError: If token not found or invalid
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        token = self._tokens.get(token_id)
        if token is None:
            raise ValueError(f"Token {token_id} not found")
        
        consumed = token.consume(current_time)
        self._tokens[token_id] = consumed
        return consumed
    
    def get_pending_proposals(self, limit: int = 100) -> list[PendingProposal]:
        """
        Get list of proposals awaiting approval.
        
        Args:
            limit: Maximum number of proposals to return
            
        Returns:
            List of PendingProposal (most recent first)
        """
        pending = [
            p for p in self._proposals.values()
            if p.state in {OrderState.APPROVAL_REQUESTED, OrderState.RISK_APPROVED}
        ]
        
        # Sort by creation time (most recent first)
        pending.sort(key=lambda p: p.created_at, reverse=True)
        
        # Convert to PendingProposal
        result = []
        for proposal in pending[:limit]:
            result.append(self._proposal_to_pending(proposal))
        
        return result
    
    def _generate_token(
        self,
        proposal: OrderProposal,
        current_time: datetime
    ) -> ApprovalToken:
        """Generate approval token for proposal."""
        token_id = str(uuid.uuid4())
        expires_at = current_time + self._token_ttl
        
        return ApprovalToken(
            token_id=token_id,
            proposal_id=proposal.proposal_id,
            intent_hash=proposal.intent_hash,
            issued_at=current_time,
            expires_at=expires_at,
        )
    
    def _evict_old_proposals(self) -> None:
        """Evict oldest terminal state proposals to make room."""
        terminal_states = {
            OrderState.APPROVAL_DENIED,
            OrderState.RISK_REJECTED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
        }
        
        terminal = [
            p for p in self._proposals.values()
            if p.state in terminal_states
        ]
        
        if not terminal:
            # No terminal proposals to evict, remove oldest overall
            oldest = min(self._proposals.values(), key=lambda p: p.created_at)
            del self._proposals[oldest.proposal_id]
            return
        
        # Remove oldest terminal proposal
        oldest_terminal = min(terminal, key=lambda p: p.updated_at)
        del self._proposals[oldest_terminal.proposal_id]
    
    def _proposal_to_pending(self, proposal: OrderProposal) -> PendingProposal:
        """Convert OrderProposal to PendingProposal for UI."""
        # Parse intent to extract key fields
        intent = json.loads(proposal.intent_json)
        
        # Parse risk decision if available
        risk_decision = None
        risk_reason = None
        if proposal.risk_decision_json:
            risk = json.loads(proposal.risk_decision_json)
            risk_decision = risk.get("decision")
            risk_reason = risk.get("reason")
        
        # Parse simulation to get notional
        gross_notional = None
        if proposal.simulation_json:
            sim = json.loads(proposal.simulation_json)
            gross_notional_str = sim.get("gross_notional")
            if gross_notional_str:
                gross_notional = Decimal(gross_notional_str)
        
        return PendingProposal(
            proposal_id=proposal.proposal_id,
            correlation_id=proposal.correlation_id,
            state=proposal.state,
            created_at=proposal.created_at,
            symbol=intent.get("instrument", {}).get("symbol"),
            side=intent.get("side"),
            quantity=Decimal(str(intent.get("quantity", 0))),
            gross_notional=gross_notional,
            risk_decision=risk_decision,
            risk_reason=risk_reason,
        )
