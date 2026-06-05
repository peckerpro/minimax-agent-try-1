"""`hello-agent rag` 鈥?index / query a document collection."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from hello_agent.core.logging import get_logger

app = typer.Typer(help="RAG: index a directory or run a query.")
logger = get_logger(__name__)


@app.command("index")
def index(
    path: str = typer.Argument(..., help="Directory to walk."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", "-r"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Walk a directory, chunk + embed + index all supported files."""
    from hello_agent.rag.index_cli import run_index

    n_files, n_chunks = run_index(Path(path).expanduser().resolve(), recursive=recursive)
    if json_output:
        typer.echo(json.dumps({"indexed_files": n_files, "indexed_chunks": n_chunks}))
    else:
        typer.echo(f"Indexed {n_files} files, {n_chunks} chunks")


@app.command("query")
def query(
    text: str = typer.Argument(..., help="Query text."),
    top_k: int = typer.Option(8, "--top-k", "-k"),
    strategies: str = typer.Option("rewrite,hyde,multi_query,rerank", "--strategies", "-s"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run the 4-strategy retrieval pipeline and print the top results."""
    from hello_agent.core.llm import LLMClient
    from hello_agent.rag.embedder import Embedder
    from hello_agent.rag.retrieval import retrieve
    from hello_agent.rag.vector_store import VectorStore

    embedder = Embedder()
    store = VectorStore()
    llm = LLMClient()
    strat_list = [s.strip() for s in strategies.split(",") if s.strip()]

    try:
        results = retrieve(
            text,
            store,
            embedder,
            llm,
            strategies=strat_list,
            top_k=top_k,
        )
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"query failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(
            json.dumps(
                [
                    {
                        "chunk_id": r.chunk_id,
                        "source": r.source,
                        "score": r.score,
                        "strategy": r.strategy,
                        "text": r.text[:500],
                    }
                    for r in results
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    for r in results:
        typer.echo(f"[{r.score:.3f}] ({r.strategy}) {r.source}")
        typer.echo(f"    {r.text[:200]}")
        typer.echo("")


if __name__ == "__main__":
    app()
