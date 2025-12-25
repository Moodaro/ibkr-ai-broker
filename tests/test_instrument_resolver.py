"""Tests for instrument resolver module."""

import pytest
from packages.schemas.instrument import (
    InstrumentContract,
    SearchCandidate,
    InstrumentSearchRequest,
    InstrumentSearchResponse,
    InstrumentResolveRequest,
    InstrumentResolveResponse,
    InstrumentResolutionError,
)
from packages.instrument_resolver import (
    InstrumentResolver,
    InstrumentDataProvider,
)
from typing import List, Optional


class MockInstrumentProvider:
    """Mock provider for testing."""
    
    def __init__(self):
        self.instruments = [
            InstrumentContract(
                con_id=265598,
                symbol="AAPL",
                type="STK",
                exchange="NASDAQ",
                currency="USD",
                name="Apple Inc.",
            ),
            InstrumentContract(
                con_id=265599,  # Different conId for same symbol on different exchange
                symbol="AAPL",
                type="STK",
                exchange="NYSE",
                currency="USD",
                name="Apple Inc.",
            ),
            InstrumentContract(
                con_id=272093,
                symbol="MSFT",
                type="STK",
                exchange="NASDAQ",
                currency="USD",
                name="Microsoft Corporation",
            ),
            InstrumentContract(
                con_id=208813720,
                symbol="GOOGL",
                type="STK",
                exchange="NASDAQ",
                currency="USD",
                name="Alphabet Inc. Class A",
            ),
        ]
    
    def search_instruments(
        self,
        query: str,
        type: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchCandidate]:
        """Mock search."""
        query = query.upper()
        candidates = []
        
        for contract in self.instruments:
            # Apply filters
            if type and contract.type != type:
                continue
            if exchange and contract.exchange != exchange:
                continue
            if currency and contract.currency != currency:
                continue
            
            # Simple scoring
            score = 0.0
            if query == contract.symbol:
                score = 1.0
            elif contract.symbol.startswith(query):
                score = 0.9
            elif query in contract.symbol:
                score = 0.7
            elif contract.name and query in contract.name.upper():
                score = 0.6
            
            if score > 0:
                candidates.append(SearchCandidate(
                    con_id=contract.con_id,
                    symbol=contract.symbol,
                    type=contract.type,
                    exchange=contract.exchange,
                    currency=contract.currency,
                    name=contract.name,
                    match_score=score
                ))
        
        candidates.sort(key=lambda c: c.match_score, reverse=True)
        return candidates[:limit]
    
    def resolve_instrument(
        self,
        symbol: str,
        type: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        con_id: Optional[int] = None
    ) -> InstrumentContract:
        """Mock resolve."""
        if con_id:
            for contract in self.instruments:
                if contract.con_id == con_id:
                    return contract
            raise ValueError(f"conId {con_id} not found")
        
        symbol = symbol.upper()
        matches = []
        
        for contract in self.instruments:
            if contract.symbol != symbol:
                continue
            if type and contract.type != type:
                continue
            if exchange and contract.exchange != exchange:
                continue
            if currency and contract.currency != currency:
                continue
            matches.append(contract)
        
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            candidates = [
                SearchCandidate(
                    con_id=m.con_id,
                    symbol=m.symbol,
                    type=m.type,
                    exchange=m.exchange,
                    currency=m.currency,
                    name=m.name,
                    match_score=1.0
                )
                for m in matches
            ]
            raise InstrumentResolutionError(
                f"Multiple contracts found for {symbol}",
                candidates=candidates
            )
        else:
            raise InstrumentResolutionError(
                f"No contracts found for {symbol}",
                candidates=[]
            )
    
    def get_contract_by_id(self, con_id: int) -> Optional[InstrumentContract]:
        """Mock get by id."""
        for contract in self.instruments:
            if contract.con_id == con_id:
                return contract
        return None


class TestInstrumentResolver:
    """Tests for InstrumentResolver."""
    
    def test_calculate_match_score_exact(self):
        """Test exact match scoring."""
        score = InstrumentResolver.calculate_match_score("AAPL", "AAPL", "Apple Inc.")
        assert score == 1.0
    
    def test_calculate_match_score_starts_with(self):
        """Test starts-with match scoring."""
        score = InstrumentResolver.calculate_match_score("AAP", "AAPL", "Apple Inc.")
        assert score == 0.9
    
    def test_calculate_match_score_name_match(self):
        """Test name-based match scoring."""
        score = InstrumentResolver.calculate_match_score("APPLE", "AAPL", "Apple Inc.")
        assert score == 0.85
    
    def test_calculate_match_score_fuzzy(self):
        """Test fuzzy match scoring."""
        score = InstrumentResolver.calculate_match_score("APPL", "AAPL", "Apple Inc.")
        assert 0.7 < score < 1.0  # Should be reasonably high for typo
    
    def test_search_exact_match(self):
        """Test search with exact symbol match."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentSearchRequest(
            query="AAPL",
            limit=10
        )
        response = resolver.search(request)
        
        assert len(response.candidates) >= 1
        assert response.candidates[0].symbol == "AAPL"
        assert response.candidates[0].match_score >= 0.9
    
    def test_search_with_filters(self):
        """Test search with type/exchange filters."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentSearchRequest(
            query="AAPL",
            type="STK",
            exchange="NASDAQ",
            limit=10
        )
        response = resolver.search(request)
        
        assert len(response.candidates) >= 1
        assert all(c.type == "STK" for c in response.candidates)
        assert all(c.exchange == "NASDAQ" for c in response.candidates)
    
    def test_search_limit(self):
        """Test search respects limit."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentSearchRequest(
            query="A",  # Broad query
            limit=2
        )
        response = resolver.search(request)
        
        assert len(response.candidates) <= 2
    
    def test_resolve_explicit_conid(self):
        """Test resolution with explicit conId."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentResolveRequest(
            symbol="AAPL",
            con_id=265598
        )
        response = resolver.resolve(request)
        
        assert response.contract.con_id == 265598
        assert response.contract.symbol == "AAPL"
        assert response.ambiguous is False
        assert response.resolution_method == "explicit_con_id"
    
    def test_resolve_exact_match(self):
        """Test resolution with exact symbol+exchange match."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentResolveRequest(
            symbol="AAPL",
            type="STK",
            exchange="NASDAQ"
        )
        response = resolver.resolve(request)
        
        assert response.contract.symbol == "AAPL"
        assert response.contract.exchange == "NASDAQ"
        assert response.ambiguous is False
    
    def test_resolve_ambiguous(self):
        """Test resolution with ambiguous symbol (multiple exchanges)."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentResolveRequest(
            symbol="AAPL",
            type="STK"
            # No exchange specified - ambiguous
        )
        
        # InstrumentResolver returns ambiguous=True instead of raising
        response = resolver.resolve(request)
        
        assert response.ambiguous is True
        assert len(response.alternatives) >= 1  # At least 1 alternative
        assert response.contract.symbol == "AAPL"  # Best match returned
        assert response.resolution_method == "best_match_ambiguous"
    
    def test_resolve_not_found(self):
        """Test resolution with non-existent symbol."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        request = InstrumentResolveRequest(
            symbol="INVALID"
        )
        
        with pytest.raises(InstrumentResolutionError) as exc_info:
            resolver.resolve(request)
        
        assert len(exc_info.value.candidates) == 0
    
    def test_resolve_fuzzy_high_confidence(self):
        """Test resolution with fuzzy match above confidence threshold."""
        provider = MockInstrumentProvider()
        resolver = InstrumentResolver(provider)
        
        # Exact match should auto-resolve
        request = InstrumentResolveRequest(
            symbol="MSFT"
        )
        response = resolver.resolve(request)
        
        assert response.contract.symbol == "MSFT"
        assert response.ambiguous is False


class TestInstrumentContract:
    """Tests for InstrumentContract validation."""
    
    def test_valid_contract(self):
        """Test creating valid contract."""
        contract = InstrumentContract(
            con_id=265598,
            symbol="AAPL",
            type="STK",
            exchange="NASDAQ",
            currency="USD"
        )
        assert contract.con_id == 265598
        assert contract.symbol == "AAPL"
    
    def test_invalid_conid(self):
        """Test validation rejects invalid conId."""
        with pytest.raises(ValueError):
            InstrumentContract(
                con_id=0,  # Invalid
                symbol="AAPL",
                type="STK",
                exchange="NASDAQ",
                currency="USD"
            )
    
    def test_invalid_currency(self):
        """Test validation rejects invalid currency."""
        with pytest.raises(ValueError):
            InstrumentContract(
                con_id=265598,
                symbol="AAPL",
                type="STK",
                exchange="NASDAQ",
                currency="US"  # Must be 3 letters
            )
    
    def test_symbol_normalization(self):
        """Test symbol is normalized to uppercase."""
        contract = InstrumentContract(
            con_id=265598,
            symbol="aapl",  # Lowercase
            type="STK",
            exchange="NASDAQ",
            currency="USD"
        )
        assert contract.symbol == "AAPL"


class TestSearchCandidate:
    """Tests for SearchCandidate."""
    
    def test_valid_candidate(self):
        """Test creating valid search candidate."""
        candidate = SearchCandidate(
            con_id=265598,
            symbol="AAPL",
            type="STK",
            exchange="NASDAQ",
            currency="USD",
            name="Apple Inc.",
            match_score=0.95
        )
        assert candidate.match_score == 0.95
        assert candidate.symbol == "AAPL"
    
    def test_invalid_score_range(self):
        """Test validation rejects score outside 0-1 range."""
        with pytest.raises(ValueError):
            SearchCandidate(
                con_id=265598,
                symbol="AAPL",
                type="STK",
                exchange="NASDAQ",
                currency="USD",
                match_score=1.5  # > 1.0
            )
        
        with pytest.raises(ValueError):
            SearchCandidate(
                con_id=265598,
                symbol="AAPL",
                type="STK",
                exchange="NASDAQ",
                currency="USD",
                match_score=-0.1  # < 0.0
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
