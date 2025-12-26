"""
Tests for FlexQuery service.
"""

import json
import pytest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from packages.flex_query.service import FlexQueryService
from packages.schemas.flex_query import (
    FlexQueryConfig,
    FlexQueryRequest,
    FlexQueryStatus,
    FlexQueryType,
)


@pytest.fixture
def temp_storage(tmp_path):
    """Temporary storage directory."""
    return str(tmp_path / "flex_reports")


@pytest.fixture
def sample_config_file(tmp_path):
    """Create sample config file."""
    config_data = {
        "queries": [
            {
                "query_id": "123456",
                "name": "Daily Trades",
                "query_type": "TRADES",
                "description": "Daily trade confirmations",
                "enabled": True,
                "auto_schedule": True,
                "schedule_cron": "0 9 * * *",
                "retention_days": 90,
            },
            {
                "query_id": "789012",
                "name": "Weekly P&L",
                "query_type": "REALIZED_PNL",
                "enabled": False,
                "auto_schedule": False,
                "retention_days": 180,
            }
        ]
    }
    
    config_file = tmp_path / "flex_queries.json"
    with open(config_file, "w") as f:
        json.dump(config_data, f)
    
    return str(config_file)


@pytest.fixture
def sample_xml_trades():
    """Sample XML response with trade confirmations."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
    <FlexStatements>
        <FlexStatement>
            <Trades>
                <Trade tradeID="T12345" execID="E67890" accountId="DU123456"
                       symbol="AAPL" description="Apple Inc." conid="265598"
                       tradeDate="20251226" settleDate="20251228"
                       quantity="100" tradePrice="195.50" proceeds="19550.00"
                       commission="1.00" netCash="19549.00" buySell="BUY"
                       currency="USD" exchange="NASDAQ"/>
                <Trade tradeID="T12346" execID="E67891" accountId="DU123456"
                       symbol="MSFT" description="Microsoft Corp." conid="272093"
                       tradeDate="20251226"
                       quantity="-50" tradePrice="375.00" proceeds="-18750.00"
                       commission="0.50" netCash="-18750.50" buySell="SELL"
                       currency="USD" exchange="NASDAQ"/>
            </Trades>
        </FlexStatement>
    </FlexStatements>
</FlexQueryResponse>"""


@pytest.fixture
def sample_csv_trades():
    """Sample CSV response with trade confirmations."""
    return """TradeID,ExecID,AccountId,Symbol,Description,ConID,TradeDate,SettleDate,Quantity,TradePrice,Proceeds,Commission,NetCash,BuySell,Currency,Exchange
T12345,E67890,DU123456,AAPL,Apple Inc.,265598,20251226,20251228,100,195.50,19550.00,1.00,19549.00,BUY,USD,NASDAQ
T12346,E67891,DU123456,MSFT,Microsoft Corp.,272093,20251226,,-50,375.00,-18750.00,0.50,-18750.50,SELL,USD,NASDAQ"""


def test_service_init_no_config(temp_storage):
    """Test service initialization without config file."""
    service = FlexQueryService(storage_path=temp_storage)
    
    assert service.storage_path == Path(temp_storage)
    assert len(service.queries) == 0
    assert service.storage_path.exists()


def test_service_init_with_config(temp_storage, sample_config_file):
    """Test service initialization with config file."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    assert len(service.queries) == 2
    assert "123456" in service.queries
    assert "789012" in service.queries
    
    # Check first query
    q1 = service.queries["123456"]
    assert q1.name == "Daily Trades"
    assert q1.query_type == FlexQueryType.TRADES
    assert q1.enabled is True
    assert q1.auto_schedule is True
    
    # Check second query
    q2 = service.queries["789012"]
    assert q2.name == "Weekly P&L"
    assert q2.enabled is False


def test_list_queries_all(temp_storage, sample_config_file):
    """Test listing all queries."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    response = service.list_queries(enabled_only=False)
    
    assert response.total == 2
    assert len(response.queries) == 2


def test_list_queries_enabled_only(temp_storage, sample_config_file):
    """Test listing only enabled queries."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    response = service.list_queries(enabled_only=True)
    
    assert response.total == 1
    assert len(response.queries) == 1
    assert response.queries[0].query_id == "123456"
    assert response.queries[0].enabled is True


def test_get_query_config(temp_storage, sample_config_file):
    """Test getting specific query config."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    config = service.get_query_config("123456")
    assert config is not None
    assert config.name == "Daily Trades"
    
    missing = service.get_query_config("999999")
    assert missing is None


def test_add_query_config(temp_storage):
    """Test adding query configuration."""
    service = FlexQueryService(storage_path=temp_storage)
    
    config = FlexQueryConfig(
        query_id="111111",
        name="New Query",
        query_type=FlexQueryType.TRADES,
    )
    
    service.add_query_config(config)
    
    assert "111111" in service.queries
    assert service.queries["111111"].name == "New Query"


def test_execute_query_no_mock_returns_pending(temp_storage, sample_config_file):
    """Test execute_query without mock returns PENDING status."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    request = FlexQueryRequest(
        query_id="123456",
        from_date=date(2025, 12, 1),
        to_date=date(2025, 12, 26),
    )
    
    result = service.execute_query(request)
    
    assert result.status == FlexQueryStatus.PENDING
    assert result.query_id == "123456"
    assert result.query_type == FlexQueryType.TRADES
    assert result.from_date == date(2025, 12, 1)
    assert result.to_date == date(2025, 12, 26)


def test_execute_query_unknown_query_id(temp_storage):
    """Test execute_query with unknown query ID raises error."""
    service = FlexQueryService(storage_path=temp_storage)
    
    request = FlexQueryRequest(query_id="999999")
    
    with pytest.raises(ValueError, match="Unknown query ID: 999999"):
        service.execute_query(request)


def test_execute_query_xml_trades(temp_storage, sample_config_file, sample_xml_trades):
    """Test execute_query with XML trade confirmations."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    request = FlexQueryRequest(query_id="123456")
    result = service.execute_query(request, mock_response=sample_xml_trades)
    
    assert result.status == FlexQueryStatus.COMPLETED
    assert result.raw_xml == sample_xml_trades
    assert result.raw_csv is None
    assert result.data_hash is not None
    
    # Check trades parsed
    assert len(result.trades) == 2
    
    # First trade (BUY)
    t1 = result.trades[0]
    assert t1.trade_id == "T12345"
    assert t1.symbol == "AAPL"
    assert t1.quantity == Decimal("100")
    assert t1.buy_sell == "BUY"
    assert t1.commission == Decimal("1.00")
    
    # Second trade (SELL)
    t2 = result.trades[1]
    assert t2.trade_id == "T12346"
    assert t2.symbol == "MSFT"
    assert t2.quantity == Decimal("-50")
    assert t2.buy_sell == "SELL"


def test_execute_query_csv_trades(temp_storage, sample_config_file, sample_csv_trades):
    """Test execute_query with CSV trade confirmations."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    request = FlexQueryRequest(query_id="123456")
    result = service.execute_query(request, mock_response=sample_csv_trades)
    
    assert result.status == FlexQueryStatus.COMPLETED
    assert result.raw_csv == sample_csv_trades
    assert result.raw_xml is None
    assert result.data_hash is not None
    
    # Check trades parsed
    assert len(result.trades) == 2
    assert result.trades[0].symbol == "AAPL"
    assert result.trades[1].symbol == "MSFT"


def test_execute_query_invalid_xml(temp_storage, sample_config_file):
    """Test execute_query with invalid XML."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    request = FlexQueryRequest(query_id="123456")
    result = service.execute_query(request, mock_response="<invalid>xml")
    
    assert result.status == FlexQueryStatus.FAILED
    assert result.error_message is not None
    assert "XML parse error" in result.error_message


def test_storage_creates_file(temp_storage, sample_config_file, sample_xml_trades):
    """Test that execute_query stores result to file."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    request = FlexQueryRequest(query_id="123456")
    result = service.execute_query(request, mock_response=sample_xml_trades)
    
    # Check file was created
    expected_file = Path(temp_storage) / f"123456_{result.execution_id}.json"
    assert expected_file.exists()
    
    # Check file content
    with open(expected_file) as f:
        stored_data = json.load(f)
    
    assert stored_data["query_id"] == "123456"
    assert stored_data["status"] == "COMPLETED"
    assert len(stored_data["trades"]) == 2


def test_hash_verification(temp_storage, sample_config_file, sample_xml_trades):
    """Test SHA256 hash is computed correctly."""
    service = FlexQueryService(
        storage_path=temp_storage,
        config_path=sample_config_file
    )
    
    request = FlexQueryRequest(query_id="123456")
    result = service.execute_query(request, mock_response=sample_xml_trades)
    
    # Verify hash
    import hashlib
    expected_hash = hashlib.sha256(sample_xml_trades.encode()).hexdigest()
    assert result.data_hash == expected_hash


def test_execution_id_generation(temp_storage):
    """Test execution ID is unique and timestamp-based."""
    import time
    service = FlexQueryService(storage_path=temp_storage)
    
    exec_id1 = service._generate_execution_id()
    time.sleep(0.001)  # Ensure different timestamp
    exec_id2 = service._generate_execution_id()
    
    # Should be different
    assert exec_id1 != exec_id2
    
    # Should contain date components
    assert len(exec_id1) > 15  # YYYYMMDD_HHMMSS_ffffff format
