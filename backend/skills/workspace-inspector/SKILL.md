---
name: workspace-inspector
description: Inspect and understand files in the configured Skills workspace. Use when the user asks to explore a codebase, locate text, understand project structure, or summarize workspace contents.
---

# Workspace Inspector

Use the restricted workspace tools to inspect files safely and efficiently.

## Workflow

1. Start with `list_files` or `glob_files` to understand the relevant structure.
2. Use `grep` to narrow down symbols, phrases, configuration keys, or TODOs.
3. Use `read_file` only for files that are relevant to the user's question.
4. Prefer read-only inspection. Do not call `write_file`, `edit_file`, or `bash` unless the user explicitly asks for a change or command execution.
5. Never attempt to leave the configured Skills workspace.

## Output

Summarize the findings directly. When useful, include the relevant workspace-relative file paths and line context. If the requested information is not present, say so instead of guessing.
