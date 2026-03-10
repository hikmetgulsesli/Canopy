"""Regression tests for edit-driven mention/inbox payload refresh."""

import json
import os
import sqlite3
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

if 'zeroconf' not in sys.modules:
    zeroconf_stub = types.ModuleType('zeroconf')

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

    zeroconf_stub.ServiceBrowser = _Dummy
    zeroconf_stub.ServiceInfo = _Dummy
    zeroconf_stub.Zeroconf = _Dummy
    zeroconf_stub.ServiceStateChange = _Dummy
    sys.modules['zeroconf'] = zeroconf_stub

from canopy.core.inbox import InboxManager
from canopy.core.mentions import MentionManager, record_mention_activity, sync_edited_mention_activity


class _FakeDbManager:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                public_key TEXT,
                password_hash TEXT,
                account_type TEXT DEFAULT 'human',
                status TEXT DEFAULT 'active',
                origin_peer TEXT
            );
            CREATE TABLE channel_members (
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                notifications_enabled INTEGER DEFAULT 1
            );
            """
        )
        self.conn.executemany(
            """
            INSERT INTO users (id, username, display_name, public_key, password_hash, account_type, status, origin_peer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ('author', 'author', 'Author', 'pk-author', 'pw', 'human', 'active', None),
                ('agent_one', 'agent_one', 'Agent One', 'pk-one', 'pw', 'agent', 'active', None),
                ('agent_two', 'agent_two', 'Agent Two', 'pk-two', 'pw', 'agent', 'active', None),
            ],
        )
        self.conn.executemany(
            "INSERT INTO channel_members (channel_id, user_id, role, notifications_enabled) VALUES (?, ?, ?, ?)",
            [
                ('Csync', 'author', 'admin', 1),
                ('Csync', 'agent_one', 'member', 0),
                ('Csync', 'agent_two', 'member', 1),
            ],
        )
        self.conn.commit()

    def get_connection(self):
        return self.conn


class _FakeP2PManager:
    def get_peer_id(self) -> str:
        return 'peer-local'


class TestEditedMentionPayloadRefresh(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDbManager()
        self.mention_manager = MentionManager(self.db)
        self.inbox_manager = InboxManager(self.db)
        self.p2p_manager = _FakeP2PManager()
        for uid in ('agent_one', 'agent_two', 'author'):
            self.inbox_manager.set_config(
                uid,
                {
                    'cooldown_seconds': 0,
                    'sender_cooldown_seconds': 0,
                    'agent_sender_cooldown_seconds': 0,
                    'channel_burst_limit': 100,
                    'channel_hourly_limit': 1000,
                    'sender_hourly_limit': 1000,
                },
            )

    def tearDown(self) -> None:
        self.db.conn.close()

    def test_feed_edit_refresh_updates_payloads_and_creates_new_target(self) -> None:
        record_mention_activity(
            mention_manager=self.mention_manager,
            p2p_manager=None,
            target_ids=['agent_one'],
            source_type='feed_post',
            source_id='FP-edit',
            author_id='author',
            origin_peer='peer-local',
            channel_id=None,
            preview='Initial mention',
            extra_ref={'post_id': 'FP-edit'},
            inbox_manager=self.inbox_manager,
            source_content='Initial @agent_one draft',
        )

        sync_edited_mention_activity(
            db_manager=self.db,
            mention_manager=self.mention_manager,
            inbox_manager=self.inbox_manager,
            p2p_manager=self.p2p_manager,
            content='Edited for @agent_two only',
            source_type='feed_post',
            source_id='FP-edit',
            author_id='author',
            origin_peer='peer-local',
            visibility='network',
            permissions=None,
            edited_at='2026-03-07T10:00:00+00:00',
        )

        old_mention = self.db.conn.execute(
            "SELECT preview, metadata FROM mention_events WHERE user_id = ? AND source_id = ?",
            ('agent_one', 'FP-edit'),
        ).fetchone()
        self.assertIsNotNone(old_mention)
        old_meta = json.loads(old_mention['metadata'])
        self.assertFalse(old_meta.get('still_mentioned'))
        self.assertEqual(old_meta.get('content'), 'Edited for @agent_two only')
        self.assertEqual(old_meta.get('edited_at'), '2026-03-07T10:00:00+00:00')
        self.assertEqual(old_mention['preview'], 'Edited for @agent_two only')

        new_mention = self.db.conn.execute(
            "SELECT preview, metadata FROM mention_events WHERE user_id = ? AND source_id = ?",
            ('agent_two', 'FP-edit'),
        ).fetchone()
        self.assertIsNotNone(new_mention)
        new_meta = json.loads(new_mention['metadata'])
        self.assertTrue(new_meta.get('still_mentioned'))
        self.assertEqual(new_meta.get('content'), 'Edited for @agent_two only')
        self.assertEqual(new_meta.get('post_id'), 'FP-edit')

        old_inbox = self.db.conn.execute(
            "SELECT payload_json FROM agent_inbox WHERE agent_user_id = ? AND source_id = ? AND trigger_type = 'mention'",
            ('agent_one', 'FP-edit'),
        ).fetchone()
        self.assertIsNotNone(old_inbox)
        old_payload = json.loads(old_inbox['payload_json'])
        self.assertFalse(old_payload.get('still_mentioned'))
        self.assertEqual(old_payload.get('content'), 'Edited for @agent_two only')
        self.assertEqual(old_payload.get('edited_at'), '2026-03-07T10:00:00+00:00')

        new_inbox = self.db.conn.execute(
            "SELECT payload_json FROM agent_inbox WHERE agent_user_id = ? AND source_id = ? AND trigger_type = 'mention'",
            ('agent_two', 'FP-edit'),
        ).fetchone()
        self.assertIsNotNone(new_inbox)
        new_payload = json.loads(new_inbox['payload_json'])
        self.assertTrue(new_payload.get('still_mentioned'))
        self.assertEqual(new_payload.get('content'), 'Edited for @agent_two only')

    def test_channel_edit_refresh_respects_channel_mute(self) -> None:
        sync_edited_mention_activity(
            db_manager=self.db,
            mention_manager=self.mention_manager,
            inbox_manager=self.inbox_manager,
            p2p_manager=self.p2p_manager,
            content='Edited message for @agent_one and @agent_two',
            source_type='channel_message',
            source_id='M-edit',
            author_id='author',
            origin_peer='peer-local',
            channel_id='Csync',
            edited_at='2026-03-07T11:00:00+00:00',
        )

        recipients = [
            row['agent_user_id']
            for row in self.db.conn.execute(
                "SELECT agent_user_id FROM agent_inbox WHERE source_id = ? AND trigger_type = 'mention' ORDER BY agent_user_id",
                ('M-edit',),
            ).fetchall()
        ]
        self.assertEqual(recipients, ['agent_two'])

        mention_recipients = [
            row['user_id']
            for row in self.db.conn.execute(
                "SELECT user_id FROM mention_events WHERE source_id = ? ORDER BY user_id",
                ('M-edit',),
            ).fetchall()
        ]
        self.assertEqual(mention_recipients, ['agent_two'])

    def test_reply_and_dm_trigger_refresh_updates_existing_rows_without_duplication(self) -> None:
        reply_id = self.inbox_manager.create_trigger(
            agent_user_id='agent_two',
            source_type='channel_message',
            source_id='M-reply',
            sender_user_id='author',
            channel_id='Csync',
            trigger_type='reply',
            preview='Old reply',
            payload={'content': 'Old reply body', 'message_id': 'M-reply'},
            message_id='M-reply',
        )
        self.assertIsNotNone(reply_id)

        result = self.inbox_manager.sync_source_triggers(
            source_type='channel_message',
            source_id='M-reply',
            trigger_type='reply',
            sender_user_id='author',
            channel_id='Csync',
            preview='New reply body',
            payload={'parent_message_id': 'M-root', 'edited_at': '2026-03-07T12:00:00+00:00'},
            message_id='M-reply',
            source_content='New reply body',
        )
        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['created'], 0)

        reply_row = self.db.conn.execute(
            "SELECT payload_json FROM agent_inbox WHERE source_id = ? AND trigger_type = 'reply'",
            ('M-reply',),
        ).fetchone()
        reply_payload = json.loads(reply_row['payload_json'])
        self.assertEqual(reply_payload.get('content'), 'New reply body')
        self.assertEqual(reply_payload.get('preview'), 'New reply body')
        self.assertEqual(reply_payload.get('parent_message_id'), 'M-root')
        self.assertEqual(reply_payload.get('edited_at'), '2026-03-07T12:00:00+00:00')

        dm_first = self.inbox_manager.sync_source_triggers(
            source_type='dm',
            source_id='DM-edit',
            trigger_type='dm',
            target_ids=['agent_two'],
            sender_user_id='author',
            preview='Original DM',
            payload={'content': 'Original DM', 'message_id': 'DM-edit'},
            message_id='DM-edit',
            source_content='Original DM',
        )
        self.assertEqual(dm_first['created'], 1)

        dm_second = self.inbox_manager.sync_source_triggers(
            source_type='dm',
            source_id='DM-edit',
            trigger_type='dm',
            target_ids=['agent_two'],
            sender_user_id='author',
            preview='Edited DM',
            payload={'content': 'Edited DM', 'message_id': 'DM-edit', 'edited_at': '2026-03-07T12:30:00+00:00'},
            message_id='DM-edit',
            source_content='Edited DM',
        )
        self.assertEqual(dm_second['updated'], 1)
        self.assertEqual(dm_second['created'], 0)

        dm_rows = self.db.conn.execute(
            "SELECT COUNT(*) AS n FROM agent_inbox WHERE source_id = ? AND trigger_type = 'dm'",
            ('DM-edit',),
        ).fetchone()
        self.assertEqual(dm_rows['n'], 1)

        dm_row = self.db.conn.execute(
            "SELECT payload_json FROM agent_inbox WHERE source_id = ? AND trigger_type = 'dm'",
            ('DM-edit',),
        ).fetchone()
        dm_payload = json.loads(dm_row['payload_json'])
        self.assertEqual(dm_payload.get('content'), 'Edited DM')
        self.assertEqual(dm_payload.get('preview'), 'Edited DM')
        self.assertEqual(dm_payload.get('edited_at'), '2026-03-07T12:30:00+00:00')


if __name__ == '__main__':
    unittest.main()
