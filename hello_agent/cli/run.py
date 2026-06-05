"""`hello-agent run` 鈥?one-shot non-interactive run."""
from __future__ import annotations

import json

import typer

from hello_agent.agents.react import ReActAgent
from hello_agent.core.config import get_config
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import Role
from hello_agent.tools.registry import registry

app = typer.Typer(help="Run a one-shot query.")
logger = get_logger(__name__)


@app.command(name="run")
def run_cmd(
    query: str = typer.Argument(..., help="The user query / task."),
    session: str | None = typer.Option(None, "--session", "-s"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of plain text."),
) -> None:
    """Run the agent once and print the final reply."""
    cfg = get_config()
    llm = LLMClient()
    system_prompt = (
        "You are hello-agent, a personal Windows Python agent. "
        "Be concise. Use tools when they help."
    )
    agent = ReActAgent(
        llm=llm,
        tool_registry=registry,
        system_prompt=system_prompt,
        max_iterations=cfg.agent.max_iterations,
        max_cost_per_turn_usd=cfg.agent.max_cost_per_turn_usd,
        session_id=session,
    )
    try:
        state = agent.run(query)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    last = state.messages[-1] if state.messages else None
    text = last.content if last and last.role == Role.ASSISTANT else ""

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "session_id": agent.session_id,
                    "iterations": state.iteration,
                    "reply": text,
                    "messages": [m.to_dict() for m in state.messages],
                },
                ensure_ascii=False,
            )
        )
    else:
        if text:
            typer.echo(text)
        else:
            typer.echo("(no reply)", err=True)
            raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
