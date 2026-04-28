<!-- claude-setup 2.0.3 2026-04-26 -->
Before writing: check if what you are about to write already exists in the target file (current content provided below if it exists). If already up to date: print "SKIPPED — already up to date" and stop. Write only what is genuinely missing.

Read /stack-0-context for full project info.

## Target: .claude/commands/ (excluding stack-*.md — those are setup artifacts)
Installed: none

### When to create
Create a command ONLY for project-specific multi-step workflows a developer repeats.
Do NOT create commands for things expressible as a single shell alias.

### Smart environment detection
Also scan for missing/incomplete environment setup:
- `.env.example` exists but `.env` missing → suggest `/setup-env`
- `docker-compose.yml` with `depends_on` → suggest `/up` with correct startup order
- Database migration files (`migrations/`, `prisma/schema.prisma`, `alembic/`) → suggest `/db:migrate`, `/db:rollback`
- `package.json` with `"prepare"` or `"postinstall"` hooks → suggest `/install`
- `Makefile` with `install`, `deps`, `bootstrap` → fold into `/init`
- README sections ("Environment Variables", "Database Setup") → each can become a command

All suggestions must be built from actual project files — never assume fixed commands.
Detect the real tooling (npm vs yarn vs pnpm, docker compose vs docker-compose) from project evidence.

### REQUIRED: Scan for multi-step patterns before deciding
You MUST actively scan these sources in /stack-0-context:
- **Makefile targets**: multiple chained commands under one target
- **package.json scripts**: chained commands with && or ;
- **docker-compose.yml**: service dependencies implying a boot order
- **Dockerfile**: multi-stage patterns implying a build sequence
- **README.md / docs**: sections like "Getting Started", "How to run"
- **Shell scripts** in /scripts or /bin
- **.env.example**: many vars suggest a setup sequence

### Pattern signatures to detect
| Pattern found | Suggested command |
|---------------|-------------------|
| docker-compose down + volume removal + build + up | /clean-rebuild |
| migrate + seed + start | /fresh-start |
| build + test + deploy | /release |
| lint + format + typecheck all separate | /check |
| setup + install + configure in README or scripts | /init |
| backup/restore scripts or pg_dump/mongodump | /db:backup, /db:restore |
| test + test:watch + test:coverage | /test |
| dev + start + debug in package.json | /dev |
| >2 manual steps in README "how to run" | candidate for /start |

For each pattern found, suggest to the user:
```
## Suggested command: /[name]

I found a multi-step pattern in [source]:
  1. [step]
  2. [step]

Create .claude/commands/[name].md?
```

### Rules
- If existing commands cover the same workflow: skip
- Commands should be specific to this project, not generic
- Adapt exact commands from actual project files — never hardcode
- Never skip with a blanket "no workflows found" without scanning all sources above

### Output
Created: ✅ .claude/commands/[name].md — [what workflow and why useful]
Skipped: ⏭ commands — scanned [list each source checked and result]. Nothing warranted.
