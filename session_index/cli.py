#!/usr/bin/env python3
"""
Unified CLI for claude-session-index.

Plain text defaults to search — no subcommands needed for the common case.

Usage:
    sessions "webhook debugging"                # search (default)
    sessions "webhook" --context                # search with conversation excerpts
    sessions context a5b111c6 "failure"         # conversation around matches
    sessions context a5b111c6                   # all exchanges
    sessions analytics --week                   # this week's stats
    sessions analytics --client "Acme"          # per-client stats
    sessions synthesize "form automation"       # cross-session synthesis
    sessions recent                             # last 10 sessions
    sessions recent 20                          # last 20 sessions
    sessions find --tool Task --week            # filter sessions
    sessions tools                              # top tools across sessions
    sessions tools "Bash"                       # sessions using specific tool
    sessions topics <session_id>                # topic timeline
    sessions stats                              # database overview
    sessions index                              # re-index new/modified
    sessions index --backfill                   # re-index everything
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

try:
    from . import config
    from .search import SessionSearch, format_result
    from .analyzer import (
        get_context, format_context,
        analytics, format_analytics,
        synthesize, format_synthesis,
    )
except ImportError:
    import config
    from search import SessionSearch, format_result
    from analyzer import (
        get_context, format_context,
        analytics, format_analytics,
        synthesize, format_synthesis,
    )


SUBCOMMANDS = {
    'context', 'analytics', 'synthesize', 'recent', 'find',
    'tools', 'topics', 'stats', 'index', 'search',
}


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog='sessions',
        description='Search and analyze your Claude Code sessions',
        usage='sessions "query" | sessions <command> [options]',
    )
    parser.add_argument('--db-path', type=str, default=None,
                        help='Path to sessions.db (overrides config)')

    subparsers = parser.add_subparsers(dest='command')

    # search (also the default when no subcommand given)
    sp = subparsers.add_parser('search', help='Full-text search')
    sp.add_argument('query', help='Search query')
    sp.add_argument('-n', '--limit', type=int, default=20)
    sp.add_argument('--context', action='store_true',
                    help='Show conversation exchanges inline')

    # context
    sp = subparsers.add_parser('context', help='Conversation context for a session')
    sp.add_argument('session_id', help='Session ID (full or prefix)')
    sp.add_argument('query', nargs='?', default=None, help='Filter to matching exchanges')
    sp.add_argument('-n', '--limit', type=int, default=10, help='Max exchanges')

    # analytics
    sp = subparsers.add_parser('analytics', help='Session analytics')
    sp.add_argument('--client', help='Filter by client')
    sp.add_argument('--project', help='Filter by project')
    sp.add_argument('--week', action='store_true', help='This week only')
    sp.add_argument('--month', action='store_true', help='This month only')

    # synthesize
    sp = subparsers.add_parser('synthesize', help='Cross-session synthesis')
    sp.add_argument('query', help='Topic to synthesize across sessions')
    sp.add_argument('--limit', type=int, default=10, help='Max sessions to analyze')

    # recent
    sp = subparsers.add_parser('recent', help='Recent sessions')
    sp.add_argument('n', nargs='?', type=int, default=10)

    # find
    sp = subparsers.add_parser('find', help='Filter sessions')
    sp.add_argument('--client', help='Filter by client')
    sp.add_argument('--tag', help='Filter by tag')
    sp.add_argument('--tool', help='Filter by tool used')
    sp.add_argument('--agent', help='Filter by agent used')
    sp.add_argument('--date', help='Filter by date (YYYY-MM-DD)')
    sp.add_argument('--week', action='store_true', help='Last 7 days')
    sp.add_argument('--project', help='Filter by project')
    sp.add_argument('--compacted', action='store_true', help='Only compacted sessions')
    sp.add_argument('-n', '--limit', type=int, default=20)

    # tools
    sp = subparsers.add_parser('tools', help='Tool usage')
    sp.add_argument('tool_name', nargs='?', help='Specific tool')

    # topics
    sp = subparsers.add_parser('topics', help='Topic timeline for a session')
    sp.add_argument('session_id', help='Session ID (full or prefix)')

    # stats
    subparsers.add_parser('stats', help='Database overview')

    # index
    sp = subparsers.add_parser('index', help='Index sessions')
    sp.add_argument('--backfill', action='store_true', help='Re-index everything')
    sp.add_argument('--session', metavar='ID', help='Index a single session')

    # --- Default to search if first arg isn't a subcommand ---
    # Intercept before argparse: if the first real arg isn't a known
    # subcommand or flag, treat the whole thing as a search query.
    raw_args = sys.argv[1:]
    if raw_args and raw_args[0] not in SUBCOMMANDS and not raw_args[0].startswith('-'):
        # Bare text = search. Rebuild as: search "the query" [flags]
        query_parts = []
        flags = []
        for arg in raw_args:
            if arg.startswith('-'):
                flags.append(arg)
            else:
                query_parts.append(arg)
        sys.argv = [sys.argv[0], 'search', ' '.join(query_parts)] + flags

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Resolve paths
    db_path = Path(args.db_path) if args.db_path else config.get_db_path()
    config.ensure_indexed(db_path)

    # --- Dispatch ---

    if args.command == 'search':
        searcher = SessionSearch(db_path=db_path)
        searcher.connect()
        try:
            results = searcher.search(args.query, args.limit)
            if not results:
                print(f"No results for: {args.query}")
                return
            print(f"\n🔍 {len(results)} results for \"{args.query}\"\n")
            for r in results:
                print(format_result(r))
                if args.context:
                    ctx = get_context(r['session_id'], query=args.query, limit=3, db_path=db_path)
                    if ctx.get('exchanges'):
                        for ex in ctx['exchanges']:
                            ts = ex['timestamp'][:16] if ex['timestamp'] else ''
                            try:
                                dt = datetime.fromisoformat(ts)
                                ts_display = dt.strftime("%b %d, %H:%M")
                            except (ValueError, TypeError):
                                ts_display = ts
                            print(f"    ┌─ {ts_display} {'─' * max(1, 36 - len(ts_display))}")
                            user_preview = ex['user'][:250].replace('\n', ' ')
                            asst_preview = ex['assistant'][:250].replace('\n', ' ')
                            print(f"    │ 🧑 {user_preview}")
                            print(f"    │ 🤖 {asst_preview}")
                            print(f"    └{'─' * 42}")
                print()
        finally:
            searcher.close()

    elif args.command == 'context':
        result = get_context(args.session_id, query=args.query,
                             limit=args.limit, db_path=db_path)
        print(format_context(result))

    elif args.command == 'analytics':
        result = analytics(
            client=args.client, project=args.project,
            week=args.week, month=args.month,
            db_path=db_path,
        )
        print(format_analytics(result))

    elif args.command == 'synthesize':
        result = synthesize(args.query, limit=args.limit, db_path=db_path)
        print(format_synthesis(result))

    elif args.command == 'recent':
        searcher = SessionSearch(db_path=db_path)
        searcher.connect()
        try:
            results = searcher.recent(args.n)
            print(f"\n📋 Last {len(results)} sessions\n")
            for r in results:
                print(format_result(r))
                print()
        finally:
            searcher.close()

    elif args.command == 'find':
        searcher = SessionSearch(db_path=db_path)
        searcher.connect()
        try:
            results = searcher.find(
                client=args.client, tag=args.tag, tool=args.tool,
                agent=args.agent, date=args.date, week=args.week,
                project=args.project,
                has_compaction=True if args.compacted else None,
                limit=args.limit,
            )
            if not results:
                print("No sessions match those filters.")
                return
            print(f"\n📋 {len(results)} sessions\n")
            for r in results:
                print(format_result(r))
                print()
        finally:
            searcher.close()

    elif args.command == 'tools':
        searcher = SessionSearch(db_path=db_path)
        searcher.connect()
        try:
            tool_name = getattr(args, 'tool_name', None)
            results = searcher.tools_usage(tool_name)
            if tool_name:
                print(f"\n🔧 Sessions using '{tool_name}'\n")
                for r in results:
                    sid = r['session_id'][:8]
                    title = r.get('title_display') or r.get('title') or '(unnamed)'
                    print(f"  ◆ {sid} · {r['tool_name']} ×{r['use_count']}  {title}")
            else:
                print(f"\n🔧 Top tools across all sessions\n")
                for r in results:
                    print(f"  {r['tool_name']:25s}  {r['total']:>6d} uses  ({r['session_count']} sessions)")
        finally:
            searcher.close()

    elif args.command == 'topics':
        searcher = SessionSearch(db_path=db_path)
        searcher.connect()
        try:
            sid = args.session_id
            if len(sid) < 36:
                row = searcher.conn.execute(
                    "SELECT session_id FROM sessions WHERE session_id LIKE ?", (f"{sid}%",)
                ).fetchone()
                if row:
                    sid = row['session_id']
                else:
                    print(f"No session found matching: {sid}")
                    return

            topics = searcher.topics(sid)
            if not topics:
                print(f"No topics recorded for session {sid[:8]}")
                return

            session = searcher.conn.execute(
                "SELECT title_display, start_time, project_name FROM sessions WHERE session_id=?",
                (sid,)
            ).fetchone()

            if session:
                title = session['title_display'] or '(unnamed)'
                print(f"\n╭─── {title} {'─' * max(1, 44 - len(title))}")
                meta = []
                if session['start_time']:
                    meta.append(session['start_time'][:16])
                if session['project_name']:
                    meta.append(session['project_name'])
                print(f"│ {' · '.join(meta)}")
                print(f"╰{'─' * 48}")

            print(f"\n💬 Topic timeline ({len(topics)} entries)\n")
            for t in topics:
                ts = t['captured_at'][:16] if t['captured_at'] else ''
                ex = f" (exchange {t['exchange_number']})" if t['exchange_number'] else ''
                src = t['source']
                print(f"  [{src:20s}] {ts}{ex}")
                print(f"                       {t['topic']}")
                print()
        finally:
            searcher.close()

    elif args.command == 'stats':
        searcher = SessionSearch(db_path=db_path)
        searcher.connect()
        try:
            stats = searcher.stats()
            print(f"\n📊 Database overview")
            print(f"{'═' * 40}")
            print(f"  Sessions:  {stats.get('total_sessions', 0)}")
            print(f"  Topics:    {stats.get('total_topics', 0)}")
            print(f"  Tools:     {stats.get('total_tools', 0)} distinct")
            print(f"  Agents:    {stats.get('total_agents', 0)} distinct")
            dr = stats.get('date_range', {})
            if dr.get('earliest'):
                print(f"  Range:     {dr['earliest']} → {dr['latest']}")
            if stats.get('by_project'):
                print(f"\n  📁 By project")
                print(f"  {'─' * 36}")
                for name, cnt in list(stats['by_project'].items())[:10]:
                    print(f"  {name:25s}  {cnt:>5d}")
            if stats.get('top_tools'):
                print(f"\n  🔧 Top tools")
                print(f"  {'─' * 36}")
                for name, cnt in list(stats['top_tools'].items())[:10]:
                    print(f"  {name:25s}  {cnt:>5d}")
            print()
        finally:
            searcher.close()

    elif args.command == 'index':
        try:
            from session_index.indexer import SessionIndexer
        except ImportError:
            try:
                from .indexer import SessionIndexer
            except ImportError:
                from indexer import SessionIndexer

        indexer = SessionIndexer(db_path=db_path)
        indexer.connect()
        try:
            if args.backfill:
                indexer.backfill_all()
            elif args.session:
                if indexer.index_session(session_id=args.session):
                    print(f"Indexed: {args.session}")
                else:
                    print(f"Failed to index: {args.session}", file=sys.stderr)
                    sys.exit(1)
            else:
                stats = indexer.index_incremental()
                print(f"Incremental: {stats['indexed']} new/updated, "
                      f"{stats['unchanged']} unchanged, {stats['errors']} errors")
        finally:
            indexer.close()


if __name__ == "__main__":
    main()
