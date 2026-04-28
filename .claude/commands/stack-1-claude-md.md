<!-- claude-setup 2.0.3 2026-04-26 -->
Before writing: check if what you are about to write already exists in the target file (current content provided below if it exists). If already up to date: print "SKIPPED — already up to date" and stop. Write only what is genuinely missing.

Read /stack-0-context for full project info.

## Target: CLAUDE.md

### Current content — APPEND ONLY, never rewrite, never remove:
```
<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

```

### What to write
CLAUDE.md is the most valuable artifact. Make it specific to THIS project:
- **Purpose**: one sentence describing what this project does
- **Runtime**: language, framework, key dependencies from /stack-0-context
- **Key dirs**: reference actual directory paths from the project tree
- **Run/test/build commands**: extract from scripts in /stack-0-context
- **Non-obvious conventions**: patterns you see in the source samples

### Rules
- Every line must reference something you actually saw in /stack-0-context
- No generic boilerplate. Two different projects must produce two different CLAUDE.md files
- If it exists above: read it fully, add only what is genuinely missing

### Output
Created/Updated: ✅ CLAUDE.md — [one clause: what you wrote and why]
Skipped: ⏭ CLAUDE.md — [why not needed]
