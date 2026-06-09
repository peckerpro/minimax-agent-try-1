"""hello-agent-2 examples — small, focused walkthroughs of the public API.

Each `NN_*.py` file in this directory is a runnable script that demonstrates
one feature of `hello_agent`. Run an example with:

    uv run python examples/01_quick_chat.py                # real LLM call
    uv run python examples/01_quick_chat.py --self-test    # offline smoke

The `--self-test` flag exists on every example so the test suite can
`subprocess.run` them safely. In self-test mode the example exercises
the relevant code paths without network / LLM API calls and exits 0
on success.

The five examples:

  01_quick_chat.py        LLMClient + SimpleAgent.chat("hello")
  02_react_with_tools.py  ReActAgent + file_tools.read_file round-trip
  03_rag_index_and_query.py  walk + chunk + embed + 4-strategy retrieve
  04_obsidian_export.py   LongTermMemory.add_fact + ObsidianSync.export_memory
  05_mcp_round_trip.py    spawn hello-agent as MCP server, connect from MCPClient
"""