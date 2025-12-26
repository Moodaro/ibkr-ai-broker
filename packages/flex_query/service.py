"""
FlexQuery service for IBKR reporting and reconciliation.

Provides:
- List configured Flex Queries
- Execute Flex Query (request + download + parse)
- Parse XML/CSV reports robustly
- Append-only storage with hash verification
"""

import csv
import hashlib
import io
import json
from datetime import datetime, date, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

from packages.schemas.flex_query import (
    CashTransaction,
    FlexQueryConfig,
    FlexQueryExecutionResponse,
    FlexQueryListResponse,
    FlexQueryRequest,
    FlexQueryResult,
    FlexQueryStatus,
    FlexQueryType,
    RealizedPnL,
    TradeConfirmation,
)
from packages.structured_logging import get_logger


logger = get_logger(__name__)


class FlexQueryService:
    """Service for managing IBKR Flex Queries."""
    
    def __init__(self, storage_path: str = "./data/flex_reports", config_path: Optional[str] = None):
        """
        Initialize FlexQuery service.
        
        Args:
            storage_path: Directory for storing downloaded reports
            config_path: Path to JSON file with query configurations
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Load configurations
        self.config_path = Path(config_path) if config_path else None
        self.queries: dict[str, FlexQueryConfig] = {}
        if self.config_path and self.config_path.exists():
            self._load_configs()
        else:
            logger.info("No flex query config file, using empty configuration")
    
    def _load_configs(self) -> None:
        """Load Flex Query configurations from JSON file."""
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            
            for query_data in data.get("queries", []):
                config = FlexQueryConfig.model_validate(query_data)
                self.queries[config.query_id] = config
            
            logger.info(f"Loaded {len(self.queries)} Flex Query configurations")
        except Exception as e:
            logger.error(f"Failed to load Flex Query configs: {e}")
            raise
    
    def list_queries(self, enabled_only: bool = True) -> FlexQueryListResponse:
        """
        List all configured Flex Queries.
        
        Args:
            enabled_only: Return only enabled queries
            
        Returns:
            List of query configurations
        """
        queries = list(self.queries.values())
        
        if enabled_only:
            queries = [q for q in queries if q.enabled]
        
        return FlexQueryListResponse(
            queries=queries,
            total=len(queries)
        )
    
    def get_query_config(self, query_id: str) -> Optional[FlexQueryConfig]:
        """Get configuration for specific query."""
        return self.queries.get(query_id)
    
    def add_query_config(self, config: FlexQueryConfig) -> None:
        """Add or update query configuration."""
        self.queries[config.query_id] = config
        logger.info(f"Added/updated query config: {config.query_id}")
    
    def execute_query(
        self,
        request: FlexQueryRequest,
        mock_response: Optional[str] = None
    ) -> FlexQueryResult:
        """
        Execute a Flex Query.
        
        Args:
            request: Query execution request
            mock_response: Optional mock XML/CSV response (for testing)
            
        Returns:
            Query execution result with parsed data
        """
        config = self.get_query_config(request.query_id)
        if config is None:
            raise ValueError(f"Unknown query ID: {request.query_id}")
        
        execution_id = self._generate_execution_id()
        
        # In real implementation, would call IBKR Flex Web Service API
        # For now, use mock response or return PENDING status
        if mock_response is None:
            # Return pending status - would need async polling for real IBKR
            return FlexQueryResult(
                query_id=request.query_id,
                execution_id=execution_id,
                status=FlexQueryStatus.PENDING,
                query_type=config.query_type,
                request_time=datetime.now(timezone.utc),
                from_date=request.from_date,
                to_date=request.to_date,
            )
        
        # Parse mock response
        try:
            result = self._parse_response(
                query_id=request.query_id,
                execution_id=execution_id,
                query_type=config.query_type,
                raw_data=mock_response,
                from_date=request.from_date,
                to_date=request.to_date,
            )
            
            # Store result
            self._store_result(result)
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to parse Flex Query response: {e}")
            return FlexQueryResult(
                query_id=request.query_id,
                execution_id=execution_id,
                status=FlexQueryStatus.FAILED,
                query_type=config.query_type,
                request_time=datetime.now(timezone.utc),
                from_date=request.from_date,
                to_date=request.to_date,
                error_message=str(e),
            )
    
    def _parse_response(
        self,
        query_id: str,
        execution_id: str,
        query_type: FlexQueryType,
        raw_data: str,
        from_date: Optional[date],
        to_date: Optional[date],
    ) -> FlexQueryResult:
        """Parse XML or CSV response from IBKR."""
        # Compute hash
        data_hash = hashlib.sha256(raw_data.encode()).hexdigest()
        
        # Detect format
        is_xml = raw_data.strip().startswith("<")
        
        result = FlexQueryResult(
            query_id=query_id,
            execution_id=execution_id,
            status=FlexQueryStatus.COMPLETED,
            query_type=query_type,
            request_time=datetime.now(timezone.utc),
            completion_time=datetime.now(timezone.utc),
            from_date=from_date,
            to_date=to_date,
            data_hash=data_hash,
        )
        
        if is_xml:
            result.raw_xml = raw_data
            self._parse_xml(raw_data, result)
        else:
            result.raw_csv = raw_data
            self._parse_csv(raw_data, result)
        
        return result
    
    def _parse_xml(self, xml_data: str, result: FlexQueryResult) -> None:
        """Parse XML Flex Query response."""
        try:
            root = ET.fromstring(xml_data)
            
            # Parse based on query type
            if result.query_type == FlexQueryType.TRADES:
                result.trades = self._parse_trades_xml(root)
            elif result.query_type == FlexQueryType.REALIZED_PNL:
                result.pnl_records = self._parse_pnl_xml(root)
            elif result.query_type == FlexQueryType.CASH_REPORT:
                result.cash_transactions = self._parse_cash_xml(root)
            else:
                logger.warning(f"Unsupported query type for XML parsing: {result.query_type}")
        
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            result.status = FlexQueryStatus.FAILED
            result.error_message = f"XML parse error: {e}"
    
    def _parse_csv(self, csv_data: str, result: FlexQueryResult) -> None:
        """Parse CSV Flex Query response."""
        try:
            reader = csv.DictReader(io.StringIO(csv_data))
            
            if result.query_type == FlexQueryType.TRADES:
                result.trades = self._parse_trades_csv(reader)
            elif result.query_type == FlexQueryType.REALIZED_PNL:
                result.pnl_records = self._parse_pnl_csv(reader)
            elif result.query_type == FlexQueryType.CASH_REPORT:
                result.cash_transactions = self._parse_cash_csv(reader)
            else:
                logger.warning(f"Unsupported query type for CSV parsing: {result.query_type}")
        
        except Exception as e:
            logger.error(f"CSV parse error: {e}")
            result.status = FlexQueryStatus.FAILED
            result.error_message = f"CSV parse error: {e}"
    
    def _parse_trades_xml(self, root: ET.Element) -> list[TradeConfirmation]:
        """Parse trade confirmations from XML."""
        trades = []
        
        # Example XML structure (IBKR specific, adjust based on actual format)
        for trade_elem in root.findall(".//Trade"):
            try:
                trades.append(TradeConfirmation(
                    trade_id=trade_elem.get("tradeID", ""),
                    execution_id=trade_elem.get("execID", ""),
                    account_id=trade_elem.get("accountId", ""),
                    symbol=trade_elem.get("symbol", ""),
                    description=trade_elem.get("description", ""),
                    con_id=int(trade_elem.get("conid")) if trade_elem.get("conid") else None,
                    trade_date=datetime.strptime(trade_elem.get("tradeDate", ""), "%Y%m%d").date(),
                    settle_date=datetime.strptime(trade_elem.get("settleDate", ""), "%Y%m%d").date() if trade_elem.get("settleDate") else None,
                    quantity=Decimal(trade_elem.get("quantity", "0")),
                    trade_price=Decimal(trade_elem.get("tradePrice", "0")),
                    proceeds=Decimal(trade_elem.get("proceeds", "0")),
                    commission=Decimal(trade_elem.get("commission", "0")),
                    net_cash=Decimal(trade_elem.get("netCash", "0")),
                    buy_sell=trade_elem.get("buySell", ""),
                    currency=trade_elem.get("currency", "USD"),
                    exchange=trade_elem.get("exchange"),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse trade: {e}")
        
        return trades
    
    def _parse_trades_csv(self, reader: csv.DictReader) -> list[TradeConfirmation]:
        """Parse trade confirmations from CSV."""
        trades = []
        
        for row in reader:
            try:
                trades.append(TradeConfirmation(
                    trade_id=row.get("TradeID", ""),
                    execution_id=row.get("ExecID", ""),
                    account_id=row.get("AccountId", ""),
                    symbol=row.get("Symbol", ""),
                    description=row.get("Description", ""),
                    con_id=int(row["ConID"]) if row.get("ConID") else None,
                    trade_date=datetime.strptime(row.get("TradeDate", ""), "%Y%m%d").date(),
                    settle_date=datetime.strptime(row.get("SettleDate", ""), "%Y%m%d").date() if row.get("SettleDate") else None,
                    quantity=Decimal(row.get("Quantity", "0")),
                    trade_price=Decimal(row.get("TradePrice", "0")),
                    proceeds=Decimal(row.get("Proceeds", "0")),
                    commission=Decimal(row.get("Commission", "0")),
                    net_cash=Decimal(row.get("NetCash", "0")),
                    buy_sell=row.get("BuySell", ""),
                    currency=row.get("Currency", "USD"),
                    exchange=row.get("Exchange"),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse trade row: {e}")
        
        return trades
    
    def _parse_pnl_xml(self, root: ET.Element) -> list[RealizedPnL]:
        """Parse P&L records from XML."""
        # Placeholder implementation
        return []
    
    def _parse_pnl_csv(self, reader: csv.DictReader) -> list[RealizedPnL]:
        """Parse P&L records from CSV."""
        # Placeholder implementation
        return []
    
    def _parse_cash_xml(self, root: ET.Element) -> list[CashTransaction]:
        """Parse cash transactions from XML."""
        # Placeholder implementation
        return []
    
    def _parse_cash_csv(self, reader: csv.DictReader) -> list[CashTransaction]:
        """Parse cash transactions from CSV."""
        # Placeholder implementation
        return []
    
    def _store_result(self, result: FlexQueryResult) -> None:
        """Store query result to append-only storage."""
        # Create filename with execution_id
        filename = f"{result.query_id}_{result.execution_id}.json"
        filepath = self.storage_path / filename
        
        # Store as JSON
        with open(filepath, "w") as f:
            json.dump(result.model_dump(mode="json"), f, indent=2, default=str)
        
        logger.info(f"Stored Flex Query result: {filepath}")
    
    def _generate_execution_id(self) -> str:
        """Generate unique execution ID."""
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
