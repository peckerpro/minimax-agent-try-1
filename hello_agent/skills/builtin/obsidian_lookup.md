---
name: obsidian_lookup
description: Search the Obsidian vault for notes related to a topic.
version: 0.1.0
author: hello-agent
license: MIT
platforms:
 - windows
 - linux
 - macos
tags:
 - obsidian
 - memory
 - search
 - rag
category: memory
triggers:
 regex:
 - "(?i)\\bsearch\\s+(?:my\\s+)?obsidian\\s+(?:for|about)\\b"
 - "(?i)\\b(?:find|lookup)\\s+(?:related\\s+)?notes?\\s+(?:in|from)\\s+(?:my\\s+)?obsidian\\b"
 - "(?i)\\bwhat\\s+(?:notes|have\\s+i\\s+written)\\s+(?:do\\s+i\\s+have\\s+)?(?:about|on)\\b"
 keywords:
 - obsidian_lookup
 - obsidian search
 - find notes
 - search vault
tools:
 - file_tools.read_file
 - shell_tool.run_powershell
 - rag.query
inputs:
 obsidian_vault:
 type: string
 description: Absolute path to the Obsidian vault root.
 query:
 type: string
 description: Free-text query to search for.
 max_results:
 type: integer
 description: Maximum number of notes to return (default10).
 include_folders:
 type: array
 description: Optional whitelist of folders to search; defaults to vault-wide.
outputs:
 matches:
 type: array
 description: List of {path, title, snippet, score} records.
 total_candidates:
 type: integer
 description: Number of notes scanned.
---

# obsidian_lookup

Search the user's Obsidian vault for notes matching a free-text query.
Returns the top-N hits with snippets and relevance scores.

Built on top of the existing RAG pipeline (`rag.query`) — the difference
is that the source corpus is the user's vault, not a project-specific
index. This is the v0.2 Day7 bundled skill.

## When to Use

- The user says "search my Obsidian for …", "find notes about …",
 "what do I have on …?".
- The user is writing a new note and wants to surface related prior work.
- The user wants a quick re-read of an existing topic without opening
 Obsidian manually.

## Prerequisites

- The Obsidian vault path is configured (`config.yaml` → `obsidian.vault`).
- The vault contains at least one `.md` file (else nothing to search).
- For best results, the vault has been indexed by `hello-agent rag index
 <vault>` — the index lives at `<vault>/.hello_agent_rag/` and is
 re-used by this skill.

## How to Run

```
hello-agent chat "/obsidian_lookup my MCP experiments"
hello-agent chat "/obsidian_lookup --max5 hello-agent skills"
```

## Quick Reference

| Field | Value |
| --- | --- |
| Primary tools | `rag.query`, `file_tools.read_file`, `shell_tool.run_powershell` |
| Confirmation | not required (read-only) |
| Side effects | none (read-only); may rebuild the rag index if stale |
| Reversible | yes — no writes |

## Procedure

1. **Resolve the vault path.** Read `~/.hello_agent/config.yaml` →
 `obsidian.vault`. If unset, ask the user.

2. **Check for an existing index.** Look for
 `<vault>/.hello_agent_rag/chroma.sqlite3`. If present, use it
 directly. If absent, offer to run `hello-agent rag index <vault>` in
 the background (or inline if the vault is small — <1000 notes).

3. **Run the query** via `rag.query(query, top_k=max_results or10)` with
 the multi-strategy pipeline (`rewrite,hyde,multi_query,rerank`).

4. **For each result, fetch a snippet.** Read the first ~500 chars after
 the H1 heading of the matched note. Strip YAML frontmatter. Keep
 code blocks intact.

5. **Format the response** as a numbered list:

 ```
1. **<note title>** (score0.82) — <vault-relative path>
 > <snippet, max200 chars>
2. ...
 ```

 Include the source path (relative to vault) and the absolute path so
 the user can click through.

6. **Suggest related actions:**
 - "Open in Obsidian: obsidian://open?path=…"
 - "Backlinks: <list of notes that link TO this one>"
 - "Read full note: /file_organize …" (no — that's the wrong skill —
 instead just `/read_file <absolute path>` or `hello-agent run
 "summarize <path>"`)

7. **If no results**, suggest:
 - Rephrasing the query (try shorter keywords).
 - Indexing more folders (`--include_folders`).
 - Checking the spelling of proper nouns.

## Examples

**Trigger**: `hello-agent chat "/obsidian_lookup hello-agent skills"`

**Output**:
```
Found4 matches in D:\Notes (scanned1,237 notes):

1. **Day7 Skills Plan** (score0.91) — Projects/hello-agent/Day7.md
 > Day7 plan: SKILL.md loader + registry +3 builtins…

2. **Skills frontmatter spec** (score0.84) — Reference/skills.md
 > SKILL.md frontmatter: name, description, triggers, tools, inputs, outputs…

3. **Hermes skill_commands** (score0.78) — Reference/hermes.md
 > Borrow from hermes agent/skill_commands.py — scans ~/.hermes/skills/…

4. **SKILL.md examples** (score0.71) — Examples/skills.md
 > file_organize.md, daily_review.md, obsidian_lookup.md…
```

## Constraints

- **NEVER** modify any file in the vault (read-only skill).
- **NEVER** return snippets longer than200 chars (avoid context bloat).
- **NEVER** include notes that match the exclude patterns
 (`Daily Reviews/*.md`, `Templates/*.md`, `*.excalidraw.md`) by default.
- **NEVER** expose notes that contain a `private: true` frontmatter tag.
- **NEVER** index the `.obsidian/` config dir, `.trash/`, or any folder
 starting with `.`.
- If the vault has >10,000 notes, require explicit confirmation before
 indexing (slow).

## Verification

- Every result path actually exists.
- Every snippet came from the file at the claimed path (sanity check
 the first50 chars match).
- Scores are monotonically decreasing.

## Related Skills

- `daily_review` — uses obsidian_lookup when composing "Highlights" to
 find related notes from prior days.
- `file_organize` — does not directly call obsidian_lookup but the
 user's organized files can be summarized via a chain that starts
 here.
