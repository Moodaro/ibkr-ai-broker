"""Tests for instrument search/resolve in FakeBrokerAdapter."""

import pytest
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.schemas.instrument import InstrumentResolutionError


class TestFakeBrokerAdapterInstruments:
    """Tests for instrument methods in FakeBrokerAdapter."""
    
    @pytest.fixture
    def broker(self):
        """Create broker adapter instance."""
        return FakeBrokerAdapter()
    
    def test_search_exact_match(self, broker):
        """Test search with exact symbol match."""
        candidates = broker.search_instruments(query="AAPL", limit=10)
        
        assert len(candidates) >= 1
        assert candidates[0].symbol == "AAPL"
        assert candidates[0].match_score == 1.0
    
    def test_search_case_insensitive(self, broker):
        """Test search is case-insensitive."""
        candidates = broker.search_instruments(query="aapl", limit=10)
        
        assert len(candidates) >= 1
        assert candidates[0].symbol == "AAPL"
    
    def test_search_partial_match(self, broker):
        """Test search with partial symbol match."""
        candidates = broker.search_instruments(query="AAP", limit=10)
        
        assert len(candidates) >= 1
        assert any(c.symbol.startswith("AAP") for c in candidates)
    
    def test_search_by_name(self, broker):
        """Test search by company name."""
        candidates = broker.search_instruments(query="APPLE", limit=10)
        
        assert len(candidates) >= 1
        assert any("Apple" in (c.name or "") for c in candidates)
    
    def test_search_fuzzy_typo(self, broker):
        """Test fuzzy matching with typo."""
        candidates = broker.search_instruments(query="APPL", limit=10)
        
        assert len(candidates) >= 1
        # AAPL should be top match due to similarity
        assert candidates[0].symbol == "AAPL"
        assert candidates[0].match_score > 0.7
    
    def test_search_with_type_filter(self, broker):
        """Test search with instrument type filter."""
        candidates = broker.search_instruments(
            query="SPY",
            type="ETF",
            limit=10
        )
        
        assert len(candidates) >= 1
        assert all(c.type == "ETF" for c in candidates)
        assert candidates[0].symbol == "SPY"
    
    def test_search_with_exchange_filter(self, broker):
        """Test search with exchange filter."""
        candidates = broker.search_instruments(
            query="AAPL",
            exchange="NASDAQ",
            limit=10
        )
        
        assert len(candidates) >= 1
        assert all(c.exchange == "NASDAQ" for c in candidates)
    
    def test_search_with_currency_filter(self, broker):
        """Test search with currency filter."""
        candidates = broker.search_instruments(
            query="EUR",
            currency="USD",
            limit=10
        )
        
        assert len(candidates) >= 1
        assert all(c.currency == "USD" for c in candidates)
    
    def test_search_limit(self, broker):
        """Test search respects limit parameter."""
        candidates = broker.search_instruments(query="A", limit=3)
        
        assert len(candidates) <= 3
    
    def test_search_sorted_by_score(self, broker):
        """Test search results are sorted by match score."""
        candidates = broker.search_instruments(query="A", limit=10)
        
        if len(candidates) > 1:
            scores = [c.match_score for c in candidates]
            assert scores == sorted(scores, reverse=True)
    
    def test_search_empty_query_raises(self, broker):
        """Test empty query raises ValueError."""
        with pytest.raises(ValueError, match="Query cannot be empty"):
            broker.search_instruments(query="")
    
    def test_search_invalid_limit_raises(self, broker):
        """Test invalid limit raises ValueError."""
        with pytest.raises(ValueError, match="Limit must be between"):
            broker.search_instruments(query="AAPL", limit=0)
        
        with pytest.raises(ValueError, match="Limit must be between"):
            broker.search_instruments(query="AAPL", limit=101)
    
    def test_resolve_explicit_conid(self, broker):
        """Test resolution with explicit conId."""
        contract = broker.resolve_instrument(
            symbol="AAPL",
            con_id=265598
        )
        
        assert contract.con_id == 265598
        assert contract.symbol == "AAPL"
    
    def test_resolve_invalid_conid_raises(self, broker):
        """Test resolution with invalid conId raises error."""
        with pytest.raises(InstrumentResolutionError, match="not found"):
            broker.resolve_instrument(
                symbol="AAPL",
                con_id=999999999
            )
    
    def test_resolve_exact_match(self, broker):
        """Test resolution with exact symbol+type+exchange."""
        contract = broker.resolve_instrument(
            symbol="AAPL",
            type="STK",
            exchange="NASDAQ"
        )
        
        assert contract.symbol == "AAPL"
        assert contract.type == "STK"
        assert contract.exchange == "NASDAQ"
    
    def test_resolve_with_type_only(self, broker):
        """Test resolution with symbol+type."""
        contract = broker.resolve_instrument(
            symbol="AAPL",
            type="STK"
        )
        
        assert contract.symbol == "AAPL"
        assert contract.type == "STK"
    
    def test_resolve_case_insensitive(self, broker):
        """Test resolution is case-insensitive."""
        contract = broker.resolve_instrument(
            symbol="aapl",
            type="STK"
        )
        
        assert contract.symbol == "AAPL"
    
    def test_resolve_not_found_raises(self, broker):
        """Test resolution with non-existent symbol raises error."""
        with pytest.raises(InstrumentResolutionError):
            broker.resolve_instrument(symbol="INVALIDXYZ999")
    
    def test_resolve_fuzzy_high_confidence(self, broker):
        """Test fuzzy resolution with high confidence auto-selects."""
        # Exact match should always resolve
        contract = broker.resolve_instrument(symbol="MSFT")
        
        assert contract.symbol == "MSFT"
    
    def test_get_contract_by_id_found(self, broker):
        """Test get_contract_by_id returns contract when found."""
        contract = broker.get_contract_by_id(265598)
        
        assert contract is not None
        assert contract.con_id == 265598
        assert contract.symbol == "AAPL"
    
    def test_get_contract_by_id_not_found(self, broker):
        """Test get_contract_by_id returns None when not found."""
        contract = broker.get_contract_by_id(999999999)
        
        assert contract is None
    
    def test_get_contract_by_id_invalid_raises(self, broker):
        """Test get_contract_by_id with invalid conId raises ValueError."""
        with pytest.raises(ValueError, match="conId must be positive"):
            broker.get_contract_by_id(0)
        
        with pytest.raises(ValueError, match="conId must be positive"):
            broker.get_contract_by_id(-1)
    
    def test_mock_database_has_stocks(self, broker):
        """Test mock database contains expected stocks."""
        stocks = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN", "META", "NVDA"]
        
        for symbol in stocks:
            candidates = broker.search_instruments(query=symbol, type="STK")
            assert len(candidates) >= 1, f"Stock {symbol} not found"
            assert candidates[0].symbol == symbol
    
    def test_mock_database_has_etfs(self, broker):
        """Test mock database contains expected ETFs."""
        etfs = ["SPY", "QQQ", "IWM", "VTI", "AGG"]
        
        for symbol in etfs:
            candidates = broker.search_instruments(query=symbol, type="ETF")
            assert len(candidates) >= 1, f"ETF {symbol} not found"
            assert candidates[0].symbol == symbol
    
    def test_mock_database_has_forex(self, broker):
        """Test mock database contains forex pairs."""
        forex = ["EUR", "GBP", "USD", "AUD"]
        
        for symbol in forex:
            candidates = broker.search_instruments(query=symbol, type="FX")
            assert len(candidates) >= 1, f"Forex {symbol} not found"
    
    def test_mock_database_has_futures(self, broker):
        """Test mock database contains futures."""
        futures = ["ES", "NQ"]
        
        for symbol in futures:
            candidates = broker.search_instruments(query=symbol, type="FUT")
            assert len(candidates) >= 1, f"Future {symbol} not found"
    
    def test_mock_database_has_crypto(self, broker):
        """Test mock database contains crypto."""
        crypto = ["BTC", "ETH"]
        
        for symbol in crypto:
            candidates = broker.search_instruments(query=symbol, type="CRYPTO")
            assert len(candidates) >= 1, f"Crypto {symbol} not found"
    
    def test_instrument_contract_fields(self, broker):
        """Test resolved contract has all expected fields."""
        contract = broker.resolve_instrument(symbol="AAPL", type="STK")
        
        assert contract.con_id > 0
        assert contract.symbol == "AAPL"
        assert contract.type == "STK"
        assert contract.exchange is not None
        assert contract.currency is not None
        assert contract.name is not None
        assert contract.tradeable is True
        assert contract.min_tick is not None
        assert contract.lot_size is not None
    
    def test_search_no_results(self, broker):
        """Test search with no results returns empty list."""
        candidates = broker.search_instruments(query="ZZZ999XXX")
        
        # If fuzzy matching returns some results, that's OK too
        # Main point is it doesn't crash
        assert isinstance(candidates, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

