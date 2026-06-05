"""`hello-agent run` — one-shot non-interactive run.

`hello-agent run --agent-type react "ping"` runs a single turn and prints
the final reply. Without `--agent-type`, the `TaskRouter` classifies the
query using a zero-shot LLM call (with a rule-based fallback).
"""
from __future__ import annotations

import json
import os

import typer

from hello_agent.agents.router import VALID_AGENT_TYPES, TaskRouter
from hello_agent.core.config import get_config
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import Role
from hello_agent.tools.registry import registry

logger = get_logger(__name__)

# Use a callback (not a @command) so `hello-agent run "ping"` parses the
# message as a positional, not as a subcommand. This mirrors the pattern
# used in `chat_app.py`.
app = typer.Typer(
    help="Run a one-shot query.",
    invoke_without_command=True,
    add_completion=False,
)

# Default system prompt. Pulled into a module constant so tests can
# reference it without instantiating the agent.
_DEFAULT_SYSTEM_PROMPT = (
    "You are hello-agent, a personal Windows Python agent. "
    "Be concise. Use tools when they help."
)


def _resolve_agent_type(value: str | None) -> str:
    """Normalize a CLI / config agent_type value to a known lowercase label.

    Accepts `simple|react|plan_solve|reflection` (and a few common aliases
    like `plan-and-solve` and `plan_and_solve`). Unknown values fall back
    to `react` with a warning so the user still gets a response.
    """
    if value is None:
        return "react"
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "plan_and_solve": "plan_solve",
        "plan": "plan_solve",
        "reflect": "reflection",
        "react_loop": "react",
        "default": "react",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in VALID_AGENT_TYPES:
        return normalized
    typer.echo(
        f"warning: unknown --agent-type {value!r}; "
        f"valid: {', '.join(VALID_AGENT_TYPES)}. Falling back to 'react'.",
        err=True,
    )
    return "react"


def _build_agent(agent_type: str, session_id: str | None, llm: LLMClient, cfg):
    """Construct the agent for `agent_type` via the central router dispatcher."""
    return TaskRouter.dispatch(
        agent_type=agent_type,  # type: ignore[arg-type]
        llm=llm,
        tool_registry=registry,
        system_prompt=_DEFAULT_SYSTEM_PROMPT,
        max_iterations=cfg.agent.max_iterations,
        max_cost_per_turn_usd=cfg.agent.max_cost_per_turn_usd,
        session_id=session_id,
    )


def _format_no_key_help() -> str:
    """Friendly message printed when LLM_API_KEY is empty."""
    return (
        "no LLM_API_KEY set — skipping the network call.\n"
        "Set LLM_API_KEY in .env or the environment to enable real LLM calls.\n"
        "See `hello-agent doctor` for the full env checklist."
    )


def _env_key_present() -> bool:
    """Return True if any LLM_API_KEY source (env var or pydantic-settings) is set."""
    if os.environ.get("LLM_API_KEY", "").strip():
        return True
    try:
        from hello_agent.core.config import get_env

        return bool(get_env().llm_api_key)
    except Exception:  # noqa: BLE001
        return False


@app.callback(invoke_without_command=True)
def run_cmd(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="The user query / task."),
    session: str | None = typer.Option(None, "--session", "-s"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of plain text."),
    agent_type: str | None = typer.Option(
        None,
        "--agent-type",
        "-a",
        help=f"Agent type. One of: {', '.join(VALID_AGENT_TYPES)}. "
        "Omit to let the TaskRouter pick automatically (LLM-first, rule fallback).",
    ),
    router_explain: bool = typer.Option(
        False,
        "--router-explain",
        help="Print which agent type was chosen (and why) before running.",
    ),
) -> None:
    """Run the agent once and print the final reply.

    Without `--agent-type`, the `TaskRouter` classifies the query using a
    zero-shot LLM call and falls back to rule-based heuristics if the
    LLM call is unavailable. Pass `--agent-type react` (the default per
    `config.yaml`) to skip classification and use the standard ReAct loop.
    """
    cfg = get_config()

    # Short-circuit on missing API key: print a clear message and exit 0
    # so smoke tests don't fail on machines without credentials. We check
    # the env first (cheap) before constructing the LLMClient.
    if not _env_key_present():
        if router_explain:
            typer.echo("[router] no LLM_API_KEY — cannot run any agent. Skipping.")
        typer.echo(_format_no_key_help())
        raise typer.Exit(code=0)

    llm = LLMClient()
    resolved = _resolve_agent_type(agent_type)
    if router_explain:
        typer.echo(f"[router] selected agent type: {resolved!r} (source=cli/explicit)")
    agent = _build_agent(resolved, session, llm, cfg)

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
                    "agent_type": resolved,
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
