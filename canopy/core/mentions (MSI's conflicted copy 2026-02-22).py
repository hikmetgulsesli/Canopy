"""
Mention event handling for Canopy.

Stores per-user mention events and provides helpers to resolve
@mentions in content so agents can react on demand.

Author: Konrad Walus (architecture, design, and direction)
Project: Canopy - Local Mesh Communication
License: Apache 2.0
Development: AI-assisted implementation (Claude, Codex, GitHub Copilot, Cursor IDE, Ollama)
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

logger = logging.getLogger(__name__)


# Match @handles when the preceding character is not part of a handle.
# This supports markdown wrappers like "**@Agent**", avoids emails, and
# avoids swallowing trailing punctuation at sentence boundaries.
MENTION_REGEX = re.compile(
    r'(^|[^A-Za-z0-9_.\-@])@([A-Za-z0-9](?:[A-Za-z0-9_.\-]{0,47}[A-Za-z0-9]))'
)


def extract_mentions(text: str) -> List[str]:
    """Extract @handles from a string."""
    if not text or '@' not in text:
        return []
    return [m.group(2) for m in MENTION_REGEX.finditer(text)]


def build_preview(text: str, limit: int = 120) -> str:
    """Create a short preview string for notifications."""
    if not text:
        return ""
    preview = str(text).strip()
    if len(preview) > limit:
        preview = preview[: limit - 3] + "..."
    return preview


def _normalize_handles(handles: Sequence[str]) -> List[str]:
    """Normalize handles while preserving case (case-sensitive dedupe)."""
    cleaned = []
    for h in handles or []:
        if not h:
            continue
        cleaned.append(str(h).strip())
    # preserve order while de-duping (case-sensitive)
    seen = set()
    ordered = []
    for h in cleaned:
        if h in seen:
            continue
        seen.add(h)
        ordered.append(h)
    return ordered


def _normalize_display_handle(display_name: Optional[str]) -> str:
    """Normalize display_name to a mention handle: trim, collapse spaces, replace with underscore.
    Must match SQL normalization used in _query so resolution is consistent."""
    if not display_name:
        return ""
    return "_".join(str(display_name).strip().split())


def _lower_handles(handles: Sequence[str]) -> List[str]:
    """Lowercase handles while preserving order (case-insensitive dedupe)."""
    cleaned = []
    for h in handles or []:
        if not h:
            continue
        cleaned.append(str(h).strip().lower())
    seen = set()
    ordered = []
    for h in cleaned:
        if h in seen:
            continue
        seen.add(h)
        ordered.append(h)
    return ordered


def resolve_mention_targets(
    db_manager: Any,
    handles: Sequence[str],
    channel_id: Optional[str] = None,
    visibility: Optional[str] = None,
    permissions: Optional[Sequence[str]] = None,
    author_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Resolve mention handles to user records.

    For channel mentions, restrict to channel members.
    For feed mentions, apply visibility/permission filtering.
    """
    handles_raw = _normalize_handles(handles)
    if not handles_raw:
        return []

    # Normalize display_name for matching: TRIM + collapse multiple spaces + space to underscore.
    # Must match _normalize_display_handle() so DB and Python comparison agree.
    _norm_display_u = (
        "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(u.display_name,'')), '  ', ' '), '  ', ' '), '  ', ' '), '  ', ' '), ' ', '_')"
    )
    _norm_display = (
        "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(display_name,'')), '  ', ' '), '  ', ' '), '  ', ' '), '  ', ' '), ' ', '_')"
    )
    try:
        with db_manager.get_connection() as conn:
            def _query(handles_list: Sequence[str], case_sensitive: bool) -> List[Any]:
                if not handles_list:
                    return []
                placeholders = ",".join("?" for _ in handles_list)
                if channel_id:
                    params = [channel_id] + list(handles_list) + list(handles_list) + list(handles_list)
                    if case_sensitive:
                        sql = f"""
                        SELECT u.id, u.username, u.display_name, u.public_key, u.origin_peer,
                               cm.notifications_enabled
                        FROM users u
                        JOIN channel_members cm ON u.id = cm.user_id
                        WHERE cm.channel_id = ?
                          AND u.id NOT IN ('system', 'local_user')
                          AND (u.id IN ({placeholders})
                               OR TRIM(COALESCE(u.username,'')) IN ({placeholders})
                               OR {_norm_display_u} IN ({placeholders}))
                        """
                    else:
                        sql = f"""
                        SELECT u.id, u.username, u.display_name, u.public_key, u.origin_peer,
                               cm.notifications_enabled
                        FROM users u
                        JOIN channel_members cm ON u.id = cm.user_id
                        WHERE cm.channel_id = ?
                          AND u.id NOT IN ('system', 'local_user')
                          AND (LOWER(u.id) IN ({placeholders})
                               OR LOWER(TRIM(COALESCE(u.username,''))) IN ({placeholders})
                               OR LOWER({_norm_display_u}) IN ({placeholders}))
                        """
                    return cast(List[Any], conn.execute(sql, params).fetchall())
                else:
                    params = list(handles_list) + list(handles_list) + list(handles_list)
                    if case_sensitive:
                        sql = f"""
                        SELECT id, username, display_name, public_key, origin_peer
                        FROM users
                        WHERE id NOT IN ('system', 'local_user')
                          AND (id IN ({placeholders})
                               OR TRIM(COALESCE(username,'')) IN ({placeholders})
                               OR {_norm_display} IN ({placeholders}))
                        """
                    else:
                        sql = f"""
                        SELECT id, username, display_name, public_key, origin_peer
                        FROM users
                        WHERE id NOT IN ('system', 'local_user')
                          AND (LOWER(id) IN ({placeholders})
                               OR LOWER(TRIM(COALESCE(username,''))) IN ({placeholders})
                               OR LOWER({_norm_display}) IN ({placeholders}))
                        """
                    return cast(List[Any], conn.execute(sql, params).fetchall())

            exact_rows = _query(handles_raw, case_sensitive=True)
            exact_handles = set()
            rows = []
            for row in exact_rows:
                try:
                    row_id = row['id']
                    row_username = (row['username'] or '').strip()
                    row_display = row['display_name'] or ''
                except Exception:
                    row_id = row[0]
                    row_username = (row[1] or '').strip() if len(row) > 1 else ''
                    row_display = row[2] if len(row) > 2 else ''
                display_handle = _normalize_display_handle(row_display)
                for handle in handles_raw:
                    if handle == row_id or (row_username and handle == row_username) or (display_handle and handle == display_handle):
                        exact_handles.add(handle)
                rows.append(row)

            remaining = [h for h in handles_raw if h not in exact_handles]
            if remaining:
                remaining_lower = _lower_handles(remaining)
                rows.extend(_query(remaining_lower, case_sensitive=False))
    except Exception as e:
        logger.error(f"Failed to resolve mention targets: {e}")
        return []

    # Apply visibility filters for feed posts
    allowed: Optional[set] = None
    if visibility:
        vis = str(visibility).lower()
        if vis == 'private' and author_id:
            allowed = {author_id}
        elif vis == 'custom':
            allowed = set(permissions or [])

    targets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        try:
            user_id = row['id']
            username = row['username']
            public_key = row['public_key']
            origin_peer = row['origin_peer']
            notifications_enabled = None
            if 'notifications_enabled' in row.keys():
                notifications_enabled = row['notifications_enabled']
        except Exception:
            user_id = row[0]
            username = row[1]
            # row[2] is display_name when selected; shift indices accordingly
            public_key = row[3] if len(row) > 3 else row[2]
            origin_peer = row[4] if len(row) > 4 else None
            notifications_enabled = row[5] if len(row) > 5 else None

        if author_id and user_id == author_id:
            continue
        if allowed is not None and user_id not in allowed:
            continue

        targets[user_id] = {
            'user_id': user_id,
            'username': username,
            'public_key': public_key,
            'origin_peer': origin_peer,
            'notifications_enabled': notifications_enabled,
        }

    return list(targets.values())


def split_mention_targets(
    targets: Sequence[Dict[str, Any]],
    local_peer_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split mention targets into local vs remote candidates."""
    local_targets: List[Dict[str, Any]] = []
    remote_targets: List[Dict[str, Any]] = []
    for t in targets or []:
        public_key = t.get('public_key')
        origin_peer = t.get('origin_peer')
        is_local = bool(public_key) and (not origin_peer or (local_peer_id and origin_peer == local_peer_id))
        if is_local:
            local_targets.append(t)
        else:
            remote_targets.append(t)
    return local_targets, remote_targets


class MentionManager:
    """Stores per-user mention events."""

    def __init__(self, db_manager):
        self.db = db_manager
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            with self.db.get_connection() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS mention_events (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        author_id TEXT,
                        origin_peer TEXT,
                        channel_id TEXT,
                        preview TEXT,
                        metadata TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        acknowledged_at TIMESTAMP,
                        status TEXT DEFAULT 'new'
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_mention_events_unique
                        ON mention_events(user_id, source_type, source_id);
                    CREATE INDEX IF NOT EXISTS idx_mention_events_user
                        ON mention_events(user_id, created_at);
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure mention_events table: {e}")

    def record_mentions(
        self,
        user_ids: Sequence[str],
        source_type: str,
        source_id: str,
        author_id: Optional[str] = None,
        origin_peer: Optional[str] = None,
        channel_id: Optional[str] = None,
        preview: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Insert mention events for the given user IDs."""
        if not user_ids or not source_id:
            return []

        inserted: List[str] = []
        unique_users = list(dict.fromkeys([uid for uid in user_ids if uid]))
        meta_json = json.dumps(metadata) if metadata else None
        base_time = datetime.now(timezone.utc)
        try:
            with self.db.get_connection() as conn:
                for idx, uid in enumerate(unique_users):
                    mention_id = f"MN{secrets.token_hex(8)}"
                    created_at = (base_time + timedelta(microseconds=idx)).strftime('%Y-%m-%d %H:%M:%S.%f')
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO mention_events
                        (id, user_id, source_type, source_id, author_id, origin_peer,
                         channel_id, preview, metadata, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            mention_id, uid, source_type, source_id,
                            author_id, origin_peer, channel_id,
                            preview or '', meta_json, created_at
                        ),
                    )
                    if cur.rowcount:
                        inserted.append(mention_id)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to record mention events: {e}")
        return inserted

    def get_mentions(
        self,
        user_id: str,
        since: Optional[Any] = None,
        limit: int = 50,
        include_acknowledged: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch mention events for a user."""
        if not user_id:
            return []

        since_db = None
        if since is not None and since != "":
            try:
                if isinstance(since, (int, float)):
                    dt = datetime.fromtimestamp(float(since), tz=timezone.utc)
                else:
                    s = str(since)
                    if s.isdigit():
                        dt = datetime.fromtimestamp(float(s), tz=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                since_db = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                since_db = None

        limit_val = max(1, min(int(limit or 50), 200))

        try:
            with self.db.get_connection() as conn:
                query = """
                    SELECT id, user_id, source_type, source_id, author_id,
                           origin_peer, channel_id, preview, metadata,
                           created_at, acknowledged_at, status
                    FROM mention_events
                    WHERE user_id = ?
                """
                params: List[Any] = [user_id]
                if not include_acknowledged:
                    query += " AND acknowledged_at IS NULL"
                if since_db:
                    query += " AND created_at > ?"
                    params.append(since_db)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit_val)
                rows = conn.execute(query, params).fetchall()
        except Exception as e:
            logger.error(f"Failed to fetch mention events: {e}")
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            try:
                created_at = row['created_at']
                ack_at = row['acknowledged_at']
            except Exception:
                created_at = row[9]
                ack_at = row[10]

            created_iso = created_at
            if created_at:
                try:
                    dt = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    created_iso = dt.isoformat()
                except Exception:
                    created_iso = created_at

            ack_iso = ack_at
            if ack_at:
                try:
                    dt = datetime.fromisoformat(str(ack_at).replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ack_iso = dt.isoformat()
                except Exception:
                    ack_iso = ack_at

            try:
                metadata = json.loads(row['metadata']) if row['metadata'] else None
            except Exception:
                metadata = None

            results.append({
                'id': row['id'] if hasattr(row, '__getitem__') else row[0],
                'user_id': row['user_id'] if hasattr(row, '__getitem__') else row[1],
                'source_type': row['source_type'] if hasattr(row, '__getitem__') else row[2],
                'source_id': row['source_id'] if hasattr(row, '__getitem__') else row[3],
                'author_id': row['author_id'] if hasattr(row, '__getitem__') else row[4],
                'origin_peer': row['origin_peer'] if hasattr(row, '__getitem__') else row[5],
                'channel_id': row['channel_id'] if hasattr(row, '__getitem__') else row[6],
                'preview': row['preview'] if hasattr(row, '__getitem__') else row[7],
                'metadata': metadata,
                'created_at': created_iso,
                'acknowledged_at': ack_iso,
                'status': row['status'] if hasattr(row, '__getitem__') else row[11],
            })
        return results

    def get_mention_by_id(self, mention_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single mention event by ID."""
        if not mention_id:
            return None
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT id, user_id, source_type, source_id, author_id,
                           origin_peer, channel_id, preview, metadata,
                           created_at, acknowledged_at, status
                    FROM mention_events WHERE id = ?
                    """,
                    (mention_id,),
                ).fetchone()
            if not row:
                return None
        except Exception as e:
            logger.error(f"Failed to fetch mention event {mention_id}: {e}")
            return None

        try:
            metadata = json.loads(row['metadata']) if row['metadata'] else None
        except Exception:
            metadata = None

        def _iso(val: Any) -> Any:
            if not val:
                return val
            try:
                dt = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                return val

        return {
            'id': row['id'] if hasattr(row, '__getitem__') else row[0],
            'user_id': row['user_id'] if hasattr(row, '__getitem__') else row[1],
            'source_type': row['source_type'] if hasattr(row, '__getitem__') else row[2],
            'source_id': row['source_id'] if hasattr(row, '__getitem__') else row[3],
            'author_id': row['author_id'] if hasattr(row, '__getitem__') else row[4],
            'origin_peer': row['origin_peer'] if hasattr(row, '__getitem__') else row[5],
            'channel_id': row['channel_id'] if hasattr(row, '__getitem__') else row[6],
            'preview': row['preview'] if hasattr(row, '__getitem__') else row[7],
            'metadata': metadata,
            'created_at': _iso(row['created_at'] if hasattr(row, '__getitem__') else row[9]),
            'acknowledged_at': _iso(row['acknowledged_at'] if hasattr(row, '__getitem__') else row[10]),
            'status': row['status'] if hasattr(row, '__getitem__') else row[11],
        }

    def acknowledge_mentions(self, user_id: str, mention_ids: Sequence[str]) -> int:
        """Mark mention events as acknowledged."""
        ids = [mid for mid in (mention_ids or []) if mid]
        if not user_id or not ids:
            return 0
        try:
            with self.db.get_connection() as conn:
                placeholders = ",".join("?" for _ in ids)
                params = [user_id] + ids
                cur = conn.execute(
                    f"""
                    UPDATE mention_events
                    SET acknowledged_at = CURRENT_TIMESTAMP, status = 'acknowledged'
                    WHERE user_id = ? AND id IN ({placeholders})
                    """,
                    params,
                )
                conn.commit()
                return cur.rowcount or 0
        except Exception as e:
            logger.error(f"Failed to acknowledge mention events: {e}")
            return 0


def record_mention_activity(
    mention_manager: Optional[MentionManager],
    p2p_manager: Any,
    target_ids: Sequence[str],
    source_type: str,
    source_id: str,
    author_id: Optional[str],
    origin_peer: Optional[str],
    channel_id: Optional[str],
    preview: str,
    extra_ref: Optional[Dict[str, Any]] = None,
    inbox_manager: Any = None,
    source_content: Optional[str] = None,
) -> None:
    """Persist mention events and surface a UI activity notification."""
    if mention_manager and target_ids:
        mention_manager.record_mentions(
            user_ids=target_ids,
            source_type=source_type,
            source_id=source_id,
            author_id=author_id,
            origin_peer=origin_peer,
            channel_id=channel_id,
            preview=preview,
            metadata=extra_ref,
        )

    if inbox_manager and target_ids:
        try:
            inbox_manager.record_mention_triggers(
                target_ids=target_ids,
                source_type=source_type,
                source_id=source_id,
                author_id=author_id,
                origin_peer=origin_peer,
                channel_id=channel_id,
                preview=preview,
                extra_ref=extra_ref,
                source_content=source_content,
            )
        except Exception as e:
            logger.debug(f"Inbox trigger creation failed: {e}")

    if p2p_manager and target_ids:
        try:
            ref = dict(extra_ref or {})
            ref.setdefault('mention_targets', list(target_ids))
            if source_type == 'channel_message':
                ref.setdefault('message_id', source_id)
                ref.setdefault('channel_id', channel_id)
                ref.setdefault('user_id', author_id)
            elif source_type == 'feed_post':
                ref.setdefault('post_id', source_id)
                ref.setdefault('author_id', author_id)

            event_id = f"MN:{source_id or secrets.token_hex(6)}"
            p2p_manager.record_activity_event({
                'id': event_id,
                'peer_id': origin_peer or '',
                'kind': 'mention',
                'timestamp': datetime.now(timezone.utc).timestamp(),
                'preview': preview,
                'ref': ref,
            })
        except Exception:
            pass


def broadcast_mention_interaction(
    p2p_manager: Any,
    source_type: str,
    source_id: str,
    author_id: str,
    target_user_ids: Sequence[str],
    preview: str,
    channel_id: Optional[str] = None,
    origin_peer: Optional[str] = None,
) -> None:
    """Send mention events to peers via the interaction channel."""
    if not p2p_manager or not target_user_ids:
        return

    extra = {
        'action': 'mention',
        'source_type': source_type,
        'source_id': source_id,
        'author_id': author_id,
        'target_user_ids': list(dict.fromkeys([tid for tid in target_user_ids if tid])),
        'preview': preview,
        'origin_peer': origin_peer,
    }
    if channel_id:
        extra['channel_id'] = channel_id

    try:
        p2p_manager.broadcast_interaction(
            item_id=source_id,
            user_id=author_id,
            action='mention',
            item_type=source_type,
            extra=extra,
        )
    except Exception:
        pass
