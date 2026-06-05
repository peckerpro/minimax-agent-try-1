"""`hello-agent chat` — interactive TUI.

`hello-agent chat "..."` runs one turn and exits.
`hello-agent chat` (no message) starts the interactive REPL.
"""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from hello_agent.agents.react import ReActAgent
from hello_agent.core.config import get_config
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.paths import get_hello_agent_home
from hello_agent.core.types import AgentState, Message, Role
from hello_agent.tools.registry import registry

console = Console()
logger = get_logger(__name__)


def _build_agent(
    session_id: str | None = None,
    agent_type: str | None = None,
) -> ReActAgent:
    cfg = get_config()
    atype = (agent_type or cfg.agent.default_type).lower()
    llm = LLMClient()
    system_prompt = (
        "You are hello-agent, a personal Windows Python agent. "
        "Be concise. Use tools when they help. Remember user preferences across the session."
    )
    if atype == "simple":
        # SimpleAgent doesn't use tools — wrap in a thin shim that still has the
        # same `run()` interface.
        from hello_agent.agents.base import Agent as _Agent

        class _SimpleAdapter(_Agent):
            def __init__(self_inner, llm_, system_prompt_, max_iterations_, session_id_):
                super().__init__(system_prompt_, max_iterations_, 0.50, session_id_)
                self_inner._llm = llm_

            def step(self_inner, state: AgentState) -> AgentState:
                resp = self_inner._llm.chat(state.messages, tools=None)
                state.messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=resp.choices[0].message.content,
                        finish_reason=resp.choices[0].finish_reason,
                    )
                )
                return state

        return _SimpleAdapter(  # type: ignore[return-value]
            llm, system_prompt, cfg.agent.max_iterations, session_id
        )

    return ReActAgent(
        llm=llm,
        tool_registry=registry,
        system_prompt=system_prompt,
        max_iterations=cfg.agent.max_iterations,
        max_cost_per_turn_usd=cfg.agent.max_cost_per_turn_usd,
        session_id=session_id,
    )


def _render_assistant(content: str) -> None:
    console.print(Panel(Markdown(content or "(empty)"), title="hello-agent", border_style="cyan"))


def _render_tool(name: str, args: dict, result_preview: str) -> None:
    args_str = json.dumps(args, ensure_ascii=False)[:200]
    preview = (result_preview or "")[:300]
    console.print(
        Panel(
            f"[bold]{name}[/bold]({args_str})\n\n→ {preview}",
            title="tool",
            border_style="magenta",
        )
    )


def _run_one(agent: ReActAgent, user_message: str) -> str:
    """Run one turn and stream the final assistant reply to stdout."""
    state = agent.run(user_message)
    last = state.messages[-1] if state.messages else None
    return last.content if last and last.role == Role.ASSISTANT else ""


def _run_one_repl(agent: ReActAgent, user_message: str) -> str:
    """Run a turn, streaming tool calls as they happen. Returns final text."""
    state = AgentState(
        session_id=agent.session_id,
        messages=[
            Message(role=Role.SYSTEM, content=agent.system_prompt),
            Message(role=Role.USER, content=user_message),
        ],
        max_iterations=agent.max_iterations,
    )

    final = ""
    with Live(Spinner("dots", text="thinking..."), console=console, transient=True) as live:
        for _ in range(agent.max_iterations):
            try:
                state = agent.step(state)
            except Exception as exc:  # noqa: BLE001
                live.update(Text(f"error: {exc}", style="red"))
                return f"[error: {exc}]"
            state.iteration += 1
            last = state.messages[-1] if state.messages else None
            if last is None:
                continue
            if last.role == Role.ASSISTANT and last.content:
                final = last.content
            if last.role == Role.ASSISTANT and last.tool_calls:
                # tool result is appended next iteration as a TOOL message
                for _tc in last.tool_calls:
                    pass
            if last.role == Role.TOOL:
                # Render the tool result we just appended
                prev_tool_call = None
                for m in state.messages:
                    if m.role == Role.ASSISTANT and m.tool_calls:
                        prev_tool_call = m.tool_calls[-1]
                if prev_tool_call:
                    _render_tool(prev_tool_call.name, prev_tool_call.arguments, last.content or "")
            if agent._is_terminal(state):
                break
    return final


# Public function — invoked by cli/main.py as the `chat` subcommand.
def run_chat(
    message: str | None = None,
    session: str | None = None,
    agent_type: str | None = None,
    plain: bool = False,
) -> None:
    """One-shot or REPL chat, depending on whether `message` is given.

    Exits 1 on error so the CLI exit code reflects failure to the user.
    """
    agent = _build_agent(session_id=session, agent_type=agent_type)
    if message:
        try:
            if plain:
                text = _run_one(agent, message)
            else:
                text = _run_one_repl(agent, message)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if text:
            _render_assistant(text)
        return

    # Interactive REPL
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
    except ImportError as exc:
        typer.echo("prompt_toolkit not installed; pip install hello-agent (or `uv sync`)")
        raise typer.Exit(code=1) from exc

    history_path = get_hello_agent_home() / "chat_history.txt"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    session_obj = PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
    )

    typer.echo(
        f"hello-agent REPL — session={agent.session_id}  (Ctrl-C or /quit to exit)"
    )
    while True:
        try:
            user_input = session_obj.prompt("> ")
        except (KeyboardInterrupt, EOFError):
            typer.echo("\nbye")
            return
        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input in ("/quit", "/exit", ":q"):
            return
        if user_input == "/help":
            typer.echo("Commands: /quit /exit /help")
            continue
        if plain:
            text = _run_one(agent, user_input)
        else:
            text = _run_one_repl(agent, user_input)
        if text:
            _render_assistant(text)


# Minimal stub Typer app so `from hello_agent.cli.chat import app` keeps working
# for back-compat. We do NOT add this app as a typer subcommand in main.py;
# main.py invokes run_chat() directly to keep `hello-agent chat "ping"` from
# being parsed as `hello-agent chat <subcommand>`.
app = typer.Typer(help="Chat with the agent (see `hello-agent chat --help` for options).")


@app.callback(invoke_without_command=True)
def _chat_callback(
    ctx: typer.Context,
    message: str | None = typer.Argument(None, help="Single message. If omitted, starts the REPL."),
    session: str | None = typer.Option(None, "--session", "-s", help="Stable session id."),
    agent_type: str | None = typer.Option(
        None, "--type", "-t", help="simple|react|plan_solve|reflection"
    ),
    plain: bool = typer.Option(False, "--plain", help="Disable streaming tool cards."),
) -> None:
    if ctx.invoked_subcommand is not None:
        # If someone adds a subcommand later, defer to it.
        return
    run_chat(message=message, session=session, agent_type=agent_type, plain=plain)


if __name__ == "__main__":
    # Allow `python -m hello_agent.cli.chat` for ad-hoc REPL testing.
    run_chat()
