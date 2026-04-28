<!-- claude-setup 2.0.3 2026-04-26 -->
Before writing: check if what you are about to write already exists in the target file (current content provided below if it exists). If already up to date: print "SKIPPED — already up to date" and stop. Write only what is genuinely missing.

Read /stack-0-context for full project info.

## Target: .mcp.json

### Current content — MERGE ONLY, never remove existing entries:
```json
{
  "mcpServers": {
    "code-review-graph": {
      "command": "code-review-graph",
      "args": [
        "serve"
      ],
      "type": "stdio"
    }
  }
}

```

### When to create/update
Add an MCP server if you find ANY of these signals in /stack-0-context:
- Import statement referencing an external service (e.g., pg, mysql2, mongoose, redis, stripe)
- docker-compose service (database, cache, queue, message broker)
- Env var name in .env.example matching a known service pattern (DATABASE_URL, REDIS_URL, STRIPE_KEY, etc.)
- Explicit dependency on an MCP-compatible package
- User mentioned external services during init questions

If ANY evidence is found, create .mcp.json with the corresponding servers.
No evidence = no server. Do not invent services.

### Verified MCP package names — ONLY use these
```
playwright   → @playwright/mcp@latest
postgres     → @modelcontextprotocol/server-postgres
filesystem   → @modelcontextprotocol/server-filesystem
memory       → @modelcontextprotocol/server-memory
github       → @modelcontextprotocol/server-github
brave        → @modelcontextprotocol/server-brave-search
puppeteer    → @modelcontextprotocol/server-puppeteer
slack        → @modelcontextprotocol/server-slack
sqlite       → @modelcontextprotocol/server-sqlite
stripe       → @stripe/mcp@latest
redis        → @modelcontextprotocol/server-redis
mysql        → @benborla29/mcp-server-mysql
mongodb      → mcp-mongo-server
```
If the service is not in this list, print:
`⚠️ UNKNOWN PACKAGE — [service] MCP server not added: package name unverified. Find it at https://github.com/modelcontextprotocol/servers`
Do not add a placeholder. Do not guess.

### OS-correct format (detected: macOS)
**Preferred: use CLI to add (writes to .mcp.json automatically):**
```
claude mcp add --scope project --transport stdio <name> -- npx -y <package>
```
**Or write .mcp.json directly:**
Use: `{ "command": "npx", "args": ["-y", "<package>"] }`
Always include `-y` in npx args to prevent install hangs.
Note: On macOS, Homebrew services run on localhost by default. Check with `brew services list`.

### Connection strings — smart auto-configuration
For each MCP server that needs a connection string:
1. **Check environment first:** If `${VARNAME}` is set in the user's environment, use `"env": { "VAR": "${VAR}" }`
2. **Detect local service:** Run the OS-appropriate check command to see if the service is installed locally
   - PostgreSQL: `command -v psql || brew list postgresql 2>/dev/null`
   - MongoDB: `command -v mongosh || brew list mongodb-community 2>/dev/null`
   - Redis: `command -v redis-cli || brew list redis 2>/dev/null`
   - MySQL: `command -v mysql || brew list mysql 2>/dev/null`
3. **If local service found and env var NOT set:** Use the well-known default URL directly in the env block:
   - PostgreSQL: `postgresql://localhost:5432/postgres`
   - MongoDB: `mongodb://localhost:27017`
   - Redis: `redis://localhost:6379`
   - MySQL: `mysql://root@localhost:3306`
   AND document the var in .env.example with the default value
4. **If neither env var nor local service found:** Use `${VARNAME}` syntax and flag:
   `⚠️ Set VARNAME in your environment or .env file before starting Claude Code`

**NEVER hardcode credentials.** Default localhost URLs are acceptable for dev environments.
After adding any server with env vars, always document them in .env.example.

### Rules
- Produce valid JSON only
- If creating: document every new env var in .env.example
- OS format must match detected OS: macOS

### Channels (Telegram, Discord) — special MCP servers
Channels are MCP servers that push events INTO a session. They require:
- Claude Code v2.1.80+
- claude.ai login (not API key / Console)
- Bun runtime installed
- `--channels` flag at EVERY session launch

Verified channel plugins:
```
Telegram → plugin:telegram@claude-plugins-official
Discord  → plugin:discord@claude-plugins-official
```

If adding a channel-type server, bot tokens must NEVER be hardcoded:
`{ "command": "bun", "args": ["run", "${CLAUDE_PLUGIN_ROOT}/servers/telegram"], "env": { "TELEGRAM_BOT_TOKEN": "${TELEGRAM_BOT_TOKEN}" } }`
After adding, flag: `⚠️ CHANNEL ACTIVATION REQUIRED — launch with: claude --channels plugin:telegram@claude-plugins-official`

### Self-correction fallback
If MCP configuration fails or produces warnings:
1. Read the official MCP documentation: https://modelcontextprotocol.io/introduction
2. Verify the package name against the MCP servers registry: https://github.com/modelcontextprotocol/servers
3. Check the server's README for required env vars and correct args format
4. Re-run `npx claude-setup doctor` to validate the fix
Do NOT leave broken MCP configuration in place — either fix it or remove the entry.

### Output
Created/Updated: ✅ .mcp.json — [what server and evidence source]
Skipped: ⏭ .mcp.json — checked [files], found [nothing], no action
