"""`hello-agent completion` — generate shell completion scripts."""
import sys

import typer

app = typer.Typer(help="Print shell completion scripts (bash, zsh, fish, pwsh).")


@app.command("bash")
def bash() -> None:
    """Print the bash completion script."""
    sys.stdout.write(_SCRIPT_BASH)


@app.command("zsh")
def zsh() -> None:
    """Print the zsh completion script."""
    sys.stdout.write(_SCRIPT_ZSH)


@app.command("fish")
def fish() -> None:
    """Print the fish completion script."""
    sys.stdout.write(_SCRIPT_FISH)


@app.command("pwsh")
def pwsh() -> None:
    """Print the PowerShell completion script (sourced into $PROFILE)."""
    sys.stdout.write(_SCRIPT_PWSH)


# Minimal completion scripts — users can source them. For more complete
# coverage, point them at Typer's own script generators.
_SCRIPT_BASH = '''# hello-agent bash completion
_hello_agent() {
    local cur prev cmds
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmds="chat run serve rag memory tools mcp doctor completion autostart"
    if [[ ${COMP_CWORD} -eq 1 ]] ; then
        COMPREPLY=( $(compgen -W "${cmds}" -- ${cur}) )
        return 0
    fi
    COMPREPLY=( $(compgen -f -- ${cur}) )
    return 0
}
complete -F _hello_agent hello-agent
'''

_SCRIPT_ZSH = '''# hello-agent zsh completion
#hello-agent completion script for zsh
_hello_agent() {
    local -a subcommands
    subcommands=(chat run serve rag memory tools mcp doctor completion autostart)
    _describe 'subcommand' subcommands
}
compdef _hello_agent hello-agent
'''

_SCRIPT_FISH = '''# hello-agent fish completion
complete -c hello-agent -n "__fish_use_subcommand" -a "chat run serve rag memory tools mcp doctor completion autostart"
'''

_SCRIPT_PWSH = '''# hello-agent PowerShell completion
Register-ArgumentCompleter -Native -CommandName 'hello-agent' -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    @('chat','run','serve','rag','memory','tools','mcp','doctor','completion','autostart') |
        Where-Object { $_ -like "$wordToComplete*" } |
        ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_) }
}
'''


if __name__ == "__main__":
    app()
