"""`hello-agent chat` subcommand.

Uses a Typer callback (not a sub-command) so the message positional is
parsed as `hello-agent chat "ping"`, not `hello-agent chat ping` (where
`ping` would be a subcommand of `chat`).
"""
from __future__ import annotations

import typer

from hello_agent.cli.chat import run_chat

app = typer.Typer(help="Chat with the agent.", invoke_without_command=True)


@app.callback()
def chat(
    message: str | None = typer.Argument(
        None, help="Single message. If omitted, starts the REPL."
    ),
    session: str | None = typer.Option(
        None, "--session", "-s", help="Stable session id."
    ),
    agent_type: str | None = typer.Option(
        None, "--type", "-t", help="simple|react|plan_solve|reflection"
    ),
    plain: bool = typer.Option(False, "--plain", help="Disable streaming tool cards."),
) -> None:
    """Chat with the agent."""
    run_chat(message=message, session=session, agent_type=agent_type, plain=plain)


if __name__ == "__main__":
    # Allow `python -m hello_agent.cli.chat_app` for ad-hoc testing.
    app()
