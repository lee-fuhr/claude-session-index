# Changelog

## v0.2.0 — It looks good now

The output got a proper makeover. Conversations read like conversations. Analytics have visual hierarchy. And you don't have to set anything up anymore.

- **One command to rule them all** — `sessions` replaces the old `session-search` / `session-analyze` / `session-index` trio. Plain text defaults to search: `sessions "webhook debugging"` just works.
- Chat-like conversation display with 🧑/🤖 markers — you can actually tell who said what
- Box-drawing characters for session cards and exchange blocks
- Section headers with emoji in analytics (📊 📈 🔧 💬) for scannable output
- Cleaner search results with ◆ bullets and → resume commands
- Auto-indexing on first use — no more separate `--backfill` step, just run any command and it handles the rest
- Better stats display with visual structure instead of raw JSON
- The old commands still work if you prefer them

## v0.1.0 — Initial release

- Full-text search across all Claude Code sessions (SQLite + FTS5)
- Filter by client, project, tool, agent, tag, date
- Conversation context retrieval from session JSONL files
- Analytics: time per client, tool trends, session frequency, topic analysis
- Cross-session synthesis via Anthropic API (optional dependency)
- Live topic capture via Claude Code hooks (UserPromptSubmit, PreCompact, SessionEnd)
- Background indexing via macOS LaunchAgent
- Claude Code skill for natural language session queries
- Configurable paths via CLI flags, env vars, or config file
