"""Action Gateway package — the ONLY exit for sensitive actions."""

from src.gateway.service import ActionGateway, register_executor

gateway = ActionGateway()  # one shared instance for the whole app

__all__ = ["ActionGateway", "gateway", "register_executor"]
