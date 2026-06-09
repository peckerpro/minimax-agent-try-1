---
name: daily_review
description: Summarize the day's sessions and write the review to Obsidian.
version: 0.1.0
author: hello-agent
license: MIT
platforms:
 - windows
 - linux
 - macos
tags:
 - memory
 - obsidian
 - review
 - productivity
category: memory
triggers:
 regex:
 - "(?i)\\b(?:daily|end[\\s-]of[\\s-]day)\\s+review\\b"
 - "(?i)\\brecap\\s+(?:my\\s+)?(?:day|sessions?)\\b"
 - "(?i)\\bwhat\\s+did\\s+i\\s+do\\s+(?:today|this\\s+(?:day|week))\\b"
 keywords:
 - daily_review
 - end of day
 - daily review
 - recap today
tools:
 - memory.search_long_term
 - memory.search_episodic
 - file_tools.read_file
 - file_tools.write_file
 - shell_tool.run_powershell
inputs:
 obsidian_vault:
 type: string
 description: Absolute path to the Obsidian vault root.
 date:
 type: string
 description: ISO date (YYYY-MM-DD) to review. Defaults to today.
 sessions:
 type: array
 description: Optional list of session_ids to include; defaults to all today's sessions.
outputs:
 review_path:
 type: string
 description: Absolute path to the written Obsidian review note.
 summary:
 type: string
 description: The short summary text (markdown).
---

# daily_review

Walk through every chat session from the given date, summarize what was
done, and write a markdown review note to the user's Obsidian vault.

This is the v0.2 Day7 bundled skill — it composes `memory`,
`file_tools`, and `shell_tool` (for Obsidian-side effects) into a
single end-of-day workflow.

## When to Use

- The user says "give me my daily review", "end of day recap", "what did
 I do today?".
- It's the end of the workday and the user wants to write a wrap-up note.
- The user has set `obsidian_vault` in their config (so we know where to
 write).

## Prerequisites

- The Obsidian vault path is configured (`config.yaml` →
 `obsidian.vault` or `inputs.obsidian_vault`).
- The folder `Daily Reviews/` exists in the vault (or `daily_review` will
 create it on first write).
- Sessions have been recorded — i.e. the agent has been used today.

## How to Run

```
hello-agent chat "/daily_review"
hello-agent chat "/daily_review --date2026-06-08"
hello-agent chat "/daily_review --vault D:\\Notes"
```

## Quick Reference

| Field | Value |
| --- | --- |
| Primary tools | `memory.search_episodic`, `file_tools.read_file`, `file_tools.write_file` |
| Confirmation | required (`write_file` to Obsidian is dangerous) |
| Side effects | creates/updates `Daily Reviews/YYYY-MM-DD.md` in Obsidian vault |
| Reversible | yes — delete the file, or restore from git if the vault is versioned |

## Procedure

1. **Resolve the date and vault.** If the user didn't pass them, read
 `~/.hello_agent/config.yaml` for `obsidian.vault` and default to today
 in the user's local timezone.

2. **List today's sessions** by querying the session database
 (`memory.list_sessions(date=...)` or `sqlite` direct query against
 `~/.hello_agent/state.db` sessions table). If the user passed
 `inputs.sessions`, use that list verbatim.

3. **For each session**, call `memory.search_episodic(session_id=...)`
 to retrieve the episode summary, then `file_tools.read_file` against
 `~/.hello_agent/sessions/<session_id>.jsonl` for the full message log.

4. **Synthesize per-session summaries.** For each session produce:
 - **Goal** — what the user wanted at the start.
 - **Actions** — what tools were called, what files changed.
 - **Outcome** — final assistant reply, files created, decisions made.
 - **Open threads** — anything the user said "let's come back to" or
 that the assistant flagged as unresolved.

5. **Compose the day summary** as markdown with sections:
 - `# Daily Review — YYYY-MM-DD`
 - `## Stats` — session count, total tokens, total cost (if available).
 - `## Sessions` — one `###` block per session with the4 fields above.
 - `## Highlights` —3-5 bullets of the most important outcomes.
 - `## Follow-ups` — bullets pulled from the open-threads section.
 - `## Tags` — auto-derived from session topics (e.g. `#refactor`,
 `#hello-agent`, `#mcp`).

6. **Write to Obsidian.** Path:
 `<vault>/Daily Reviews/YYYY-MM-DD.md`. If a note for that date
 already exists, append `## Update (HH:MM)` below the existing content
 (preserves the original).

7. **Report back** to the user with:
 - The path to the written note.
 - The summary stats (sessions, tokens, cost).
 - The first200 chars of the highlights section.

## Examples

**Trigger**: `hello-agent chat "/daily_review"`

**Output**:
```
Wrote daily review to D:\Notes\Daily Reviews\2026-06-08.md
Sessions:4
Tokens:12,340 (input) /8,910 (output)
Top highlight: Refactored hello-agent skills loader to drop unused imports.
```

**Note contents** (excerpt):
```markdown
# Daily Review —2026-06-08

## Stats
- Sessions:4
- Tokens:21,250 total
- Cost: $0.34

## Sessions
### session7c1a... — "Refactor skills loader"
- **Goal**: drop unused imports per ruff F401
- **Actions**: edited hello_agent/skills/loader.py, ran ruff, committed
- **Outcome**: ruff clean,312 tests still green
- **Open threads**: tighten the SkillFrontmatter validator (next day)

## Highlights
- Refactored hello-agent skills loader — ruff clean
- Wrote3 builtin SKILL.md files
- Day7 commit landed on wt/e5bdcb08

## Follow-ups
- Tighten SkillFrontmatter validator (Day8 candidate)

## Tags
#hello-agent #skills #refactor #day-7
```

## Constraints

- **NEVER** delete an existing daily-review note — only append.
- **NEVER** include raw message content in the note (privacy); only
 metadata + summaries.
- **NEVER** include API keys, file paths under `~/.ssh`, or any content
 matching `BEGIN ... PRIVATE KEY` patterns.
- **NEVER** write outside the configured Obsidian vault without
 explicit user confirmation.
- **NEVER** run for dates more than7 days in the past without an
 explicit `--historical` flag (it bloats the session DB query).
- If `obsidian_vault` is unset, ask the user before failing — do NOT
 guess a default.

## Verification

- The output file exists at the expected path.
- The file parses as valid markdown (frontmatter is optional).
- The session count in the `## Stats` section matches the sessions
 actually walked.
- The user can open the file in Obsidian without errors.

## Related Skills

- `file_organize` — daily_review may invoke it on `~/Downloads` as a
 cleanup step.
- `obsidian_lookup` — daily_review can use it to find related notes from
 previous days when composing "Highlights".
