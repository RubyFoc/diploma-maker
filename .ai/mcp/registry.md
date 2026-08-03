# MCP Registry

Track MCP servers used by this project. Configured in `../../.mcp.json`.

| Name | Purpose | Access | Notes |
| --- | --- | --- | --- |
| context7 | Up-to-date library docs (FastAPI, React, python-docx, LangChain, Qdrant/Pinecone client, Motor/PyMongo) | read-only | `npx -y @upstash/context7-mcp`, no credentials |
| serena | Code navigation/editing via LSP (symbol search, refactors) | read/write on repo files | runs against this project's Python/TypeScript source |
| github | Pull requests, issues, checks | read/write | scoped to `RubyFoc/diploma-maker` via the RubyFoc account token; do not print the token in chat/logs |

No database/storage MCP servers are configured for MongoDB/Qdrant: they are reached only through
the backend application code, not directly from agent tooling, to avoid a write-capable path to
user document data outside the reviewed application layer.

## Onboarding Checklist
- Define least-privilege scopes.
- Document authentication method.
- Add failure and timeout behavior.
- Add audit trail location.
