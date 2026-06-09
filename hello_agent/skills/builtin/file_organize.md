---
name: file_organize
description: Categorize files in a folder and move them into groups.
version: 0.1.0
author: hello-agent
license: MIT
platforms:
  - windows
  - linux
  - macos
tags:
  - files
  - productivity
category: productivity
triggers:
  regex:
    - "(?i)\\borganize\\s+(?:my\\s+)?(?:files|folder|downloads?|desktop)\\b"
    - "(?i)\\bclean\\s+up\\s+(?:my\\s+)?(?:folder|downloads?)\\b"
    - "(?i)\\bsort\\s+(?:my\\s+)?(?:files|folder)\\b"
  keywords:
    - file_organize
    - organize files
    - organize folder
    - clean up downloads
tools:
  - file_tools.read_file
  - file_tools.write_file
  - file_tools.list_dir
inputs:
  folder_path:
    type: string
    description: Absolute path to the folder to organize.
  categories:
    type: object
    description: "Optional mapping of {category_name -> regex_or_glob_pattern}."
outputs:
  categorized:
    type: array
    description: List of src_path, category, suggested_dest records.
  moves_performed:
    type: integer
    description: Number of files actually moved after confirmation.
---

# file_organize

Categorize the files in a folder into logical groups and (optionally) move
them into subfolders. Designed for "I just downloaded 50 things and now my
Downloads folder is a disaster."

## When to Use

- User says "organize my Downloads", "clean up my desktop", "sort these files"
- A folder has 20+ unsorted files spanning multiple categories
- User wants a *proposal* first (dry-run) before any file is moved

Do NOT use this for: deleting duplicates (out of scope), renaming files
intelligently (out of scope), sorting photos by EXIF date (use a dedicated
photo tool).

## Prerequisites

- The folder must be readable (hello-agent has read_file permission on it)
- If the user wants files moved, write_file permission must be granted for
  the target folders
- For files > 1 MB, prefer `shell_tool.run_powershell` `Move-Item` over
  read+write (faster, preserves timestamps)

## How to Run

1. **Scan** the folder. Use `shell_tool.run_powershell` to list files:
   `Get-ChildItem -Path "folder" -File | Select-Object Name, Extension, Length, LastWriteTime`
2. **Categorize** each file by extension + name patterns:

   | Group        | Extensions                            | Examples             |
   |--------------|---------------------------------------|----------------------|
   | Documents    | .pdf .doc .docx .txt .md .rtf .odt    | report.pdf, notes.md |
   | Images       | .jpg .jpeg .png .gif .webp .svg .bmp  | photo.jpg, logo.png  |
   | Code         | .py .js .ts .tsx .jsx .go .rs .java .c .cpp .h .sh .ps1 | app.py, main.go |
   | Archives     | .zip .tar .gz .7z .rar .bz2 .xz       | backup.zip           |
   | Spreadsheets | .xlsx .csv .tsv .xls .ods             | data.csv             |
   | Audio        | .mp3 .wav .flac .ogg .m4a .aac        | song.mp3             |
   | Video        | .mp4 .mkv .mov .avi .webm             | clip.mp4             |
   | Installers   | .exe .msi .dmg .pkg .deb .rpm .AppImage | setup.exe           |
   | Misc         | (anything that does not match)         | random.bin           |

3. **Propose moves** as a JSON list. Show the user a summary:
   `Documents: 12, Images: 8, Code: 3, Misc: 2 (15 files already in place)`
4. **Confirm** with the user before any actual file movement. Always
   present the plan first; if `dry_run` is true (the default), stop here.
5. **Execute** (only after explicit confirmation). Use `Move-Item -Path
   "src" -Destination "dest"` via `shell_tool.run_powershell` so
   timestamps are preserved. Create destination folders with
   `New-Item -ItemType Directory -Force`.

## Procedure

1. Read the user's prompt and extract the target folder path. If absent,
   ask. Default to the user's `Downloads` folder if the prompt is ambiguous.
2. List the folder's files (excluding hidden files and subfolders).
3. Build a categorization plan. Group by the table above.
4. **Emit a plan summary** (always, before any move):

   ```
   Plan for folder (47 files):
     Documents/    12 files
     Images/        8 files
     Code/          3 files
     Archives/      2 files
     Misc/          2 files
     (20 files already in correct group folders)
   ```

5. Ask: "Should I execute this plan? (yes / adjust / cancel)"
6. On `yes`: execute moves in order, then print a completion summary.
7. On `adjust`: ask what to change (e.g. "merge Misc into Documents").
8. On `cancel`: stop, report no changes.

## Examples

**Example 1** — Dry-run scan

> User: "organize my Downloads folder"
>
> Agent scans `C:\Users\me\Downloads`, produces a plan with 47 files split
> into Documents (12), Images (8), Code (3), Archives (2), Misc (2),
> prints the plan, and stops. No file is moved.

**Example 2** — Execute after confirmation

> User: "organize my Downloads, yes go ahead"
>
> Agent runs the same scan, prints the plan, then (because the user
> already said "yes go ahead") executes the moves and reports:
> "Moved 20 files. Skipped 27 (already in correct location). No errors."

**Example 3** — Adjust and re-plan

> User: "merge Misc into Documents"
>
> Agent re-emits the plan with Misc merged into Documents and waits for
> confirmation.

## Constraints

- **Always** show the plan before moving. Never move without confirmation.
- **Never** delete files. This skill organizes; it does not clean.
- **Never** overwrite a same-named file. If `dest/foo.pdf` already
  exists, append ` (1)`, ` (2)`, etc. and warn the user.
- **Respect** the user's permission settings. If `file_tools.write_file`
  is disabled for the target folder, report the permission gap and stop.
- **Log** every move to the observability layer (already automatic via
  the tool registry).
- **Skip** hidden files (`.something`) and system files (`Thumbs.db`,
  `.DS_Store`, `desktop.ini`) — leave them in place.
- **Cap** the categorization table at 1000 files; if a folder has more,
  ask the user to confirm the full scan before proceeding.
- **NEVER** operate on system folders (`C:\Windows`, `C:\Program Files`,
  `/usr`, `/etc`, `/var`) or on the hello-agent home itself.
