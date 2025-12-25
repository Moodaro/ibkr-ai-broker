"""
Example MCP client for testing IBKR AI Broker MCP server.

This script demonstrates how to interact with the MCP server
programmatically for testing purposes.
"""

import asyncio
import json
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.types import CallToolRequest


async def main():
    """Test MCP server with various tool calls."""
    
    # Configure server
    server_params = StdioServerParameters(
        command="python",
        args=["apps/mcp_server/run.py"],
        env=None,
    )
    
    print("=" * 60)
    print("IBKR AI Broker MCP Client Test")
    print("=" * 60)
    print()
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize connection
            await session.initialize()
            
            # List available tools
            print("📋 Available Tools:")
            print("-" * 60)
            tools_response = await session.list_tools()
            for tool in tools_response.tools:
                print(f"  • {tool.name}: {tool.description}")
            print()
            
            # Test 1: Get Portfolio
            print("🏦 Test 1: Get Portfolio")
            print("-" * 60)
            result = await session.call_tool(
                "get_portfolio",
                {"account_id": "DU123456"}
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 2: Get Positions
            print("📊 Test 2: Get Positions")
            print("-" * 60)
            result = await session.call_tool(
                "get_positions",
                {"account_id": "DU123456"}
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 3: Get Cash
            print("💰 Test 3: Get Cash")
            print("-" * 60)
            result = await session.call_tool(
                "get_cash",
                {"account_id": "DU123456"}
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 4: Simulate Order
            print("🎯 Test 4: Simulate Order (Buy 10 AAPL @ $190)")
            print("-" * 60)
            result = await session.call_tool(
                "simulate_order",
                {
                    "account_id": "DU123456",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "quantity": "10",
                    "order_type": "MKT",
                    "market_price": "190.00"
                }
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 5: Evaluate Risk
            print("⚖️ Test 5: Evaluate Risk (Buy 10 AAPL @ $190)")
            print("-" * 60)
            result = await session.call_tool(
                "evaluate_risk",
                {
                    "account_id": "DU123456",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "quantity": "10",
                    "order_type": "MKT",
                    "market_price": "190.00"
                }
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 6: Simulate Large Order (should trigger risk warnings)
            print("⚠️ Test 6: Simulate Large Order (Buy 1000 TSLA @ $250)")
            print("-" * 60)
            result = await session.call_tool(
                "simulate_order",
                {
                    "account_id": "DU123456",
                    "symbol": "TSLA",
                    "side": "BUY",
                    "quantity": "1000",
                    "order_type": "MKT",
                    "market_price": "250.00"
                }
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 7: Evaluate Risk for Large Order
            print("🚫 Test 7: Evaluate Risk (Buy 1000 TSLA - should REJECT)")
            print("-" * 60)
            result = await session.call_tool(
                "evaluate_risk",
                {
                    "account_id": "DU123456",
                    "symbol": "TSLA",
                    "side": "BUY",
                    "quantity": "1000",
                    "market_price": "250.00"
                }
            )
            print(f"Result: {result.content[0].text}")
            print()
            
            # Test 8: Error handling (missing parameter)
            print("❌ Test 8: Error Handling (missing account_id)")
            print("-" * 60)
            try:
                result = await session.call_tool(
                    "get_portfolio",
                    {}  # Missing account_id
                )
                print(f"Result: {result.content[0].text}")
            except Exception as e:
                print(f"Error (expected): {e}")
            print()
            
            print("=" * 60)
            print("✅ All tests completed!")
            print("=" * 60)


# Import ClientSession from mcp
from mcp import ClientSession


if __name__ == "__main__":
    asyncio.run(main())
