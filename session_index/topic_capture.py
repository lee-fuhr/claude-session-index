#!/usr/bin/env python3
"""
Session topic capture — hook script for live topic tracking.

Single script handles all 3 hook events via CLAUDE_HOOK_EVENT_NAME env var:
- UserPromptSubmit: Every 10 exchanges, extract topic from recent messages
- PreCompact: Always capture (last chance before context loss)
- SessionEnd: Capture final topic + trigger full session index update

Topic extraction: parse last 3 user messages from JSONL, take first
substantive sentence of most recent, truncate to 60 chars. No API calls.

Writes to:
1. topics_dir/{session_id}.txt (statusLine reads this)
2. session_topics table in sessions.db
"""

import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime

try:
    from . import config
except ImportError:
    import config

# Config
TOPIC_INTERVAL = 10  # Capture topic every N exchanges
STATE_FILE = Path.home() / ".session-index" / "topic-capture-state.json"

# Noise patterns to skip
SKIP_PATTERNS = [
    r'^(yes|no|ok|sure|thanks|thank you|yep|nope|cool|great|good|fine|hmm|ah|oh)\b',
    r'^/$',  # slash commands
    r'^<system-reminder>',
    r'^<task-notification>',
    r'^This session has ended',
    r'^\[Request interrupted',
    r'^Please curate the memories',
    r'^implement the following plan',
]
SKIP_RE = [re.compile(p, re.IGNORECASE) for p in SKIP_PATTERNS]

# Read stdin once at module level (hooks receive JSON on stdin)
_STDIN_DATA = {}
try:
    if not sys.stdin.isatty():
        _STDIN_DATA = json.loads(sys.stdin.read())
except:
    pass


def get_session_id() -> str:
    """Get session ID from stdin JSON (reliable) or env var (fallback)."""
    sid = _STDIN_DATA.get('session_id', '')
    if sid:
        return sid
    return os.environ.get('CLAUDE_SESSION_ID', 'unknown')


def get_hook_event() -> str:
    """Determine which hook event triggered us. Passed as CLI arg."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return os.environ.get('CLAUDE_HOOK_EVENT_NAME', 'unknown')


def get_exchange_count(session_path: Path) -> int:
    """Count user messages in session JSONL (reliable per-session count).

    We count directly from the file rather than using the exchange counter
    state file, which lumps all sessions under 'unknown' due to broken
    CLAUDE_SESSION_ID env var.
    """
    if not session_path or not session_path.exists():
        return 0
    count = 0
    try:
        with open(session_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if '"type":"user"' in line or '"type": "user"' in line:
                    count += 1
    except:
        pass
    return count


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def find_session_file(session_id: str) -> Path | None:
    """Find session JSONL file across project dirs."""
    projects_dir = config.get_projects_dir()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def extract_recent_user_messages(session_path: Path, count: int = 3) -> list[str]:
    """Extract last N user messages from JSONL (efficient tail read)."""
    messages = []
    try:
        # Read from end — efficient for large files
        with open(session_path, 'r', encoding='utf-8', errors='ignore') as f:
            # For speed, read last 200KB (enough for recent messages)
            f.seek(0, 2)
            file_size = f.tell()
            read_size = min(file_size, 200_000)
            f.seek(max(0, file_size - read_size))

            lines = f.readlines()

        # Parse in reverse to find user messages
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get('type') != 'user':
                continue

            content = entry.get('message', {}).get('content', '')
            if isinstance(content, list):
                text_parts = [
                    item.get('text', '')
                    for item in content
                    if isinstance(item, dict) and item.get('type') == 'text'
                ]
                content = ' '.join(text_parts)

            if not content or len(content) < 15:
                continue

            # Skip noise
            if any(p.search(content) for p in SKIP_RE):
                continue

            messages.append(content)
            if len(messages) >= count:
                break

    except Exception as e:
        print(f"Error reading session: {e}", file=sys.stderr)

    messages.reverse()  # Chronological order
    return messages


def extract_topic(messages: list[str]) -> str | None:
    """Extract a concise topic from recent user messages.

    Strategy: take the most recent substantive message, extract first
    sentence/clause, truncate to 60 chars.
    """
    if not messages:
        return None

    # Use most recent message
    msg = messages[-1]

    # Strip system reminder content
    msg = re.sub(r'<system-reminder>.*?</system-reminder>', '', msg, flags=re.DOTALL)

    # Strip markdown formatting
    msg = re.sub(r'```[\s\S]*?```', '', msg)  # code blocks
    msg = re.sub(r'`[^`]+`', '', msg)  # inline code
    msg = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', msg)  # links
    msg = re.sub(r'[#*_~]+', '', msg)  # formatting chars

    # Clean whitespace
    msg = ' '.join(msg.split())
    msg = msg.strip()

    if not msg or len(msg) < 10:
        # Fall back to second most recent
        if len(messages) >= 2:
            return extract_topic(messages[:-1])
        return None

    # Extract first sentence/clause
    # Split on sentence boundaries
    sentences = re.split(r'[.!?]\s+', msg)
    topic = sentences[0].strip()

    # If first sentence is too long, take first clause
    if len(topic) > 60:
        clauses = re.split(r'[,;:—–\-]\s+', topic)
        topic = clauses[0].strip()

    # Final truncation
    if len(topic) > 60:
        topic = topic[:57] + '...'

    # Capitalize first letter
    if topic:
        topic = topic[0].upper() + topic[1:]

    return topic


def write_topic_file(session_id: str, topic: str):
    """Write topic to the statusLine-readable file."""
    topic_dir = config.get_topics_dir()
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_file = topic_dir / f"{session_id}.txt"
    topic_file.write_text(topic)


def write_topic_db(session_id: str, topic: str, source: str, exchange_number: int = None):
    """Write topic to the sessions database."""
    try:
        import sqlite3
        db_path = config.get_db_path()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO session_topics (session_id, topic, captured_at, exchange_number, source) VALUES (?, ?, ?, ?, ?)",
            (session_id, topic, datetime.now().isoformat(), exchange_number, source)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # DB might not exist yet if backfill hasn't run — that's OK
        print(f"Topic DB write skipped: {e}", file=sys.stderr)


def trigger_full_index(session_id: str, session_path: Path):
    """Trigger a full session index update."""
    try:
        from session_index.indexer import SessionIndexer
    except ImportError:
        try:
            # Fallback: try sibling import (running from package dir)
            from .indexer import SessionIndexer
        except ImportError:
            print("SessionIndexer not available — skipping full index", file=sys.stderr)
            return

    try:
        indexer = SessionIndexer()
        indexer.connect()
        indexer.index_session(file_path=str(session_path))
        indexer.close()
    except Exception as e:
        print(f"Full index failed: {e}", file=sys.stderr)


def handle_user_prompt_submit(session_id: str):
    """Handle UserPromptSubmit — periodic topic capture."""
    # Find session file first (needed for exchange counting)
    session_path = find_session_file(session_id)
    if not session_path:
        return

    exchange_count = get_exchange_count(session_path)

    # Check if we should capture at this interval
    state = load_state()
    session_state = state.get(session_id, {'last_capture_at': 0})
    last_capture = session_state.get('last_capture_at', 0)

    # Capture at intervals: 10, 20, 30, etc.
    if exchange_count < TOPIC_INTERVAL:
        return
    if exchange_count - last_capture < TOPIC_INTERVAL:
        return

    messages = extract_recent_user_messages(session_path)
    topic = extract_topic(messages)
    if not topic:
        return

    # Write to topic file + DB
    write_topic_file(session_id, topic)
    write_topic_db(session_id, topic, 'hook_periodic', exchange_count)

    # Update state
    state[session_id] = {'last_capture_at': exchange_count}
    save_state(state)


def handle_pre_compact(session_id: str):
    """Handle PreCompact — always capture (last chance before context loss)."""
    session_path = find_session_file(session_id)
    if not session_path:
        return

    messages = extract_recent_user_messages(session_path, count=5)
    topic = extract_topic(messages)
    if not topic:
        return

    exchange_count = get_exchange_count(session_path)
    write_topic_file(session_id, topic)
    write_topic_db(session_id, topic, 'hook_precompact', exchange_count)


def handle_session_end(session_id: str):
    """Handle SessionEnd — final topic + full index update."""
    session_path = find_session_file(session_id)
    if not session_path:
        return

    # Capture final topic
    messages = extract_recent_user_messages(session_path, count=5)
    topic = extract_topic(messages)
    if topic:
        exchange_count = get_exchange_count(session_path)
        write_topic_file(session_id, topic)
        write_topic_db(session_id, topic, 'hook_session_end', exchange_count)

    # Full session index update
    trigger_full_index(session_id, session_path)

    # Clean up state for this session
    state = load_state()
    state.pop(session_id, None)
    save_state(state)


def main():
    session_id = get_session_id()
    if session_id == 'unknown':
        sys.exit(0)

    hook_event = get_hook_event()

    if hook_event == 'UserPromptSubmit':
        handle_user_prompt_submit(session_id)
    elif hook_event == 'PreCompact':
        handle_pre_compact(session_id)
    elif hook_event == 'SessionEnd':
        handle_session_end(session_id)
    else:
        # Unknown event — do nothing
        pass


if __name__ == "__main__":
    main()
