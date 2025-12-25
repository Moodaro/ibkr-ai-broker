"""
Run MCP server with correct Python path.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import and run
from apps.mcp_server.main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
