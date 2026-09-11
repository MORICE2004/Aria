"""MCP endpoints: manage servers, inspect tools, and execute actions."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.mcp import get_mcp_manager

router = APIRouter(prefix="/mcp", tags=["mcp"])


class ServerRegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    command: str = Field(min_length=1, max_length=500)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    enabled: bool = True


class ServerOut(BaseModel):
    name: str
    command: str
    args: list[str]
    enabled: bool
    connected: bool


class ToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


class ToolExecuteIn(BaseModel):
    server_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecuteOut(BaseModel):
    server_name: str
    tool_name: str
    is_error: bool
    text: str
    raw_content: list[dict[str, Any]]


@router.get("/servers", response_model=list[ServerOut])
async def list_servers():
    """List all configured MCP servers and their current connection status."""
    manager = get_mcp_manager()
    result = []
    for name, cfg in manager._configs.items():
        client = manager._clients.get(name)
        result.append(
            ServerOut(
                name=cfg.name,
                command=cfg.command,
                args=cfg.args,
                enabled=cfg.enabled,
                connected=bool(client and client.is_connected),
            )
        )
    return result


@router.post("/servers/register", response_model=ServerOut, status_code=201)
async def register_server(body: ServerRegisterIn):
    """Register a new MCP server configuration."""
    manager = get_mcp_manager()
    manager.register_server(
        name=body.name,
        command=body.command,
        args=body.args,
        env=body.env,
        cwd=body.cwd,
        enabled=body.enabled,
    )
    client = manager._clients.get(body.name)
    return ServerOut(
        name=body.name,
        command=body.command,
        args=body.args,
        enabled=body.enabled,
        connected=bool(client and client.is_connected),
    )


@router.get("/tools", response_model=list[ToolOut])
async def list_tools(refresh: bool = False):
    """List all available tools discovered across all enabled MCP servers."""
    manager = get_mcp_manager()
    tools = await manager.list_tools(force_refresh=refresh)
    return [
        ToolOut(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            server_name=t.server_name,
        )
        for t in tools
    ]


@router.post("/tools/execute", response_model=ToolExecuteOut)
async def execute_tool(
    body: ToolExecuteIn,
    session: AsyncSession = Depends(get_session),
):
    """Execute an MCP tool under Action Gateway governance."""
    manager = get_mcp_manager()
    try:
        result = await manager.execute_tool(
            server_name=body.server_name,
            tool_name=body.tool_name,
            arguments=body.arguments,
            session=session,
            origin="api",
        )
        return ToolExecuteOut(
            server_name=body.server_name,
            tool_name=body.tool_name,
            is_error=result.is_error,
            text=result.text,
            raw_content=result.content,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
