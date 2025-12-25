"""
Instrument resolver for contract disambiguation and search.

Provides fuzzy search and resolution logic to convert user-provided
instrument identifiers into fully-qualified IBKR contracts.
"""

from typing import List, Optional, Protocol
from difflib import SequenceMatcher

from packages.schemas.instrument import (
    InstrumentContract,
    SearchCandidate,
    InstrumentSearchRequest,
    InstrumentSearchResponse,
    InstrumentResolveRequest,
    InstrumentResolveResponse,
    InstrumentResolutionError,
    InstrumentTypeEnum,
)


class InstrumentDataProvider(Protocol):
    """
    Protocol for instrument data retrieval.
    
    Implementations should provide access to instrument database.
    Used by InstrumentResolver to abstract data source.
    """
    
    def search_instruments(
        self,
        query: str,
        type: Optional[InstrumentTypeEnum] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchCandidate]:
        """
        Search for instruments matching query.
        
        Args:
            query: Search query (symbol or name)
            type: Optional instrument type filter
            exchange: Optional exchange filter
            currency: Optional currency filter
            limit: Maximum results to return
        
        Returns:
            List of matching candidates with scores
        """
        ...
    
    def resolve_instrument(
        self,
        symbol: str,
        type: Optional[InstrumentTypeEnum] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        con_id: Optional[int] = None
    ) -> InstrumentContract:
        """
        Resolve instrument to exact contract.
        
        Args:
            symbol: Instrument symbol
            type: Optional instrument type
            exchange: Optional exchange
            currency: Optional currency
            con_id: Optional explicit conId (bypasses resolution)
        
        Returns:
            Resolved instrument contract
        
        Raises:
            InstrumentResolutionError: If cannot resolve uniquely
        """
        ...
    
    def get_contract_by_id(self, con_id: int) -> Optional[InstrumentContract]:
        """Get contract by conId."""
        ...


class InstrumentResolver:
    """
    Instrument resolver with fuzzy search and smart resolution.
    
    Handles:
    - Fuzzy symbol matching
    - Type/exchange/currency disambiguation
    - Confidence scoring
    - Ambiguity detection
    """
    
    def __init__(self, provider: InstrumentDataProvider):
        """
        Initialize resolver.
        
        Args:
            provider: Instrument data provider
        """
        self.provider = provider
    
    def search(self, request: InstrumentSearchRequest) -> InstrumentSearchResponse:
        """
        Search for instruments.
        
        Args:
            request: Search request parameters
        
        Returns:
            Search response with ranked candidates
        """
        # Delegate to provider
        candidates = self.provider.search_instruments(
            query=request.query,
            type=request.type,
            exchange=request.exchange,
            currency=request.currency,
            limit=request.limit
        )
        
        # Build response
        filters = {}
        if request.type:
            filters["type"] = request.type
        if request.exchange:
            filters["exchange"] = request.exchange
        if request.currency:
            filters["currency"] = request.currency
        
        return InstrumentSearchResponse(
            query=request.query,
            candidates=candidates,
            total_found=len(candidates),
            filters_applied=filters
        )
    
    def resolve(self, request: InstrumentResolveRequest) -> InstrumentResolveResponse:
        """
        Resolve instrument to exact contract.
        
        Args:
            request: Resolution request parameters
        
        Returns:
            Resolution response with contract
        
        Raises:
            InstrumentResolutionError: If cannot resolve
        """
        # If conId provided, use it directly
        if request.con_id:
            contract = self.provider.get_contract_by_id(request.con_id)
            if contract is None:
                raise InstrumentResolutionError(
                    f"Contract with conId {request.con_id} not found"
                )
            
            return InstrumentResolveResponse(
                contract=contract,
                ambiguous=False,
                alternatives=[],
                resolution_method="explicit_con_id"
            )
        
        # Otherwise resolve via provider
        try:
            contract = self.provider.resolve_instrument(
                symbol=request.symbol,
                type=request.type,
                exchange=request.exchange,
                currency=request.currency
            )
            
            return InstrumentResolveResponse(
                contract=contract,
                ambiguous=False,
                alternatives=[],
                resolution_method="exact_match" if request.type else "inferred"
            )
        
        except InstrumentResolutionError as e:
            # Ambiguous - search for alternatives
            candidates = self.provider.search_instruments(
                query=request.symbol,
                type=request.type,
                exchange=request.exchange,
                currency=request.currency,
                limit=10
            )
            
            if not candidates:
                raise InstrumentResolutionError(
                    f"No instruments found matching '{request.symbol}'"
                )
            
            # If single high-confidence match, use it
            if len(candidates) == 1 and candidates[0].match_score >= 0.95:
                contract = self.provider.get_contract_by_id(candidates[0].con_id)
                if contract:
                    return InstrumentResolveResponse(
                        contract=contract,
                        ambiguous=False,
                        alternatives=[],
                        resolution_method="single_high_confidence"
                    )
            
            # Multiple matches - return as ambiguous
            # Use best match as primary result
            best = candidates[0]
            contract = self.provider.get_contract_by_id(best.con_id)
            
            if contract is None:
                raise InstrumentResolutionError(
                    f"Ambiguous symbol '{request.symbol}' - {len(candidates)} matches found",
                    candidates=candidates
                )
            
            return InstrumentResolveResponse(
                contract=contract,
                ambiguous=True,
                alternatives=candidates[1:5],  # Top 4 alternatives
                resolution_method="best_match_ambiguous"
            )
    
    @staticmethod
    def calculate_match_score(query: str, symbol: str, name: Optional[str] = None) -> float:
        """
        Calculate fuzzy match score between query and instrument.
        
        Args:
            query: Search query
            symbol: Instrument symbol
            name: Optional instrument name
        
        Returns:
            Match score (0-1)
        """
        query = query.upper().strip()
        symbol = symbol.upper().strip()
        
        # Exact match
        if query == symbol:
            return 1.0
        
        # Symbol starts with query
        if symbol.startswith(query):
            return 0.9
        
        # Fuzzy symbol match
        symbol_ratio = SequenceMatcher(None, query, symbol).ratio()
        
        # Check name if provided
        if name:
            name = name.upper()
            name_words = name.split()
            
            # Query matches any word in name
            if any(word.startswith(query) for word in name_words):
                return max(0.85, symbol_ratio)
            
            # Fuzzy name match
            name_ratio = max(
                SequenceMatcher(None, query, word).ratio()
                for word in name_words
            ) if name_words else 0
            
            return max(symbol_ratio, name_ratio * 0.8)
        
        return symbol_ratio


# Singleton resolver instance
_global_resolver: Optional[InstrumentResolver] = None


def get_instrument_resolver(provider: Optional[InstrumentDataProvider] = None) -> InstrumentResolver:
    """
    Get or create global instrument resolver.
    
    Args:
        provider: Optional provider (required for first call)
    
    Returns:
        Global resolver instance
    """
    global _global_resolver
    
    if _global_resolver is None:
        if provider is None:
            raise RuntimeError("InstrumentResolver not initialized - provider required")
        _global_resolver = InstrumentResolver(provider)
    
    return _global_resolver


def reset_instrument_resolver():
    """Reset global resolver (for testing)."""
    global _global_resolver
    _global_resolver = None
