---
name: session-index
description: Search, analyze, and synthesize across your Claude Code sessions
version: 0.1.0
triggers:
  - session search
  - session history
  - session analytics
  - what sessions
  - past conversations
  - what have I tried
  - what worked last time
---

# Session index skill

You have access to a session index that catalogs all Claude Code sessions — searchable by content, client, project, tool, and date.

## Capabilities

### Search sessions
Find past sessions by topic, client, tool, or date range.

```bash
session-search search "deployment debugging"
session-search find --client "Acme" --week
session-search recent 20
session-search stats
```

### View conversation context
Read the actual conversation (user + assistant exchanges) from any session.

```bash
session-analyze context <session_id> "search term"
session-analyze context <session_id>   # all exchanges
```

### Analytics
See effort distribution, tool trends, and session patterns. Pure SQL, no API calls.

```bash
session-analyze analytics                    # overall
session-analyze analytics --client "Acme"    # per client
session-analyze analytics --week             # this week
session-analyze analytics --month            # this month
```

### Cross-session synthesis
Answer questions like "What have I tried for X?" by searching across sessions and synthesizing the answer. Use a Haiku subagent (via Task tool with `model="haiku"`) to keep costs within the Claude Code subscription — no external API needed.

**Workflow for synthesis:**
1. Run `session-search search "TOPIC" -n 10` to find matching sessions
2. For the top 3-5 results, run `session-analyze context <session_id> "TOPIC" -n 3` to extract relevant exchanges
3. Spawn a Task with `model="haiku"` to synthesize the collected excerpts:
   - What approaches were tried?
   - What worked / what failed?
   - Recurring patterns?
   - Current state?
4. Present the synthesis with `claude --resume <session_id>` links for each source

## Installation

```bash
pip install claude-session-index
session-index --backfill   # Index existing sessions (one-time)
```

## Data location

- **Database:** `~/.session-index/sessions.db`
- **Topics:** `~/.claude/session-topics/`
- **Config:** `~/.session-index/config.json` (optional)
