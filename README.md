# Claude session index

**Every Claude Code session you've ever had, searchable in under a second.**

You've built things across hundreds of sessions. Solved problems, hit walls, found workarounds. But sessions disappear into `~/.claude/projects/` as unlabeled JSONL files — thousands of them, unsearchable, forgettable. This tool indexes them all into a fast SQLite database with full-text search, conversation retrieval, analytics, and cross-session synthesis.

Ask "what did I try last time I debugged webhooks?" and get an actual answer.

---

## What it does

1. **Indexes** all your Claude Code sessions into SQLite with FTS5 full-text search
2. **Searches** by content, client, project, tool, agent, tag, or date — results in milliseconds
3. **Retrieves context** — read actual conversation exchanges (user + assistant), not just metadata
4. **Analyzes** your usage — time per client, tool trends, session frequency, topic patterns
5. **Synthesizes** across sessions — "What approaches have I tried for X?" via Haiku (optional)
6. **Tracks topics** live during sessions via Claude Code hooks

## Quick start

```bash
pip install claude-session-index

# Index all your existing sessions (one-time backfill)
session-index --backfill

# Search for anything
session-search search "webhook debugging"

# See your analytics
session-analyze analytics --week
```

That's it. Your sessions are now searchable.

---

## Search

Full-text search across every user message in every session.

```bash
# Search by content
session-search search "deployment pipeline"

# Filter by project, client, tool, date
session-search find --client "Acme Corp" --week
session-search find --tool "Task" --project "my-app"

# Recent sessions
session-search recent 20

# Show conversation context inline with results
session-search search "auth bug" --context
```

**Output:**
```
3 results for "webhook debugging":

  a1b2c3d4  >>> API integration fixes [webhook, debug]
           2026-01-15 · my-app · 42 exchanges · 87min
           "...the webhook wasn't firing because the endpoint URL had a trailing slash..."
           topics: Webhook setup → Retry logic → Edge case fix
           claude --resume a1b2c3d4-full-session-id-here
```

Each result shows the session title, metadata, matching snippet, topic timeline, and a ready-to-copy `claude --resume` command.

## Conversation context

Read the actual conversation from any session — not just metadata, but what was said.

```bash
# Show exchanges matching a term
session-analyze context a1b2c3d4 "retry logic"

# Show all exchanges
session-analyze context a1b2c3d4
```

**Output:**
```
Session: API integration fixes
  2026-01-15 · my-app · 42 exchanges · 87min

Matching exchanges for "retry logic":

── Exchange 14 2026-01-15T10:42 ──
  User: The webhook fires but sometimes the receiver returns 503...
  Assistant: Let's add exponential backoff retry logic...
  [Edit: src/webhooks/sender.py (added retry decorator)]
```

Tool calls are collapsed into readable one-liners: `[Read: path]`, `[Edit: path]`, `[Bash: command]`, `[Task: "description" → agent]`.

## Analytics

Understand how you spend your time. Pure SQL — no API calls, no cost.

```bash
session-analyze analytics              # all time
session-analyze analytics --week       # this week
session-analyze analytics --month      # this month
session-analyze analytics --client X   # specific client
session-analyze analytics --project X  # specific project
```

**Output:**
```
Session analytics (this week)
==================================================

  42 sessions · 18.3h total · avg 26min/session · avg 31 exchanges

Time per client:
  Acme Corp                   12 sessions   6.2h  avg 45 exchanges
  Internal                     8 sessions   3.1h  avg 22 exchanges

Daily trend (last 14 days):
  2026-01-20    8 sessions   3.2h  ████████████████
  2026-01-21   12 sessions   4.8h  ████████████████████████
  2026-01-22    6 sessions   2.1h  ██████████

Top tools:
  Read                          312 uses  (38 sessions)
  Edit                          245 uses  (32 sessions)
  Bash                          189 uses  (28 sessions)

Tool trends (this week vs last):
  Task                          45 (was    22)  ↑ 105%
  WebSearch                     12 (was     3)  ↑ 300%
```

## Cross-session synthesis

The most powerful feature. Ask a question, get a synthesized answer from across all your sessions.

```bash
session-analyze synthesize "webhook error handling"
session-analyze synthesize "database migration patterns" --limit 5
```

This searches your sessions, extracts relevant conversation exchanges, and sends them to Claude Haiku for synthesis. Requires the `anthropic` package and an API key:

```bash
pip install claude-session-index[synthesis]
export ANTHROPIC_API_KEY=sk-...
```

**If you're already in a Claude Code session**, you can skip the API cost entirely. Use `/qq-search analyze "topic"` and Claude will search, extract, and synthesize using an in-session Haiku subagent — no external API call needed.

---

## Live topic tracking

Capture what you're working on during sessions via Claude Code hooks. Topics appear in your statusLine and get indexed for search.

### Setup hooks

Add to `~/.claude/settings.json` (or merge with your existing hooks):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "session-topic-capture UserPromptSubmit"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "session-topic-capture PreCompact"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "session-topic-capture SessionEnd"
          }
        ]
      }
    ]
  }
}
```

Topics are captured:
- **Every 10 exchanges** during a session (periodic)
- **Before compaction** (last chance before context is summarized)
- **At session end** (final topic + full re-index)

### Background indexing (macOS)

Keep the index fresh automatically:

```bash
cp launchagent/com.session-indexer.plist ~/Library/LaunchAgents/
# Edit the plist to point to your Python path
launchctl load ~/Library/LaunchAgents/com.session-indexer.plist
```

Runs `session-index --incremental` every 30 minutes. Only processes new or modified sessions.

---

## Claude Code skill

For natural language access within Claude Code sessions, install as a skill:

```bash
# From your project directory
cp skill/SKILL.md .claude/skills/session-index.md
```

Then ask Claude things like:
- "Search my sessions for webhook debugging"
- "Show me analytics for this week"
- "What have I tried for database migrations?"

---

## Configuration

Works out of the box with sensible defaults. All paths are configurable.

### Priority order

1. CLI flags (`--db-path`, `--projects-dir`)
2. Environment variables (`SESSION_INDEX_DB`, `SESSION_INDEX_PROJECTS`, `SESSION_INDEX_TOPICS`)
3. Config file (`~/.session-index/config.json`)
4. Defaults

### Default paths

| What | Default location |
|------|-----------------|
| Database | `~/.session-index/sessions.db` |
| Sessions | `~/.claude/projects/` |
| Topics | `~/.claude/session-topics/` |
| Config | `~/.session-index/config.json` |

### Optional config file

```json
{
  "projects_dir": "~/.claude/projects",
  "db_path": "~/.session-index/sessions.db",
  "topics_dir": "~/.claude/session-topics",
  "clients": ["Acme Corp", "Internal"],
  "project_names": {
    "-Users-me-projects-myapp": "My App"
  }
}
```

- **`clients`** — Optional. If provided, sessions are auto-tagged with matching client names. If empty, client detection is skipped.
- **`project_names`** — Optional. Maps Claude's directory-based project names to friendly labels. If empty, auto-generates from directory names.

---

## How it works

```
~/.claude/projects/          session-index              Your queries
  ├── -project-a/              ┌──────────┐
  │   ├── abc123.jsonl ──────▶│ SQLite   │◀──── session-search search "X"
  │   └── def456.jsonl ──────▶│ + FTS5   │◀──── session-analyze analytics
  ├── -project-b/              └──────────┘◀──── session-analyze context ID
  │   └── ghi789.jsonl ──────▶     │
  └── ...                          │
                                   ▼
                            sessions.db
                          ┌─────────────────┐
                          │ sessions        │  metadata, timestamps, tools
                          │ session_content │  FTS5 full-text index
                          │ session_topics  │  live topic timeline
                          │ session_tools   │  tool usage per session
                          │ session_agents  │  agent invocations
                          └─────────────────┘
```

The indexer parses JSONL files once, extracts metadata (timestamps, tools, agents, topics), and stores everything in SQLite. FTS5 handles the full-text search. Context retrieval reads JSONL on-demand — only the files you ask about.

## Tech stack

- **Python 3.10+** — stdlib only for core features (no dependencies)
- **SQLite + FTS5** — fast full-text search, no server needed
- **Anthropic SDK** — optional, only for standalone `synthesize` command

---

## All commands

### session-index (indexer)

```bash
session-index --backfill              # Index all existing sessions
session-index --incremental           # Index new/modified only
session-index --index <session_id>    # Index a single session
session-index --stats                 # Database statistics
```

### session-search

```bash
session-search search "query"         # Full-text search
session-search search "query" --context  # With conversation excerpts
session-search find --client X        # Filter by client
session-search find --tool Task       # Filter by tool used
session-search find --week            # Last 7 days
session-search find --project myapp   # Filter by project
session-search topics <session_id>    # Topic timeline
session-search recent 20              # Recent sessions
session-search stats                  # Database stats
session-search tools                  # Top tools across sessions
session-search tools "Bash"           # Sessions using specific tool
```

### session-analyze

```bash
session-analyze context <id> "term"   # Conversation around matches
session-analyze context <id>          # All exchanges
session-analyze analytics             # Overall stats
session-analyze analytics --client X  # Per-client
session-analyze analytics --week      # This week
session-analyze analytics --month     # This month
session-analyze synthesize "topic"    # Cross-session synthesis
session-analyze synthesize "topic" --limit 5
```

### session-topic-capture (hook script)

```bash
session-topic-capture UserPromptSubmit   # Periodic capture
session-topic-capture PreCompact         # Pre-compaction capture
session-topic-capture SessionEnd         # Final capture + re-index
```

---

## Requirements

- Python 3.10+
- Claude Code (the sessions to index)
- That's it. No server, no database setup, no API keys for core features.

---

Built by [Lee Fuhr](https://leefuhr.com)
