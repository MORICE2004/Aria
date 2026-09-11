"""Model Context Protocol (MCP) Client for ARIA.

Implements JSON-RPC 2.0 over standard I/O (stdio) to interact with any standard
MCP server (e.g., filesystem, SQLite, Git, fetch, memory) without custom wrappers.
Zero external dependencies beyond Python standard library.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    """Base exception for MCP protocol or execution errors."""


class MCPConnectionError(MCPError):
    """Failed to establish or maintain connection to an MCP server."""


class MCPTimeoutError(MCPError):
    """Timeout waiting for MCP server response."""


@dataclass(frozen=True)
class MCPTool:
    """Definition of a tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


@dataclass(frozen=True)
class MCPToolResult:
    """Result of executing an MCP tool."""

    content: list[dict[str, Any]]
    is_error: bool = False

    @property
    def text(self) -> str:
        """Convenience accessor to extract concatenated text content."""
        pieces = []
        for item in self.content:
            if isinstance(item, dict) and item.get("type") == "text":
                pieces.append(item.get("text", ""))
            elif isinstance(item, str):
                pieces.append(item)
            else:
                pieces.append(json.dumps(item))
        return "\n".join(pieces)


class MCPClient:
    """Asynchronous client that connects to an MCP server via stdio pipes."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        server_name: str = "unnamed",
        timeout: float = 15.0,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.server_name = server_name
        self.timeout = timeout

        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._connected = False
        self._server_capabilities: dict[str, Any] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected and self._proc is not None and self._proc.returncode is None

    async def connect(self) -> None:
        """Spawn the server process and complete the MCP initialization handshake."""
        if self.is_connected:
            return

        full_cmd = [self.command, *self.args]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                cwd=self.cwd,
            )
        except Exception as exc:
            raise MCPConnectionError(
                f"Failed to start MCP server '{self.server_name}' ({self.command}): {exc}"
            ) from exc

        # Complete initialization handshake
        try:
            init_response = await self._send_request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"roots": {"listChanged": False}},
                    "clientInfo": {"name": "aria-mcp-client", "version": "1.0.0"},
                },
            )
            self._server_capabilities = init_response.get("capabilities", {})
            # Send initialized notification (notifications have no ID and expect no response)
            await self._send_notification("notifications/initialized", {})
            self._connected = True
            logger.info("Connected to MCP server '%s'", self.server_name)
        except Exception as exc:
            await self.disconnect()
            raise MCPConnectionError(
                f"MCP handshake failed with server '{self.server_name}': {exc}"
            ) from exc

    async def disconnect(self) -> None:
        """Terminate the server process gracefully."""
        self._connected = False
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            finally:
                self._proc = None

    async def list_tools(self) -> list[MCPTool]:
        """Fetch all available tools from the MCP server."""
        response = await self._send_request("tools/list", {})
        tools_data = response.get("tools", [])
        return [
            MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.server_name,
            )
            for t in tools_data
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """Execute a tool on the MCP server."""
        response = await self._send_request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        content = response.get("content", [])
        is_error = response.get("isError", False)
        return MCPToolResult(content=content, is_error=is_error)

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if not self._proc or self._proc.returncode is not None:
                raise MCPConnectionError(f"Server '{self.server_name}' process is not running")

            self._request_id += 1
            req_id = self._request_id

            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            msg = json.dumps(payload) + "\n"

            try:
                assert self._proc.stdin is not None
                assert self._proc.stdout is not None
                self._proc.stdin.write(msg.encode("utf-8"))
                await self._proc.stdin.drain()

                # Read response with timeout
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=self.timeout
                )
                if not line:
                    raise MCPConnectionError(f"Server '{self.server_name}' closed stdout prematurely")

                data = json.loads(line.decode("utf-8").strip())
                if "error" in data:
                    err = data["error"]
                    code = err.get("code", -1)
                    message = err.get("message", "Unknown error")
                    raise MCPError(f"MCP error {code} from '{self.server_name}': {message}")

                return data.get("result", {})
            except asyncio.TimeoutError as exc:
                raise MCPTimeoutError(
                    f"Request '{method}' (id={req_id}) timed out after {self.timeout}s"
                ) from exc
            except json.JSONDecodeError as exc:
                raise MCPError(f"Invalid JSON from '{self.server_name}': {exc}") from exc

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        async with self._lock:
            if not self._proc or self._proc.returncode is not None:
                raise MCPConnectionError(f"Server '{self.server_name}' process is not running")

            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
            msg = json.dumps(payload) + "\n"
            assert self._proc.stdin is not None
            self._proc.stdin.write(msg.encode("utf-8"))
            await self._proc.stdin.drain()
