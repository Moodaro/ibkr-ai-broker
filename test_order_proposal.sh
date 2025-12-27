#!/bin/bash
# Test Order Proposal - Comando curl corretto

curl -X 'POST' \
  'http://localhost:8000/api/v1/propose' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "account_id": "DU123456",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "MKT",
  "quantity": 5,
  "exchange": "SMART",
  "currency": "USD",
  "instrument_type": "STK",
  "reason": "Test order from curl",
  "strategy_tag": "manual_test"
}'
