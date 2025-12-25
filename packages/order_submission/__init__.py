"""
Order submission logic for IBKR AI Broker.

Handles token validation, order submission to broker,
state transitions, and audit trail.
"""

from datetime import datetime, timezone
from typing import Optional
import json

from packages.approval_service import ApprovalService
from packages.audit_store import AuditStore, AuditEventCreate, EventType
from packages.broker_ibkr.adapter import BrokerAdapter
from packages.broker_ibkr.models import OpenOrder, OrderStatus
from packages.schemas.approval import OrderState
from packages.schemas.order_intent import OrderIntent


class OrderSubmissionError(Exception):
    """Error during order submission."""
    pass


class OrderSubmitter:
    """
    Handles order submission with token validation and audit trail.
    
    Workflow:
    1. Validate approval token (not expired, not used, hash matches)
    2. Consume token (mark as used)
    3. Transition proposal to SUBMITTED
    4. Submit order to broker
    5. Emit audit events
    6. Poll order status until terminal state
    """
    
    def __init__(
        self,
        broker: BrokerAdapter,
        approval_service: ApprovalService,
        audit_store: Optional[AuditStore] = None,
    ):
        """Initialize order submitter.
        
        Args:
            broker: Broker adapter for order submission.
            approval_service: Approval service for token validation.
            audit_store: Audit store for event logging (optional).
        """
        self._broker = broker
        self._approval_service = approval_service
        self._audit_store = audit_store
    
    def submit_order(
        self,
        proposal_id: str,
        token_id: str,
        correlation_id: str,
        current_time: Optional[datetime] = None,
    ) -> OpenOrder:
        """Submit order to broker with token validation.
        
        Args:
            proposal_id: ID of proposal to submit.
            token_id: Approval token ID.
            correlation_id: Request correlation ID.
            current_time: Current time (defaults to now UTC).
            
        Returns:
            OpenOrder with broker order ID and initial status.
            
        Raises:
            OrderSubmissionError: If submission fails.
            ValueError: If token or proposal invalid.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Get proposal
        proposal = self._approval_service.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        if proposal.state != OrderState.APPROVAL_GRANTED:
            raise ValueError(
                f"Cannot submit proposal in state {proposal.state}. "
                "Must be APPROVAL_GRANTED."
            )
        
        # Validate token
        is_valid = self._approval_service.validate_token(
            token_id,
            proposal.intent_hash,
            current_time,
        )
        if not is_valid:
            self._emit_event(
                "OrderSubmissionFailed",
                correlation_id,
                {
                    "proposal_id": proposal_id,
                    "token_id": token_id,
                    "reason": "Invalid or expired token",
                },
            )
            raise ValueError("Invalid or expired approval token")
        
        # Consume token (single-use enforcement)
        try:
            self._approval_service.consume_token(token_id, current_time)
        except ValueError as e:
            self._emit_event(
                "OrderSubmissionFailed",
                correlation_id,
                {
                    "proposal_id": proposal_id,
                    "token_id": token_id,
                    "reason": f"Token consumption failed: {e}",
                },
            )
            raise OrderSubmissionError(f"Failed to consume token: {e}")
        
        # Parse OrderIntent from JSON
        try:
            intent_dict = json.loads(proposal.intent_json)
            order_intent = OrderIntent(**intent_dict)
        except Exception as e:
            self._emit_event(
                "OrderSubmissionFailed",
                correlation_id,
                {
                    "proposal_id": proposal_id,
                    "reason": f"Failed to parse OrderIntent: {e}",
                },
            )
            raise OrderSubmissionError(f"Invalid OrderIntent: {e}")
        
        # Submit to broker
        try:
            # Get token for broker (token already consumed, pass for logging)
            token = self._approval_service.get_token(token_id)
            if token is None:
                raise OrderSubmissionError("Token not found after consumption")
            
            open_order = self._broker.submit_order(order_intent, token)
        except Exception as e:
            self._emit_event(
                "OrderSubmissionFailed",
                correlation_id,
                {
                    "proposal_id": proposal_id,
                    "token_id": token_id,
                    "reason": f"Broker submission failed: {e}",
                },
            )
            raise OrderSubmissionError(f"Failed to submit to broker: {e}")
        
        # Transition proposal to SUBMITTED
        updated_proposal = proposal.with_state(
            OrderState.SUBMITTED,
            broker_order_id=open_order.broker_order_id,
        )
        self._approval_service.update_proposal(updated_proposal)
        
        # Emit success event
        self._emit_event(
            "OrderSubmitted",
            correlation_id,
            {
                "proposal_id": proposal_id,
                "token_id": token_id,
                "broker_order_id": open_order.broker_order_id,
                "order_type": open_order.order_type,
                "side": open_order.side,
                "quantity": str(open_order.quantity),
                "symbol": open_order.instrument.symbol,
                "status": open_order.status,
            },
        )
        
        return open_order
    
    def poll_order_until_terminal(
        self,
        broker_order_id: str,
        proposal_id: str,
        correlation_id: str,
        max_polls: int = 60,
        poll_interval_seconds: int = 1,
    ) -> OpenOrder:
        """Poll order status until terminal state.
        
        Terminal states: FILLED, CANCELLED, REJECTED.
        
        Args:
            broker_order_id: Broker order ID.
            proposal_id: Proposal ID.
            correlation_id: Request correlation ID.
            max_polls: Maximum number of polls before timeout.
            poll_interval_seconds: Seconds between polls.
            
        Returns:
            OpenOrder in terminal state.
            
        Raises:
            OrderSubmissionError: If polling times out or fails.
        """
        import time
        
        terminal_states = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }
        
        for poll_count in range(max_polls):
            try:
                order = self._broker.get_order_status(broker_order_id)
                
                if order.status in terminal_states:
                    # Update proposal state
                    proposal = self._approval_service.get_proposal(proposal_id)
                    if proposal:
                        new_state = self._order_status_to_state(order.status)
                        updated_proposal = proposal.with_state(new_state)
                        self._approval_service.update_proposal(updated_proposal)
                        
                        # Emit terminal event
                        self._emit_event(
                            f"Order{order.status.capitalize()}",
                            correlation_id,
                            {
                                "proposal_id": proposal_id,
                                "broker_order_id": broker_order_id,
                                "status": order.status,
                                "filled_quantity": str(order.filled_quantity) if order.filled_quantity else "0",
                                "average_fill_price": str(order.average_fill_price) if order.average_fill_price else None,
                            },
                        )
                    
                    return order
                
                # Not terminal yet, wait and retry
                if poll_count < max_polls - 1:
                    time.sleep(poll_interval_seconds)
                    
            except Exception as e:
                self._emit_event(
                    "OrderPollingError",
                    correlation_id,
                    {
                        "proposal_id": proposal_id,
                        "broker_order_id": broker_order_id,
                        "poll_count": poll_count,
                        "error": str(e),
                    },
                )
                # Continue polling on transient errors
                if poll_count < max_polls - 1:
                    time.sleep(poll_interval_seconds)
        
        # Timeout
        raise OrderSubmissionError(
            f"Order polling timed out after {max_polls} attempts"
        )
    
    def _order_status_to_state(self, status: OrderStatus) -> OrderState:
        """Map OrderStatus to OrderState."""
        mapping = {
            OrderStatus.FILLED: OrderState.FILLED,
            OrderStatus.CANCELLED: OrderState.CANCELLED,
            OrderStatus.REJECTED: OrderState.REJECTED,
        }
        return mapping.get(status, OrderState.SUBMITTED)
    
    def _emit_event(
        self,
        event_type: str,
        correlation_id: str,
        data: dict,
    ) -> None:
        """Emit audit event."""
        if self._audit_store:
            # Map event type string to EventType enum
            event_type_mapping = {
                "OrderSubmissionFailed": EventType.ERROR_OCCURRED,
                "OrderSubmitted": EventType.ORDER_SUBMITTED,
                "OrderFilled": EventType.ORDER_FILLED,
                "OrderCancelled": EventType.ORDER_CANCELLED,
                "OrderRejected": EventType.ORDER_REJECTED,
                "OrderPollingError": EventType.ERROR_OCCURRED,
            }
            
            # Default to ERROR_OCCURRED if not mapped
            mapped_event_type = event_type_mapping.get(event_type, EventType.ERROR_OCCURRED)
            
            event = AuditEventCreate(
                event_type=mapped_event_type,
                correlation_id=correlation_id,
                data={"event_subtype": event_type, **data},
            )
            self._audit_store.append_event(event)


__all__ = [
    "OrderSubmitter",
    "OrderSubmissionError",
]
