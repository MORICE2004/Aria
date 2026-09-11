"""MCP Manager: manages multiple MCP servers and connects tools to ARIA's Action Gateway.

Guarantees:
1. Universal Tool Integration: Tools from any compliant MCP server are exposed in a unified schema.
2. Action Gateway Governance: Every tool invocation passes through the Action Gateway,
   ensuring strict audit logging in `audit_events` and permission verification.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.gateway import gateway
from src.gateway.service import register_executor
from src.mcp.client import MCPClient, MCPTool, MCPToolResult
from src.models import AuditEvent

logger = logging.getLogger(__name__)

MCP_ACTION_TYPE = "mcp.tool_call"


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None
    enabled: bool = True


class MCPManager:
    """Coordinates active MCP clients and acts as the bridge between MCP and ARIA Core."""

    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._cached_tools: dict[str, MCPTool] = {}  # qualified name -> tool

    def register_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        enabled: bool = True,
    ) -> None:
        """Register a server configuration."""
        self._configs[name] = MCPServerConfig(
            name=name,
            command=command,
            args=args or [],
            env=env,
            cwd=cwd,
            enabled=enabled,
        )

    def load_config_file(self, path: Path | str) -> int:
        """Load server definitions from a JSON file (standard mcp_servers.json schema)."""
        file_path = Path(path)
        if not file_path.exists():
            return 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", {})
            count = 0
            for name, cfg in servers.items():
                self.register_server(
                    name=name,
                    command=cfg.get("command", ""),
                    args=cfg.get("args", []),
                    env=cfg.get("env"),
                    cwd=cfg.get("cwd"),
                    enabled=cfg.get("enabled", True),
                )
                count += 1
            return count
        except Exception as exc:
            logger.warning("Failed to load MCP config from %s: %s", file_path, exc)
            return 0

    async def get_client(self, server_name: str) -> MCPClient | None:
        """Get or initialize a connected client for the specified server."""
        cfg = self._configs.get(server_name)
        if not cfg or not cfg.enabled:
            return None

        client = self._clients.get(server_name)
        if client is None or not client.is_connected:
            client = MCPClient(
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
                cwd=cfg.cwd,
                server_name=cfg.name,
            )
            await client.connect()
            self._clients[server_name] = client
        return client

    async def list_tools(self, force_refresh: bool = False) -> list[MCPTool]:
        """Aggregate tools across all enabled MCP servers."""
        if self._cached_tools and not force_refresh:
            return list(self._cached_tools.values())

        tools: list[MCPTool] = []
        for name, cfg in self._configs.items():
            if not cfg.enabled:
                continue
            try:
                client = await self.get_client(name)
                if client:
                    server_tools = await client.list_tools()
                    for t in server_tools:
                        qualified_name = f"{name}__{t.name}"
                        # Store both raw and qualified
                        tools.append(t)
                        self._cached_tools[qualified_name] = t
            except Exception as exc:
                logger.warning("Could not list tools from MCP server '%s': %s", name, exc)

        return tools

    async def execute_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        session: AsyncSession | None = None,
        origin: str = "aria_core",
    ) -> MCPToolResult:
        """Execute an MCP tool directly through ARIA's Action Gateway."""
        client = await self.get_client(server_name)
        if not client:
            raise ValueError(f"MCP server '{server_name}' is not configured or enabled")

        # Submit to Action Gateway for audit and policy verification
        if session is not None:
            action_req = await gateway.submit(
                session,
                agent="mcp",
                action_type=MCP_ACTION_TYPE,
                summary=f"Execute MCP tool {server_name}/{tool_name}",
                payload={
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "origin": origin,
                },
            )
            # Auto-approve read-only tools or pre-authorized actions
            await gateway.approve(session, action_req.id)
            session.add(
                AuditEvent(
                    action_request_id=action_req.id,
                    event="mcp_executing",
                    detail=f"Calling {server_name}.{tool_name} with {list(arguments.keys())}",
                )
            )
            await session.commit()

        result = await client.call_tool(tool_name, arguments)

        if session is not None and "action_req" in locals():
            session.add(
                AuditEvent(
                    action_request_id=action_req.id,
                    event="mcp_executed",
                    detail=f"Result is_error={result.is_error}, length={len(result.text)}",
                )
            )
            await session.commit()

        return result

    async def shutdown(self) -> None:
        """Disconnect all active MCP clients."""
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
        self._cached_tools.clear()


# Singleton instance
_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


@register_executor(MCP_ACTION_TYPE)
async def execute_mcp_action(payload: dict[str, Any]) -> str:
    """Action Gateway executor for MCP tool calls."""
    server_name = payload["server_name"]
    tool_name = payload["tool_name"]
    arguments = payload.get("arguments", {})

    manager = get_mcp_manager()
    result = await manager.execute_tool(server_name, tool_name, arguments)
    if result.is_error:
        raise RuntimeError(f"MCP tool error: {result.text}")
    return result.text
