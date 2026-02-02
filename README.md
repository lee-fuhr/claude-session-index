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
session-search find --client "Windmill Labs" --week
session-search find --tool "Task" --project "my-app"

# Recent sessions
session-search recent 20

# Show conversation context inline with results
session-search search "auth bug" --context
```

**Output** (from a real system with 2,900+ indexed sessions):
```
3 results for "silent failure":

  a5b111c6  (unnamed)
           2026-01-18 · my-project · 51 exchanges
           "...This was a silent failure - appeared to work but didn't..."
           claude --resume a5b111c6-dca0-4ee9-b237-74b75baf13cd

  7b22239e  (unnamed)
           2026-01-18 · my-project · 50 exchanges
           "...The phrase 'silent failure, which is the ultimate sin'
           captures the core requirement: systems must fail loudly..."
           claude --resume 7b22239e-9f90-466f-ad92-849840b2a6fd
```

Each result shows the session title, metadata, matching snippet, topic timeline, and a ready-to-copy `claude --resume` command.

### Search with inline context

Add `--context` to see actual conversation exchanges right in the search results:

```
session-search search "silent failure" --context

  a5b111c6  (unnamed)
           2026-01-18 · my-project · 51 exchanges
           ── 2026-01-18T04:55 ──
           User: [session data about discovering a silent failure in background jobs]
           Asst: Now let me check for any existing "silent failure" or
                 "user feedback" patterns in the codebase...
                 This is a new failure mode — appeared to work but didn't...
```

## Conversation context

Read the actual conversation from any session — not just metadata, but what was said.

```bash
# Show exchanges matching a term
session-analyze context a5b111c6 "failure"

# Show all exchanges
session-analyze context a5b111c6
```

**Output** (from a real session):
```
Session: Build automation debugging
  2026-01-20 · my-project · 96 exchanges · 7min

Matching exchanges for "click":

── Exchange 1 2026-01-20T19:14 ──
  User: Breakthrough session. Successfully submitted forms #32 and #33
        using synthetic MouseEvent dispatch to bypass the framework's
        event handling. Key learning: the submit button is a DIV with
        class 'action-button', NOT a <button> tag.
  Assistant: I'll process these findings. Let me search for existing
        patterns related to the framework and event handling...
        [Grep: angular|zone\.js|MouseEvent|click]
        [Read: /path/to/automation/docs.md]
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

**Output** (from a real system):
```
Session analytics (this week)
==================================================

  89 sessions · 302.8h total · avg 204min/session · avg 340 exchanges · 20 compacted

Time per client:
  Windmill Labs                 2 sessions    47.7h  avg 250 exchanges
  GridSync                      2 sessions    17.2h  avg 269 exchanges
  NovaTech                      4 sessions     7.3h  avg 212 exchanges

By project:
  tools                        20 sessions   170.8h
  consulting                    8 sessions    90.3h
  personal                      5 sessions    31.0h

Daily trend (last 14 days):
  2026-01-19    5 sessions   50.0h  ████████████████████████████████████████
  2026-01-20   18 sessions   57.2h  ████████████████████████████████████████
  2026-01-21   16 sessions   76.0h  ████████████████████████████████████████
  2026-01-22    6 sessions    7.9h  ███████████████████████████████
  2026-01-28    8 sessions   50.1h  ████████████████████████████████████████
  2026-01-29   21 sessions   40.9h  ████████████████████████████████████████
  2026-01-30   16 sessions  122.2h  ████████████████████████████████████████
  2026-01-31    7 sessions    5.0h  ████████████████████
  2026-02-01   18 sessions   34.5h  ████████████████████████████████████████

Top tools:
  Bash                         3214 uses  (46 sessions)
  Read                         2126 uses  (83 sessions)
  Edit                         1718 uses  (71 sessions)
  Grep                          785 uses  (66 sessions)
  Write                         316 uses  (20 sessions)
  Task                          218 uses  (21 sessions)

Tool trends (this week vs last):
  Task                         218 (was    90)  ↑ 142%
  Skill                         24 (was     7)  ↑ 243%
  Read                        2126 (was  1084)  ↑ 96%
  Edit                        1718 (was   818)  ↑ 110%
  WebFetch                      60 (was   125)  ↓ 52%
```

## Cross-session synthesis

The most powerful feature. Ask a question, get a synthesized answer from across all your sessions.

```bash
session-analyze synthesize "form automation debugging"
session-analyze synthesize "database migration patterns" --limit 5
```

**Output** (from a real synthesis across 5 sessions spanning 3 weeks):
```
Cross-session synthesis: "form automation debugging"
==================================================

Sources (5 sessions):
  2026-01-10  Build automation system — initial 4-module architecture
  2026-01-15  Form submission debugging — element selectors
  2026-01-18  Breakthrough — synthetic events bypass framework
  2026-01-20  Documentation + QA hardening
  2026-02-01  Phase 2 — 14 files, 4,200 lines, QA swarm

──────────────────────────────────────────────────

**Approaches tried:** element.click() → failed (framework intercepts).
Coordinate-based clicking → failed (dynamic elements). Synthetic
MouseEvent dispatch → success (bypasses framework event handling).

**What worked:** Native OS-level clicking for all button interaction.
Key insight: submit button was a <div>, not a <button>. Persistent
browser profiles for session continuity.

**What failed:** All JavaScript-based clicking (framework intercepts
and blocks). Manual fallback rejected as philosophy: "figure out how
to automate it, not do it manually."

**Recurring patterns:** Framework as persistent blocker. DOM inspection
before strategy selection. Iterative QA hardening (20 rounds → swarm).
Scaling from 4 modules → 14 files across 7 agents.

**Current state:** Phase 2 complete. End-to-end test passed. 7-day
autonomous validation running.
```

This searches your sessions, extracts relevant conversation exchanges, and sends them to Claude Haiku for synthesis. Requires the `anthropic` package and an API key:

```bash
pip install claude-session-index[synthesis]
export ANTHROPIC_API_KEY=sk-...
```

**If you're already in a Claude Code session**, you can skip the API cost entirely. The skill instructs Claude to search, extract, and synthesize using an in-session Haiku subagent — no external API call needed.

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
