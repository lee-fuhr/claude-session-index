#!/usr/bin/env python3
"""
Session analyzer — context retrieval, analytics, and cross-session synthesis.

Three capabilities on top of the session index:
  A. context   — read JSONL, extract full conversation exchanges around a match
  B. analytics — pure SQL aggregations (time per client, tool trends, etc.)
  C. synthesize — search + read matching sessions + Haiku synthesis

Usage:
    python3 -m session_index.analyzer context <session_id> "search term"
    python3 -m session_index.analyzer analytics [--client X] [--week] [--month]
    python3 -m session_index.analyzer synthesize "query" [--limit 10]
"""

import json
import os
import re
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

try:
    from . import config
except ImportError:
    import config

# ---------------------------------------------------------------------------
# A. Context retrieval — JSONL parsing
# ---------------------------------------------------------------------------

def _summarize_tool_call(item: dict) -> str:
    """Collapse a tool_use block into a one-liner."""
    name = item.get("name", "unknown")
    inp = item.get("input", {})

    if name == "Read":
        return f"[Read: {inp.get('file_path', '?')}]"
    elif name == "Edit":
        fp = inp.get("file_path", "?")
        old = (inp.get("old_string") or "")[:40]
        return f"[Edit: {fp} ({old}...)]"
    elif name == "Write":
        return f"[Write: {inp.get('file_path', '?')}]"
    elif name == "Bash":
        cmd = (inp.get("command") or "")[:60]
        return f"[Bash: {cmd}]"
    elif name == "Task":
        desc = inp.get("description", "")
        atype = inp.get("subagent_type", "")
        return f'[Task: "{desc}" → {atype}]'
    elif name == "Grep":
        return f"[Grep: {inp.get('pattern', '?')}]"
    elif name == "Glob":
        return f"[Glob: {inp.get('pattern', '?')}]"
    elif name == "WebFetch":
        return f"[WebFetch: {inp.get('url', '?')[:60]}]"
    elif name == "WebSearch":
        return f"[WebSearch: {inp.get('query', '?')}]"
    else:
        return f"[{name}]"


def _extract_assistant_text(content) -> str:
    """Extract readable text from an assistant message's content blocks."""
    if isinstance(content, str):
        return content

    parts = []
    for block in (content or []):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "")
            if text and text != "(no content)":
                parts.append(text)
        elif block.get("type") == "tool_use":
            parts.append(_summarize_tool_call(block))

    return "\n".join(parts)


def _extract_user_text(content) -> str:
    """Extract readable text from a user message's content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(texts)
    return str(content)


def extract_exchanges(session_path: str | Path, query: str = None,
                      limit: int = 10, max_chars: int = 1000) -> list[dict]:
    """Extract user+assistant exchange pairs from JSONL.

    If query provided, only return exchanges where user message matches.
    Returns list of {user: str, assistant: str, timestamp: str} dicts.
    """
    path = Path(session_path)
    if not path.exists():
        return []

    # First pass: collect ordered entries
    entries = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = entry.get("type")
                if etype not in ("user", "assistant"):
                    continue

                msg = entry.get("message", {})
                content = msg.get("content", "")
                ts = entry.get("timestamp", "")

                if etype == "user":
                    text = _extract_user_text(content)
                else:
                    text = _extract_assistant_text(content)

                entries.append({
                    "type": etype,
                    "text": text,
                    "timestamp": ts,
                })
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return []

    # Pair consecutive user → assistant messages
    exchanges = []
    i = 0
    while i < len(entries):
        if entries[i]["type"] == "user":
            user_text = entries[i]["text"]
            user_ts = entries[i]["timestamp"]
            assistant_text = ""

            # Collect all assistant messages until next user message
            j = i + 1
            assistant_parts = []
            while j < len(entries) and entries[j]["type"] == "assistant":
                assistant_parts.append(entries[j]["text"])
                j += 1
            assistant_text = "\n".join(assistant_parts)

            exchanges.append({
                "user": user_text,
                "assistant": assistant_text,
                "timestamp": user_ts,
            })
            i = j
        else:
            i += 1

    # Filter by query if provided
    if query:
        # Try regex first, then substring, then individual words
        matched = None
        try:
            pattern = re.compile(query, re.IGNORECASE)
            matched = [
                ex for ex in exchanges
                if pattern.search(ex["user"]) or pattern.search(ex["assistant"])
            ]
        except re.error:
            pass

        if not matched:
            q = query.lower()
            matched = [
                ex for ex in exchanges
                if q in ex["user"].lower() or q in ex["assistant"].lower()
            ]

        # If exact match fails, try matching ANY word from the query
        if not matched:
            words = [w.lower() for w in query.split() if len(w) > 2]
            if words:
                matched = [
                    ex for ex in exchanges
                    if any(w in ex["user"].lower() or w in ex["assistant"].lower()
                           for w in words)
                ]

        exchanges = matched or []

    # Truncate long messages
    for ex in exchanges:
        if len(ex["user"]) > max_chars:
            ex["user"] = ex["user"][:max_chars] + "..."
        if len(ex["assistant"]) > max_chars:
            ex["assistant"] = ex["assistant"][:max_chars] + "..."

    return exchanges[:limit]


def get_context(session_id: str, query: str = None, limit: int = 10,
                db_path: Path = None) -> dict:
    """Get conversation context for a session.

    Returns dict with session info + matching exchanges.
    """
    if db_path is None:
        db_path = config.get_db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Resolve partial session ID
    if len(session_id) < 36:
        row = conn.execute(
            "SELECT session_id, file_path, title_display, project_name, client, "
            "start_time, exchange_count, duration_minutes "
            "FROM sessions WHERE session_id LIKE ?",
            (f"{session_id}%",)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT session_id, file_path, title_display, project_name, client, "
            "start_time, exchange_count, duration_minutes "
            "FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()

    conn.close()

    if not row:
        return {"error": f"Session not found: {session_id}"}

    session_info = dict(row)
    exchanges = extract_exchanges(
        session_info["file_path"], query=query, limit=limit
    )

    return {
        "session": session_info,
        "query": query,
        "exchanges": exchanges,
        "total_matches": len(exchanges),
    }


def format_context(result: dict) -> str:
    """Format context result for CLI output."""
    if "error" in result:
        return result["error"]

    lines = []
    s = result["session"]
    sid = s["session_id"][:8]
    title = s.get("title_display") or "(unnamed)"
    lines.append(f"Session: {title}")
    lines.append(f"  {s.get('start_time', '')[:10]} · {s.get('project_name', '')} · "
                  f"{s.get('exchange_count', 0)} exchanges · "
                  f"{s.get('duration_minutes') or '?'}min")
    lines.append(f"  claude --resume {s['session_id']}")

    if result["query"]:
        lines.append(f"\nMatching exchanges for \"{result['query']}\":")
    else:
        lines.append(f"\nAll exchanges ({result['total_matches']} shown):")

    lines.append("")

    for i, ex in enumerate(result["exchanges"], 1):
        ts = ex["timestamp"][:16] if ex["timestamp"] else ""
        lines.append(f"── Exchange {i} {ts} ──")
        lines.append(f"  User: {ex['user']}")
        lines.append(f"  Assistant: {ex['assistant']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# B. Analytics — pure SQL
# ---------------------------------------------------------------------------

def analytics(client: str = None, project: str = None,
              week: bool = False, month: bool = False,
              db_path: Path = None) -> dict:
    """Run analytics queries against sessions.db. Returns structured dict."""
    if db_path is None:
        db_path = config.get_db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    results = {}

    # Period filter
    period_clause = ""
    period_params = []
    period_label = "all time"
    if week:
        period_clause = "AND s.start_time >= ?"
        period_params = [(datetime.now() - timedelta(days=7)).isoformat()]
        period_label = "this week"
    elif month:
        period_clause = "AND s.start_time >= ?"
        period_params = [(datetime.now() - timedelta(days=30)).isoformat()]
        period_label = "this month"

    results["period"] = period_label

    # Client filter
    client_clause = ""
    client_params = []
    if client:
        client_clause = "AND s.client LIKE ?"
        client_params = [f"%{client}%"]

    # Project filter
    project_clause = ""
    project_params = []
    if project:
        project_clause = "AND (s.project_name LIKE ? OR s.project LIKE ?)"
        project_params = [f"%{project}%", f"%{project}%"]

    base_where = f"WHERE 1=1 {period_clause} {client_clause} {project_clause}"
    base_params = period_params + client_params + project_params

    # 1. Time per client
    rows = conn.execute(f"""
        SELECT s.client, COUNT(*) as sessions,
               SUM(s.duration_minutes) as total_minutes,
               ROUND(AVG(s.exchange_count), 1) as avg_exchanges
        FROM sessions s
        {base_where} AND s.client IS NOT NULL
        GROUP BY s.client ORDER BY total_minutes DESC
    """, base_params).fetchall()
    results["time_per_client"] = [dict(r) for r in rows]

    # 2. Session frequency (last 14 days, ignoring period filter)
    rows = conn.execute("""
        SELECT date(start_time) as day, COUNT(*) as sessions,
               SUM(duration_minutes) as minutes
        FROM sessions
        WHERE start_time >= date('now', '-14 days')
        GROUP BY day ORDER BY day
    """).fetchall()
    results["daily_trend"] = [dict(r) for r in rows]

    # 3. Overall stats for period
    row = conn.execute(f"""
        SELECT COUNT(*) as total_sessions,
               SUM(duration_minutes) as total_minutes,
               ROUND(AVG(duration_minutes), 1) as avg_duration,
               ROUND(AVG(exchange_count), 1) as avg_exchanges,
               SUM(CASE WHEN has_compaction = 1 THEN 1 ELSE 0 END) as compacted_sessions
        FROM sessions s
        {base_where}
    """, base_params).fetchone()
    results["overview"] = dict(row)

    # 4. Top tools (period-aware)
    rows = conn.execute(f"""
        SELECT st.tool_name, SUM(st.use_count) as total,
               COUNT(DISTINCT st.session_id) as session_count
        FROM session_tools st
        JOIN sessions s ON s.session_id = st.session_id
        {base_where}
        GROUP BY st.tool_name ORDER BY total DESC LIMIT 15
    """, base_params).fetchall()
    results["top_tools"] = [dict(r) for r in rows]

    # 5. Tool trends: this week vs last week
    this_week_start = (datetime.now() - timedelta(days=7)).isoformat()
    last_week_start = (datetime.now() - timedelta(days=14)).isoformat()
    rows = conn.execute("""
        SELECT tool_name,
               SUM(CASE WHEN s.start_time >= ? THEN use_count ELSE 0 END) as this_week,
               SUM(CASE WHEN s.start_time >= ? AND s.start_time < ? THEN use_count ELSE 0 END) as last_week
        FROM session_tools st
        JOIN sessions s ON s.session_id = st.session_id
        WHERE s.start_time >= ?
        GROUP BY tool_name
        HAVING this_week > 0 OR last_week > 0
        ORDER BY this_week DESC
        LIMIT 15
    """, (this_week_start, last_week_start, this_week_start, last_week_start)).fetchall()
    results["tool_trends"] = [dict(r) for r in rows]

    # 6. Most-discussed topics
    rows = conn.execute(f"""
        SELECT st.topic, COUNT(*) as mentions, st.source
        FROM session_topics st
        JOIN sessions s ON s.session_id = st.session_id
        {base_where}
        GROUP BY st.topic
        ORDER BY mentions DESC
        LIMIT 20
    """, base_params).fetchall()
    results["top_topics"] = [dict(r) for r in rows]

    # 7. Sessions per project
    rows = conn.execute(f"""
        SELECT s.project_name, COUNT(*) as sessions,
               SUM(s.duration_minutes) as total_minutes
        FROM sessions s
        {base_where}
        GROUP BY s.project_name ORDER BY sessions DESC
    """, base_params).fetchall()
    results["by_project"] = [dict(r) for r in rows]

    conn.close()
    return results


def format_analytics(data: dict) -> str:
    """Format analytics dict as readable CLI output."""
    lines = []

    period = data.get("period", "all time")
    lines.append(f"Session analytics ({period})")
    lines.append("=" * 50)

    # Overview
    ov = data.get("overview", {})
    total = ov.get("total_sessions", 0)
    mins = ov.get("total_minutes") or 0
    hours = round(mins / 60, 1) if mins else 0
    lines.append(f"\n  {total} sessions · {hours}h total · "
                  f"avg {ov.get('avg_duration') or 0}min/session · "
                  f"avg {ov.get('avg_exchanges') or 0} exchanges · "
                  f"{ov.get('compacted_sessions', 0)} compacted")

    # Time per client
    tpc = data.get("time_per_client", [])
    if tpc:
        lines.append(f"\nTime per client:")
        for r in tpc:
            hrs = round((r["total_minutes"] or 0) / 60, 1)
            lines.append(f"  {r['client']:25s}  {r['sessions']:>4d} sessions  "
                          f"{hrs:>6.1f}h  avg {r['avg_exchanges']} exchanges")

    # By project
    bp = data.get("by_project", [])
    if bp:
        lines.append(f"\nBy project:")
        for r in bp:
            hrs = round((r["total_minutes"] or 0) / 60, 1)
            lines.append(f"  {r['project_name']:25s}  {r['sessions']:>4d} sessions  {hrs:>6.1f}h")

    # Daily trend
    dt = data.get("daily_trend", [])
    if dt:
        lines.append(f"\nDaily trend (last 14 days):")
        for r in dt:
            mins = r["minutes"] or 0
            bar = "█" * min(int(mins / 15), 40)
            lines.append(f"  {r['day']}  {r['sessions']:>3d} sessions  "
                          f"{round(mins / 60, 1):>5.1f}h  {bar}")

    # Top tools
    tt = data.get("top_tools", [])
    if tt:
        lines.append(f"\nTop tools:")
        for r in tt:
            lines.append(f"  {r['tool_name']:25s}  {r['total']:>6d} uses  "
                          f"({r['session_count']} sessions)")

    # Tool trends
    trends = data.get("tool_trends", [])
    if trends:
        lines.append(f"\nTool trends (this week vs last):")
        for r in trends:
            tw = r["this_week"] or 0
            lw = r["last_week"] or 0
            if lw > 0:
                pct = round((tw - lw) / lw * 100)
                arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
                change = f"{arrow} {abs(pct)}%"
            elif tw > 0:
                change = "NEW"
            else:
                change = ""
            lines.append(f"  {r['tool_name']:25s}  {tw:>5d} (was {lw:>5d})  {change}")

    # Top topics
    topics = data.get("top_topics", [])
    if topics:
        lines.append(f"\nMost discussed topics:")
        for r in topics[:10]:
            lines.append(f"  {r['mentions']:>3d}x  {r['topic']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# C. Cross-session synthesis — Haiku
# ---------------------------------------------------------------------------

def synthesize(query: str, limit: int = 10, max_excerpt_chars: int = 2000,
               db_path: Path = None) -> dict:
    """Search sessions, extract relevant exchanges, synthesize with Haiku.

    Returns dict with synthesis text + source session references.
    Requires ANTHROPIC_API_KEY environment variable and the anthropic SDK.
    """
    if db_path is None:
        db_path = config.get_db_path()

    # Import Anthropic SDK — graceful degradation if unavailable
    try:
        from anthropic import Anthropic

        def haiku_ask(prompt, system="You are a fast, precise assistant.", max_tokens=2048):
            client = Anthropic()
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
    except ImportError:
        return {
            "error": "Synthesis requires the Anthropic SDK. Install with: pip install anthropic",
            "sessions": [],
            "synthesis": None,
        }

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "error": "ANTHROPIC_API_KEY environment variable is required for synthesis.",
            "sessions": [],
            "synthesis": None,
        }

    # Step 1: Search for matching sessions via FTS
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT s.session_id, s.file_path, s.title_display, s.project_name,
               s.client, s.start_time, s.exchange_count, s.duration_minutes,
               snippet(session_content, 1, '>>>', '<<<', '...', 30) as snippet
        FROM session_content
        JOIN sessions s ON s.session_id = session_content.session_id
        WHERE session_content MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit)).fetchall()

    conn.close()

    if not rows:
        return {
            "error": f"No sessions found matching: {query}",
            "sessions": [],
            "synthesis": None,
        }

    # Step 2: Extract relevant exchanges from each matching session
    session_excerpts = []
    sources = []
    for row in rows:
        info = dict(row)
        sources.append({
            "session_id": info["session_id"],
            "title": info.get("title_display") or "(unnamed)",
            "date": (info.get("start_time") or "")[:10],
            "project": info.get("project_name", ""),
            "client": info.get("client", ""),
        })

        exchanges = extract_exchanges(
            info["file_path"], query=query, limit=5, max_chars=max_excerpt_chars
        )

        if exchanges:
            excerpt_lines = []
            title = info.get("title_display") or info["session_id"][:8]
            date = (info.get("start_time") or "")[:10]
            excerpt_lines.append(f"### Session: {title} ({date})")
            for ex in exchanges:
                excerpt_lines.append(f"User: {ex['user']}")
                excerpt_lines.append(f"Assistant: {ex['assistant']}")
                excerpt_lines.append("")
            session_excerpts.append("\n".join(excerpt_lines))

    if not session_excerpts:
        return {
            "error": "Found sessions but couldn't extract relevant exchanges.",
            "sessions": sources,
            "synthesis": None,
        }

    # Step 3: Build synthesis prompt
    formatted_excerpts = "\n---\n".join(session_excerpts)

    # Trim total context to ~20K chars for Haiku
    if len(formatted_excerpts) > 20000:
        formatted_excerpts = formatted_excerpts[:20000] + "\n[...truncated]"

    system_prompt = "You are analyzing Claude Code session excerpts. Be specific — reference actual solutions, file names, tools used. Keep it concise (under 500 words)."

    user_prompt = f"""Given the following conversation excerpts about "{query}", synthesize:

1. **Approaches tried** — What solutions or methods were attempted?
2. **What worked** — Which approaches succeeded? Key decisions that helped?
3. **What failed** — What was abandoned or didn't work? Why?
4. **Recurring patterns** — Any themes, repeated issues, or evolving understanding?
5. **Current state** — Where did things land? What's the latest?

--- EXCERPTS ---
{formatted_excerpts}"""

    # Step 4: Call Haiku
    synthesis = haiku_ask(user_prompt, system=system_prompt, max_tokens=2048)

    return {
        "query": query,
        "sessions": sources,
        "synthesis": synthesis,
        "excerpt_count": len(session_excerpts),
    }


def format_synthesis(result: dict) -> str:
    """Format synthesis result for CLI output."""
    if "error" in result and result.get("synthesis") is None:
        return result["error"]

    lines = []
    lines.append(f"Cross-session synthesis: \"{result.get('query', '')}\"")
    lines.append("=" * 50)

    # Sources
    sources = result.get("sessions", [])
    if sources:
        lines.append(f"\nSources ({len(sources)} sessions, "
                      f"{result.get('excerpt_count', 0)} with matching exchanges):")
        for s in sources:
            title = s.get("title") or "(unnamed)"
            if len(title) > 60:
                title = title[:57] + "..."
            lines.append(f"  {s['date']}  {title}")
            lines.append(f"           claude --resume {s['session_id']}")

    # Synthesis
    if result.get("synthesis"):
        lines.append(f"\n{'─' * 50}")
        lines.append(result["synthesis"])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Session analyzer")
    parser.add_argument("--db-path", help="Path to sessions.db (overrides config)")
    subparsers = parser.add_subparsers(dest="command")

    # context
    sp = subparsers.add_parser("context", help="Show conversation context for a session")
    sp.add_argument("session_id", help="Session ID (full or prefix)")
    sp.add_argument("query", nargs="?", default=None, help="Filter to matching exchanges")
    sp.add_argument("-n", "--limit", type=int, default=10, help="Max exchanges to show")

    # analytics
    sp = subparsers.add_parser("analytics", help="Session analytics")
    sp.add_argument("--client", help="Filter by client")
    sp.add_argument("--project", help="Filter by project")
    sp.add_argument("--week", action="store_true", help="This week only")
    sp.add_argument("--month", action="store_true", help="This month only")

    # synthesize
    sp = subparsers.add_parser("synthesize", help="Cross-session synthesis via Haiku")
    sp.add_argument("query", help="Topic to synthesize across sessions")
    sp.add_argument("--limit", type=int, default=10, help="Max sessions to analyze")

    args = parser.parse_args()

    # Resolve db_path from CLI flag
    db_path = None
    if args.db_path:
        db_path = Path(args.db_path).expanduser()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "context":
        result = get_context(args.session_id, query=args.query, limit=args.limit,
                             db_path=db_path)
        print(format_context(result))

    elif args.command == "analytics":
        result = analytics(
            client=args.client, project=args.project,
            week=args.week, month=args.month,
            db_path=db_path,
        )
        print(format_analytics(result))

    elif args.command == "synthesize":
        result = synthesize(args.query, limit=args.limit, db_path=db_path)
        print(format_synthesis(result))


if __name__ == "__main__":
    main()
