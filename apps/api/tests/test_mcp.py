"""Tests for ARIA Model Context Protocol (MCP) subsystem."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp.client import MCPClient, MCPError, MCPTool, MCPToolResult
from src.mcp.manager import MCPManager, get_mcp_manager


@pytest.mark.asyncio
async def test_mcp_tool_result():
    result = MCPToolResult(
        content=[
            {"type": "text", "text": "File contents here"},
            {"type": "text", "text": "Second line"},
        ]
    )
    assert result.text == "File contents here\nSecond line"
    assert not result.is_error


@pytest.mark.asyncio
async def test_mcp_client_handshake_mock():
    client = MCPClient(command="echo", server_name="test-server")

    # Mock process and stdio
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()

    # Provide valid JSON-RPC responses for initialize
    init_res = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-server", "version": "1.0.0"},
        },
    }).encode("utf-8") + b"\n"

    mock_proc.stdout = MagicMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=[init_res])

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        await client.connect()
        assert client.is_connected
        assert client.server_name == "test-server"

        # Test list_tools
        tools_res = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read file from disk",
                        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
                    }
                ]
            },
        }).encode("utf-8") + b"\n"
        mock_proc.stdout.readline = AsyncMock(return_value=tools_res)

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "read_file"
        assert tools[0].server_name == "test-server"

        # Test call_tool
        call_res = json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": "hello from mcp"}],
                "isError": False,
            },
        }).encode("utf-8") + b"\n"
        mock_proc.stdout.readline = AsyncMock(return_value=call_res)

        res = await client.call_tool("read_file", {"path": "test.txt"})
        assert res.text == "hello from mcp"
        assert not res.is_error

        await client.disconnect()
        assert not client.is_connected


@pytest.mark.asyncio
async def test_mcp_manager_registration():
    manager = MCPManager()
    manager.register_server("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "."])
    assert "filesystem" in manager._configs
    assert manager._configs["filesystem"].command == "npx"


def test_mcp_api_endpoints(client):
    # GET /mcp/servers
    res = client.get("/mcp/servers")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # POST /mcp/servers/register
    reg_payload = {
        "name": "test_sqlite",
        "command": "python",
        "args": ["-m", "mcp_sqlite"],
        "enabled": True,
    }
    res_reg = client.post("/mcp/servers/register", json=reg_payload)
    assert res_reg.status_code == 201
    assert res_reg.json()["name"] == "test_sqlite"

    # GET /mcp/tools
    res_tools = client.get("/mcp/tools")
    assert res_tools.status_code == 200
    assert isinstance(res_tools.json(), list)
