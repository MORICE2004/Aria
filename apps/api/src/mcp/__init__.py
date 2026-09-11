"""Model Context Protocol (MCP) Subsystem for ARIA."""

from src.mcp.client import MCPClient, MCPError, MCPTool, MCPToolResult
from src.mcp.manager import MCPManager, get_mcp_manager

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPManager",
    "MCPTool",
    "MCPToolResult",
    "get_mcp_manager",
]
