"""Agent registry.

Every capability (communication, job search, learning coach...) is an Agent
registered here. Phase 3 establishes the plumbing; real LLM-powered agents
arrive from Phase 4 on — each will be one new module in this package.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentInfo:
    """What the dashboard shows about an agent."""

    name: str
    description: str
    # Action types this agent may submit to the gateway — its permission
    # scope. Submitting anything else is a bug we can detect.
    allowed_actions: tuple[str, ...] = field(default=())


_registry: dict[str, AgentInfo] = {}


def register_agent(info: AgentInfo) -> None:
    if info.name in _registry:
        raise ValueError(f"Agent {info.name!r} already registered")
    _registry[info.name] = info


def list_agents() -> list[AgentInfo]:
    return list(_registry.values())


def get_agent(name: str) -> AgentInfo | None:
    return _registry.get(name)


# Import agent modules so their registrations run at startup.
from src.agents import communication, demo, jobsearch, learning  # noqa: E402,F401
from src.integrations import email  # noqa: E402,F401  (registers email.send executor)
