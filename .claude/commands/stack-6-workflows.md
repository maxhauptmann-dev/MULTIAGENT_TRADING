<!-- claude-setup 2.0.3 2026-04-26 -->
## Target: .github/workflows/
.github/ exists: no
Installed: none

### .github/ does not exist — scan for CI/CD evidence before skipping

The absence of .github/ is an opportunity to suggest, not a reason to stop.

Scan /stack-0-context for CI/CD evidence:
- `tests/` or `__tests__/` or `spec/` directory → test pipeline candidate
- `Dockerfile` or `docker-compose.yml` → build + deploy pipeline candidate
- `package.json` with build/test/lint scripts → Node CI candidate
- `Makefile` with test/build/deploy targets → generic CI candidate
- `pyproject.toml` with test config → Python CI candidate
- README references to "deploy", "release", "staging", "production"

If evidence found, print EXACTLY:
```
⚙️  WORKFLOW SUGGESTION — .github/ does not exist

Evidence that CI/CD would be useful:
  [list each piece of evidence and its source]

I can set up:
  1. CI pipeline     — run tests + build on every push
  2. Deploy pipeline — build image + push to registry on merge to main
  3. Both

Two questions before I create anything:
  1. Which of the above? (1 / 2 / 3 / none)
  2. Is this connected to a remote GitHub repository? (yes / no)
```

If user confirms: create .github/workflows/ with workflows based on actual project commands.
All secrets must use `${{ secrets.VARNAME }}` syntax — never hardcoded.
After writing, flag every secret: `⚠️ Add [VARNAME] to GitHub Settings → Secrets`

If NO evidence found:
Skipped: ⏭ .github/workflows/ — scanned: no tests dir, no Dockerfile, no build/deploy scripts, no deployment references. Nothing to automate.
