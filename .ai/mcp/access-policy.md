# MCP Access Policy

## Principles
- Use least privilege by default.
- No credentials required for `context7` (public docs lookup).
- `serena` operates only within this repository's working directory; it is not given network or
  credential access.
- The `github` MCP/CLI access uses the `RubyFoc` account token; store it only in the local git
  remote/credential config, never in repository files, MCP config, or committed history.
- Store any future API keys (DeepSeek, Sentry) in environment variables or a local, gitignored
  config file — never in repository files or MCP config.

## Required Controls
- Do not add write-capable MCP servers for external services (cloud vector DBs, billing
  providers) without an ADR in `../../docs/architecture/decisions.md`.
- If a future MCP server touches user-uploaded document content, log that explicitly in the
  registry and require explicit approval before enabling it by default.

## Review Cadence
- Re-check `registry.md` whenever a new MCP server is added or an existing one changes scope.
