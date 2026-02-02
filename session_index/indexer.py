#!/usr/bin/env python3
"""
Session index — core DB + indexing module.

Indexes all Claude Code sessions into SQLite with FTS5 for fast search.

Usage:
    python3 indexer.py --backfill                    # Index all existing sessions
    python3 indexer.py --incremental                 # Index new/modified sessions
    python3 indexer.py --index <session_id>          # Index single session
    python3 indexer.py --stats                       # Show DB stats
    python3 indexer.py --db-path /tmp/test.db        # Override database path
    python3 indexer.py --projects-dir ~/.claude/projects  # Override projects dir
"""

import json
import os
import sys
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

try:
    from . import config
except ImportError:
    import config


class SessionIndexer:
    def __init__(self, db_path: Path = None, projects_dir: Path = None):
        self.db_path = db_path or config.get_db_path()
        self.projects_dir = projects_dir or config.get_projects_dir()
        self.project_name_map = config.get_project_names()
        self.clients = config.get_clients()
        self.conn = None

    def connect(self):
        """Open DB connection and ensure schema exists."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                project TEXT,
                project_name TEXT,
                title TEXT,
                title_display TEXT,
                tags TEXT,
                client TEXT,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                exchange_count INTEGER DEFAULT 0,
                start_time TEXT,
                end_time TEXT,
                duration_minutes INTEGER,
                model TEXT,
                has_compaction INTEGER DEFAULT 0,
                indexed_at TEXT NOT NULL,
                last_modified TEXT,
                file_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS session_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                exchange_number INTEGER,
                source TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS session_tools (
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                use_count INTEGER DEFAULT 0,
                PRIMARY KEY (session_id, tool_name),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS session_agents (
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                invocation_count INTEGER DEFAULT 0,
                PRIMARY KEY (session_id, agent_name),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
            CREATE INDEX IF NOT EXISTS idx_sessions_client ON sessions(client);
            CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_time);
            CREATE INDEX IF NOT EXISTS idx_topics_session ON session_topics(session_id);
            CREATE INDEX IF NOT EXISTS idx_topics_source ON session_topics(source);
        """)

        # FTS5 table — check if exists first
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_content'"
        ).fetchone()
        if not row:
            self.conn.execute("""
                CREATE VIRTUAL TABLE session_content USING fts5(
                    session_id,
                    content,
                    tokenize='porter unicode61'
                )
            """)

        self.conn.commit()

    def _file_hash(self, path: Path) -> str:
        """Quick hash based on size + mtime (not content — too slow for backfill)."""
        stat = path.stat()
        return hashlib.md5(f"{stat.st_size}:{stat.st_mtime}".encode()).hexdigest()

    def _parse_session(self, session_path: Path) -> Optional[dict]:
        """Parse a session JSONL file into indexable data."""
        session_id = session_path.stem
        project_dir = session_path.parent.name

        user_prompts = []
        tools = {}
        agents = {}
        exchange_count = 0
        start_time = None
        end_time = None
        model = None
        has_compaction = False
        title = None
        title_display = None
        tags_str = None
        summaries = []

        try:
            with open(session_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    entry_type = entry.get('type')
                    timestamp = entry.get('timestamp')

                    # Track timestamps
                    if timestamp:
                        if start_time is None:
                            start_time = timestamp
                        end_time = timestamp

                    # Custom title (latest wins)
                    if entry_type == 'custom-title':
                        title_display = entry.get('customTitle', '')
                        # Parse ">>> NAME ... [tags]" format
                        if title_display.startswith('>>>'):
                            parts = title_display.split('......')
                            name_part = parts[0].replace('>>>', '').strip()
                            title = name_part
                            if len(parts) > 1:
                                tag_part = parts[-1].strip().strip('[]<>').strip()
                                if tag_part:
                                    tags_str = tag_part

                    # Compaction summaries
                    if entry_type == 'summary':
                        has_compaction = True
                        summary_text = entry.get('summary', '')
                        if summary_text:
                            # Parse JSON summaries to extract clean title/text
                            if summary_text.strip().startswith('{'):
                                try:
                                    parsed = json.loads(summary_text)
                                    clean = parsed.get('title', '') or parsed.get('summary', '') or summary_text
                                    summaries.append(clean)
                                except (json.JSONDecodeError, AttributeError):
                                    summaries.append(summary_text)
                            else:
                                summaries.append(summary_text)

                    # Count exchanges
                    if entry_type in ('user', 'assistant'):
                        exchange_count += 1

                    # Extract model
                    if entry_type == 'assistant' and not model:
                        model = entry.get('message', {}).get('model', '')

                    # Extract user messages
                    if entry_type == 'user':
                        content = entry.get('message', {}).get('content', '')
                        if isinstance(content, list):
                            text_parts = [
                                item.get('text', '')
                                for item in content
                                if isinstance(item, dict) and item.get('type') == 'text'
                            ]
                            content = ' '.join(text_parts)
                        if content and len(content) > 10:
                            user_prompts.append(content)

                    # Extract tool usage
                    if entry_type == 'assistant':
                        msg_content = entry.get('message', {}).get('content', [])
                        if isinstance(msg_content, list):
                            for item in msg_content:
                                if isinstance(item, dict) and item.get('type') == 'tool_use':
                                    tool = item.get('name', '')
                                    tools[tool] = tools.get(tool, 0) + 1

                                    # Track Task invocations as agents
                                    if tool == 'Task':
                                        agent_type = item.get('input', {}).get('subagent_type', '')
                                        if agent_type:
                                            agents[agent_type] = agents.get(agent_type, 0) + 1

        except Exception as e:
            print(f"Error parsing {session_id}: {e}", file=sys.stderr)
            return None

        # Auto-generate title if none was set explicitly
        if not title_display and summaries:
            title_display = summaries[0][:80]
            if len(summaries[0]) > 80:
                title_display = summaries[0][:77] + '...'
            title = title_display
        elif not title_display and user_prompts:
            # Use first substantial user message, skipping bad title candidates
            title_display = self._pick_title_from_prompts(user_prompts)
            if title_display:
                title = title_display

        # Detect client from user prompts + file paths in tool calls
        client = None
        if self.clients:
            all_text = ' '.join(user_prompts[:10]).lower()
            for c in self.clients:
                if c.lower() in all_text:
                    client = c
                    break
            # Also check project name
            if not client:
                project_name = self.project_name_map.get(project_dir, project_dir)
                for c in self.clients:
                    if c.lower() in project_name.lower():
                        client = c
                        break

        # Calculate duration
        duration = None
        if start_time and end_time:
            try:
                s = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                e = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                duration = int((e - s).total_seconds() / 60)
            except:
                pass

        # Build FTS content from user prompts (truncated to avoid huge entries)
        fts_content = '\n'.join(user_prompts[:50])
        if len(fts_content) > 100000:
            fts_content = fts_content[:100000]

        # Add summaries as bonus topic data
        topic_entries = []
        for summary in summaries:
            topic_entries.append({
                'topic': summary[:120],
                'source': 'compaction_summary',
                'captured_at': end_time or datetime.now().isoformat(),
                'exchange_number': None,
            })

        return {
            'session_id': session_id,
            'project': project_dir,
            'project_name': self.project_name_map.get(project_dir, project_dir),
            'title': title,
            'title_display': title_display,
            'tags': tags_str,
            'client': client,
            'file_path': str(session_path),
            'file_size': session_path.stat().st_size,
            'exchange_count': exchange_count,
            'start_time': start_time,
            'end_time': end_time,
            'duration_minutes': duration,
            'model': model,
            'has_compaction': 1 if has_compaction else 0,
            'file_hash': self._file_hash(session_path),
            'tools': tools,
            'agents': agents,
            'fts_content': fts_content,
            'topics': topic_entries,
        }

    # First-line patterns that make bad auto-titles
    _SKIP_TITLE_PREFIXES = (
        '#',            # Markdown headers (## Curation Data, etc.)
        'You are',      # Agent system prompts
        'Caveat:',      # System caveats injected by hooks
        'Explore the',  # Agent exploration prompts
    )

    def _pick_title_from_prompts(self, user_prompts: list) -> Optional[str]:
        """Pick the best user message to use as auto-title, skipping system noise."""
        for prompt in user_prompts[:5]:
            first_line = prompt.strip().split('\n')[0].strip()
            if len(first_line) <= 10:
                continue
            if any(first_line.startswith(p) for p in self._SKIP_TITLE_PREFIXES):
                continue
            if len(first_line) > 80:
                return first_line[:77] + '...'
            return first_line
        return None

    def index_session(self, session_id: str = None, file_path: str = None) -> bool:
        """Index a single session. Provide either session_id or file_path."""
        if file_path:
            path = Path(file_path)
        elif session_id:
            # Find the file across all project dirs
            path = self._find_session_file(session_id)
        else:
            return False

        if not path or not path.exists():
            print(f"Session file not found: {session_id or file_path}", file=sys.stderr)
            return False

        data = self._parse_session(path)
        if not data:
            return False

        return self._upsert_session(data)

    def _find_session_file(self, session_id: str) -> Optional[Path]:
        """Find session file by ID across all project directories."""
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
        return None

    def _upsert_session(self, data: dict) -> bool:
        """Insert or update a session in the DB."""
        try:
            now = datetime.now().isoformat()

            self.conn.execute("""
                INSERT INTO sessions (
                    session_id, project, project_name, title, title_display, tags,
                    client, file_path, file_size, exchange_count, start_time, end_time,
                    duration_minutes, model, has_compaction, indexed_at, last_modified, file_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title=excluded.title, title_display=excluded.title_display,
                    tags=excluded.tags, client=excluded.client,
                    file_size=excluded.file_size, exchange_count=excluded.exchange_count,
                    end_time=excluded.end_time, duration_minutes=excluded.duration_minutes,
                    model=excluded.model, has_compaction=excluded.has_compaction,
                    indexed_at=excluded.indexed_at, last_modified=excluded.last_modified,
                    file_hash=excluded.file_hash
            """, (
                data['session_id'], data['project'], data['project_name'],
                data['title'], data['title_display'], data['tags'],
                data['client'], data['file_path'], data['file_size'],
                data['exchange_count'], data['start_time'], data['end_time'],
                data['duration_minutes'], data['model'], data['has_compaction'],
                now, now, data['file_hash'],
            ))

            # Upsert tools
            self.conn.execute("DELETE FROM session_tools WHERE session_id=?", (data['session_id'],))
            for tool, count in data['tools'].items():
                self.conn.execute(
                    "INSERT INTO session_tools (session_id, tool_name, use_count) VALUES (?, ?, ?)",
                    (data['session_id'], tool, count)
                )

            # Upsert agents
            self.conn.execute("DELETE FROM session_agents WHERE session_id=?", (data['session_id'],))
            for agent, count in data['agents'].items():
                self.conn.execute(
                    "INSERT INTO session_agents (session_id, agent_name, invocation_count) VALUES (?, ?, ?)",
                    (data['session_id'], agent, count)
                )

            # Upsert FTS content
            self.conn.execute("DELETE FROM session_content WHERE session_id=?", (data['session_id'],))
            if data['fts_content']:
                self.conn.execute(
                    "INSERT INTO session_content (session_id, content) VALUES (?, ?)",
                    (data['session_id'], data['fts_content'])
                )

            # Add topics from compaction summaries (don't delete existing hook-captured topics)
            for topic in data['topics']:
                # Check if this exact topic already exists
                existing = self.conn.execute(
                    "SELECT id FROM session_topics WHERE session_id=? AND topic=? AND source=?",
                    (data['session_id'], topic['topic'], topic['source'])
                ).fetchone()
                if not existing:
                    self.conn.execute(
                        "INSERT INTO session_topics (session_id, topic, captured_at, exchange_number, source) VALUES (?, ?, ?, ?, ?)",
                        (data['session_id'], topic['topic'], topic['captured_at'],
                         topic['exchange_number'], topic['source'])
                    )

            self.conn.commit()
            return True

        except Exception as e:
            print(f"Error upserting {data['session_id']}: {e}", file=sys.stderr)
            self.conn.rollback()
            return False

    def backfill_all(self, progress_interval: int = 100) -> dict:
        """Index all existing sessions. Returns stats dict."""
        stats = {'total': 0, 'indexed': 0, 'skipped': 0, 'errors': 0}
        session_files = []

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for f in project_dir.glob("*.jsonl"):
                session_files.append(f)

        stats['total'] = len(session_files)
        print(f"Found {stats['total']} session files to index")

        for i, session_path in enumerate(session_files):
            if (i + 1) % progress_interval == 0:
                print(f"  Progress: {i + 1}/{stats['total']} ({stats['indexed']} indexed, {stats['errors']} errors)")

            # Skip if already indexed with same hash
            session_id = session_path.stem
            current_hash = self._file_hash(session_path)
            existing = self.conn.execute(
                "SELECT file_hash FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if existing and existing['file_hash'] == current_hash:
                stats['skipped'] += 1
                continue

            data = self._parse_session(session_path)
            if not data:
                stats['errors'] += 1
                continue

            if self._upsert_session(data):
                stats['indexed'] += 1
            else:
                stats['errors'] += 1

        print(f"\nBackfill complete: {stats['indexed']} indexed, {stats['skipped']} unchanged, {stats['errors']} errors")
        return stats

    def index_incremental(self) -> dict:
        """Index new or modified sessions since last run."""
        stats = {'checked': 0, 'indexed': 0, 'unchanged': 0, 'errors': 0}

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for session_path in project_dir.glob("*.jsonl"):
                stats['checked'] += 1
                session_id = session_path.stem
                current_hash = self._file_hash(session_path)

                existing = self.conn.execute(
                    "SELECT file_hash FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone()

                if existing and existing['file_hash'] == current_hash:
                    stats['unchanged'] += 1
                    continue

                data = self._parse_session(session_path)
                if not data:
                    stats['errors'] += 1
                    continue

                if self._upsert_session(data):
                    stats['indexed'] += 1
                else:
                    stats['errors'] += 1

        return stats

    def get_stats(self) -> dict:
        """Get database statistics."""
        stats = {}
        stats['total_sessions'] = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        stats['total_topics'] = self.conn.execute("SELECT COUNT(*) FROM session_topics").fetchone()[0]
        stats['total_tools'] = self.conn.execute("SELECT COUNT(DISTINCT tool_name) FROM session_tools").fetchone()[0]
        stats['total_agents'] = self.conn.execute("SELECT COUNT(DISTINCT agent_name) FROM session_agents").fetchone()[0]

        # Sessions by project
        rows = self.conn.execute(
            "SELECT project_name, COUNT(*) as cnt FROM sessions GROUP BY project_name ORDER BY cnt DESC"
        ).fetchall()
        stats['by_project'] = {r['project_name']: r['cnt'] for r in rows}

        # Sessions by client
        rows = self.conn.execute(
            "SELECT client, COUNT(*) as cnt FROM sessions WHERE client IS NOT NULL GROUP BY client ORDER BY cnt DESC"
        ).fetchall()
        stats['by_client'] = {r['client']: r['cnt'] for r in rows}

        # Top tools
        rows = self.conn.execute(
            "SELECT tool_name, SUM(use_count) as total FROM session_tools GROUP BY tool_name ORDER BY total DESC LIMIT 10"
        ).fetchall()
        stats['top_tools'] = {r['tool_name']: r['total'] for r in rows}

        # Sessions with topics
        stats['sessions_with_topics'] = self.conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM session_topics"
        ).fetchone()[0]

        # Date range
        row = self.conn.execute(
            "SELECT MIN(start_time) as earliest, MAX(start_time) as latest FROM sessions WHERE start_time IS NOT NULL"
        ).fetchone()
        stats['date_range'] = {
            'earliest': row['earliest'][:10] if row['earliest'] else None,
            'latest': row['latest'][:10] if row['latest'] else None,
        }

        return stats

    def add_topic(self, session_id: str, topic: str, source: str, exchange_number: int = None):
        """Add a topic entry for a session."""
        self.conn.execute(
            "INSERT INTO session_topics (session_id, topic, captured_at, exchange_number, source) VALUES (?, ?, ?, ?, ?)",
            (session_id, topic, datetime.now().isoformat(), exchange_number, source)
        )
        self.conn.commit()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Session indexer")
    parser.add_argument('--backfill', action='store_true', help='Index all existing sessions')
    parser.add_argument('--incremental', action='store_true', help='Index new/modified sessions')
    parser.add_argument('--index', metavar='SESSION_ID', help='Index a single session by ID')
    parser.add_argument('--stats', action='store_true', help='Show DB statistics')
    parser.add_argument('--db-path', metavar='PATH', help='Override database path')
    parser.add_argument('--projects-dir', metavar='PATH', help='Override projects directory')
    args = parser.parse_args()

    db_path = config.get_db_path(override=args.db_path) if args.db_path else None
    projects_dir = config.get_projects_dir(override=args.projects_dir) if args.projects_dir else None

    indexer = SessionIndexer(db_path=db_path, projects_dir=projects_dir)
    indexer.connect()

    try:
        if args.backfill:
            indexer.backfill_all()
        elif args.incremental:
            stats = indexer.index_incremental()
            print(f"Incremental: {stats['indexed']} new/updated, {stats['unchanged']} unchanged, {stats['errors']} errors")
        elif args.index:
            if indexer.index_session(session_id=args.index):
                print(f"Indexed: {args.index}")
            else:
                print(f"Failed to index: {args.index}", file=sys.stderr)
                sys.exit(1)
        elif args.stats:
            stats = indexer.get_stats()
            print(json.dumps(stats, indent=2))
        else:
            parser.print_help()
    finally:
        indexer.close()


if __name__ == "__main__":
    main()
