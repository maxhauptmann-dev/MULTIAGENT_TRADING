<!-- claude-setup 2.0.3 2026-04-26 -->
Before writing: check if what you are about to write already exists in the target file (current content provided below if it exists). If already up to date: print "SKIPPED — already up to date" and stop. Write only what is genuinely missing.

Read /stack-0-context for full project info.

## Target: .claude/settings.json

### Current content — MERGE ONLY, never remove existing hooks:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "code-review-graph update --skip-flows",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "code-review-graph status",
            "timeout": 10
          }
        ]
      }
    ]
  }
}

```

### When to create/update
Add a hook ONLY if it runs on a pattern that repeats every session AND the cost is justified.
Every hook adds overhead on every Claude Code action. Only add if clearly earned.

### CORRECT Claude Code hooks format — USE THIS EXACTLY
The hooks object must be nested inside a top-level `"hooks"` key.
Each event contains an array of matcher objects, each with its own `"hooks"` array.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "<shell command here>"
          }
        ]
      }
    ]
  }
}
```

**WRONG formats (do NOT use):**
- `"hooks": { "post-edit": ["mvn compile"] }` — INVALID event name and structure
- `"PostToolUse": [{ "command": "bash", "args": [...] }]` — missing top-level "hooks" key
- `{ "command": "cmd", "args": ["/c", "..."] }` — old format, must use "type": "command"

### Valid hook event names — use ONLY these
`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SessionStart`,
`Notification`, `UserPromptSubmit`, `PermissionRequest`, `ConfigChange`,
`SubagentStart`, `SubagentStop`, `SessionEnd`

### Matcher patterns
- `"Edit|Write"` — fires only on file edits
- `"Bash"` — fires only on shell commands
- `""` (empty) — fires on all occurrences of the event

### BUG 8 FIX: Verify build tools exist BEFORE adding hooks
Before adding any hook that runs a build tool, verify it is installed:
```
command -v mvn && mvn compile -q
command -v gradle && gradle build
command -v npm && npm run build
```
If the tool is NOT installed:
- Wrap the command with an existence check: `command -v mvn && mvn compile -q`
- OR skip the hook and print: `⚠️ SKIPPED mvn hook — Maven not found. Install Maven first.`
- NEVER add a hook for a tool that doesn't exist on the system

### Rules
- **NEVER write a "model" key into settings.json** — it overrides the user's model selection silently
- If it exists above: audit quoting of existing hooks first, fix broken ones
- Only add hooks for patterns that genuinely recur for this project type
- Produce valid JSON only
- The `"type"` field in each hook must be one of: `"command"`, `"prompt"`, `"agent"`, `"http"`

### Output
Created/Updated: ✅ settings.json — [hook name and justification]
Skipped: ⏭ settings.json — [why no hooks warranted]
