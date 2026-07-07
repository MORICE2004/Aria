"""Demo agent — proves the approval pipeline end to end, no LLM needed.

Its one action, "demo.echo", pretends to be something sensitive: it does
nothing until approved, and when executed it just returns the message it was
asked to "send". Phase 4's real email executor will replace a body like this
with an actual API call — the surrounding safety machinery stays identical.
"""

from src.agents import AgentInfo, register_agent
from src.gateway import register_executor

register_agent(
    AgentInfo(
        name="demo",
        description="Test agent for exercising the approval queue.",
        allowed_actions=("demo.echo",),
    )
)


@register_executor("demo.echo")
async def execute_demo_echo(payload: dict) -> str:
    return f"Executed after approval — message was: {payload.get('message', '')!r}"
