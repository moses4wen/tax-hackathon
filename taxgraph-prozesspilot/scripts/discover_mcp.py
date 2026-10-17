#!/usr/bin/env python3
"""Read-only MCP inventory; the API key is never a command-line argument."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mcp_client import discover_mcp


if __name__ == "__main__":
    result = asyncio.run(discover_mcp())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "connected" else 1)
