# Claude session index

**Every Claude Code session you've ever had, searchable in under a second.**

You've built things across hundreds of sessions. Solved problems, hit walls, found workarounds. But sessions disappear into `~/.claude/projects/` as unlabeled JSONL files — thousands of them, unsearchable, forgettable. This tool indexes them all into a fast SQLite database with full-text search, conversation retrieval, analytics, and cross-session synthesis.

Ask "what did I try last time I debugged webhooks?" and get an actual answer.

---

## Quick start

```bash
pip install claude-session-index
```

Then install the Claude Code skill:

```bash
npx skills add lee-fuhr/claude-session-index
```

Or copy it manually:

```bash
cp skills/session-index/SKILL.md .claude/skills/session-index.md
```

That's it. The first time you ask a question, it auto-indexes all your existing sessions. After that, queries return in milliseconds.

---

## How it works (for you)

The interface is your Claude Code conversation. You ask questions naturally, Claude translates them into searches, and gives you conversational answers.

### "Didn't we discuss browser control recently?"

Claude searches your sessions, finds the matches, and tells you:

> You discussed browser control in 3 sessions last week. The most relevant was on Jan 18 where you figured out that synthetic MouseEvent dispatch bypasses the framework's event handling. The key insight was that the submit button was a `<div>`, not a `<button>`.
>
> → `claude --resume a5b111c6-dca0-4ee9-b237-74b75baf13cd`

### "What have I tried for form automation? What actually worked?"

Claude searches across sessions, extracts the relevant conversations, and synthesizes:

> **Approaches tried:** element.click() → failed (framework intercepts). Coordinate-based clicking → failed (dynamic elements). Synthetic MouseEvent dispatch → success.
>
> **What worked:** Native OS-level clicking for all button interaction. Persistent browser profiles for session continuity.
>
> **What failed:** All JavaScript-based clicking — the framework intercepts and blocks it.
>
> Sources: 5 sessions spanning Jan 10–Feb 1
> → `claude --resume abc123...`
> → `claude --resume def456...`

### "How did I spend my week?"

> 89 sessions this week. 302 hours total.
>
> Windmill Labs: 2 sessions, 47h
> GridSync: 2 sessions, 17h
> NovaTech: 4 sessions, 7h
>
> Top tools: Bash (3,214), Read (2,126), Edit (1,718)
> Task agent usage up 142% from last week.

Every answer includes `claude --resume` links so you can jump straight back into any session.

---

## What it does under the hood

1. **Indexes** all your Claude Code sessions into SQLite with FTS5 full-text search
2. **Searches** by content, client, project, tool, agent, tag, or date — results in milliseconds
3. **Retrieves context** — actual conversation exchanges (user + assistant), not just metadata
4. **Analyzes** your usage — time per client, tool trends, session frequency, topic patterns
5. **Synthesizes** across sessions — "What approaches have I tried for X?" via in-session Haiku subagent (no extra API cost)
6. **Tracks topics** live during sessions via Claude Code hooks

---

## The CLI

The skill handles the conversational interface. But if you want direct access from a terminal, everything goes through `sessions`:

```bash
# Search — just type what you're looking for
sessions "webhook debugging"
sessions "webhook" --context              # with conversation excerpts

# Browse a conversation
sessions context <id> "term"              # exchanges matching a term
sessions context <id>                     # all exchanges

# Analytics
sessions analytics                        # overall stats
sessions analytics --client "Acme"        # per-client
sessions analytics --week                 # this week
sessions analytics --month                # this month

# Synthesis (requires anthropic package + API key for standalone use)
sessions synthesize "topic"               # cross-session intelligence

# Browse & filter
sessions recent 20                        # last N sessions
sessions find --client "Acme"             # filter by client
sessions find --tool Task --week          # filter by tool + date
sessions topics <session_id>              # topic timeline
sessions tools                            # top tools across sessions
sessions stats                            # database overview

# Indexing
sessions index                            # index new/modified sessions
sessions index --backfill                 # re-index everything
```

Plain text defaults to search — `sessions "webhook debugging"` just works, no subcommand needed.

### CLI output

Search results look like this:

```
🔍 3 results for "silent failure"

  ◆ a5b111c6 · (unnamed)
    2026-01-18 · my-project · 51 exchanges
    "...This was a silent failure - appeared to work but didn't..."
    → claude --resume a5b111c6-dca0-4ee9-b237-74b75baf13cd

  ◆ 7b22239e · (unnamed)
    2026-01-18 · my-project · 50 exchanges
    "...The phrase 'silent failure, which is the ultimate sin'
    captures the core requirement: systems must fail loudly..."
    → claude --resume 7b22239e-9f90-466f-ad92-849840b2a6fd
```

Conversation context shows the actual chat:

```
╭─── Build automation debugging ─────────────────
│ 2026-01-20 · my-project · 96 exchanges · 7min
│ → claude --resume a5b111c6-dca0-4ee9-b237-74b75baf13cd
╰────────────────────────────────────────────────

  ┌─ Jan 20, 19:14 ──────────────────────────────
  │
  │  🧑 Breakthrough session. Successfully submitted forms #32 and #33
  │     using synthetic MouseEvent dispatch to bypass the framework's
  │     event handling.
  │
  │  🤖 I'll process these findings. Let me search for existing patterns...
  │     [Grep: framework|zone\.js|MouseEvent|click]
  │     [Read: /path/to/automation/docs.md]
  │
  └────────────────────────────────────────────────
```

Tool calls get collapsed into readable one-liners — `[Read: path]`, `[Edit: path]`, `[Bash: command]`, `[Task: "description" → agent]` — so you can follow the conversation without drowning in JSON.

---

## Live topic tracking

Capture what you're working on during sessions via Claude Code hooks. Topics get indexed for search.

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

Topics are captured every 10 exchanges, before compaction, and at session end.

### Background indexing (macOS)

Keep the index fresh automatically:

```bash
cp launchagent/com.session-indexer.plist ~/Library/LaunchAgents/
# Edit the plist to point to your Python path
launchctl load ~/Library/LaunchAgents/com.session-indexer.plist
```

Runs `session-index --incremental` every 30 minutes. Only processes new or modified sessions.

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

## How it works (technically)

```
~/.claude/projects/          session-index              Your conversation
  ├── -project-a/              ┌──────────┐
  │   ├── abc123.jsonl ──────▶│ SQLite   │◀──── "Didn't we discuss X?"
  │   └── def456.jsonl ──────▶│ + FTS5   │◀──── "How'd I spend my week?"
  ├── -project-b/              └──────────┘◀──── "What worked for Y?"
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

## Requirements

- Python 3.10+
- Claude Code (the sessions to index)
- That's it. No server, no database setup, no API keys for core features.

---

Built by [Lee Fuhr](https://leefuhr.com)
