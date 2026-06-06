"""Long-term + short-term + episodic + Obsidian/Git sync memory.

Submodules (Day-4 spec, ENGINEERING.md §6.6):

- `short_term`  in-conversation scratchpad (HistoryManager + fact dict)
- `long_term`   SQLite-backed fact store (facts table)
- `episodic`    SQLite-backed session-summary log (episodes table)
- `obsidian_sync`  + `git_sync`  deferred to §7.3 (post-Day-4)

Submodules are lazily imported by their consumers. We do NOT eagerly
import the SQLite-backed modules here, because that would force
`hello-agent doctor` to open a database file on every invocation.
"""

from __future__ import annotations
