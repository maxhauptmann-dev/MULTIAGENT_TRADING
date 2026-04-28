<!-- claude-setup 2.0.3 2026-04-26 -->
Before writing: check if what you are about to write already exists in the target file (current content provided below if it exists). If already up to date: print "SKIPPED — already up to date" and stop. Write only what is genuinely missing.

Read /stack-0-context for full project info.

## Target: .claude/skills/
Installed: .claude/skills/review-changes.md, .claude/skills/refactor-safely.md, .claude/skills/explore-codebase.md, .claude/skills/debug-issue.md

### When to create
Create a skill if:
- A recurring multi-step project-specific pattern exists in /stack-0-context
- The project type has standard workflows worth automating (build, deploy, test patterns)
- It will save time across multiple Claude Code sessions

### Correct skill file format
Skills must be created as `.claude/skills/<skill-name>/SKILL.md` with YAML frontmatter:

```yaml
---
name: skill-name
description: What this skill does and when to use it
---

Skill instructions here...
```

Optional frontmatter fields:
- `disable-model-invocation: true` — only user can invoke (for commands with side effects)
- `allowed-tools: Read, Grep` — restrict which tools the skill can use
- `context: fork` — run in isolated subagent
- `agent: Explore` — which agent type to use with context: fork

### Project-specific skills to consider
Based on what you see in /stack-0-context, consider creating skills for:
- Build/deploy workflows specific to this stack
- Code review patterns specific to this codebase
- Database migration patterns if migration files exist
- Testing patterns if test infrastructure exists

### Rules
- Use `description:` frontmatter so Claude knows when to load the skill
- If a similar skill already exists above: extend it, don't create a parallel one
- Empty is valid — no skills is better than useless skills
- Each skill directory MUST contain a SKILL.md file

### Output
Created: ✅ .claude/skills/[name]/SKILL.md — [what pattern it captures]
Skipped: ⏭ skills — checked [patterns], found [nothing project-specific]
