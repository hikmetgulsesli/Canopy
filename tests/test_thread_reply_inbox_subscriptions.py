"""Regression tests for thread reply inbox subscriptions and mute behavior."""

import json
import os
import sqlite3
import sys
import types
import unittest
from unittest.mock import MagicMock

# Ensure repository root is importable when running tests directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Provide a lightweight zeroconf stub for environments without optional deps.
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

from canopy.core.channels import ChannelManager, ChannelType
from canopy.core.inbox import InboxManager
from canopy.core.mentions import record_thread_reply_activity


class _FakeDbManager:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
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
                origin_peer TEXT,
                agent_directives TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.conn.executemany(
            """
            INSERT INTO users (
                id, username, display_name, public_key, password_hash, account_type, status, origin_peer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ('author', 'author', 'Author', 'pk-author', 'pw', 'agent', 'active', None),
                ('replier', 'replier', 'Replier', 'pk-replier', 'pw', 'agent', 'active', None),
                ('follower', 'follower', 'Follower', 'pk-follower', 'pw', 'agent', 'active', None),
            ],
        )
        self.conn.commit()

    def get_connection(self):
        return self.conn

    def get_instance_owner_user_id(self):
        return 'author'

    def get_user(self, user_id: str):
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


class TestThreadReplyInboxSubscriptions(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDbManager()
        self.channel_manager = ChannelManager(self.db, MagicMock())
        self.inbox_manager = InboxManager(self.db)

        channel = self.channel_manager.create_channel(
            name='thread-replies',
            channel_type=ChannelType.PUBLIC,
            created_by='author',
            description='reply notification tests',
            privacy_mode='open',
        )
        self.assertIsNotNone(channel)
        assert channel is not None
        self.channel_id = channel.id

        self.assertTrue(self.channel_manager.add_member(self.channel_id, 'replier', 'author'))
        self.assertTrue(self.channel_manager.add_member(self.channel_id, 'follower', 'author'))

        root = self.channel_manager.send_message(
            channel_id=self.channel_id,
            user_id='author',
            content='Root thread message',
        )
        self.assertIsNotNone(root)
        assert root is not None
        self.root_id = root.id

    def tearDown(self) -> None:
        self.db.conn.close()

    def _disable_inbox_cooldowns(self) -> None:
        for uid in ('author', 'follower', 'replier'):
            self.inbox_manager.set_config(
                uid,
                {
                    'cooldown_seconds': 0,
                    'sender_cooldown_seconds': 0,
                    'agent_sender_cooldown_seconds': 0,
                },
            )

    def test_reply_notifies_root_author_by_default_and_other_subscribers(self) -> None:
        self._disable_inbox_cooldowns()
        sub = self.channel_manager.set_thread_subscription(
            user_id='follower',
            channel_id=self.channel_id,
            message_id=self.root_id,
            subscribed=True,
            source='manual',
        )
        self.assertTrue(sub.get('success'))

        result = record_thread_reply_activity(
            channel_manager=self.channel_manager,
            inbox_manager=self.inbox_manager,
            channel_id=self.channel_id,
            reply_message_id='Mreply-default',
            parent_message_id=self.root_id,
            author_id='replier',
            origin_peer='peer-a',
            source_content='reply payload',
            mentioned_user_ids=[],
        )

        self.assertEqual(result.get('thread_root_message_id'), self.root_id)
        recipients = [
            row['agent_user_id']
            for row in self.db.conn.execute(
                """
                SELECT agent_user_id
                FROM agent_inbox
                WHERE source_id = ? AND trigger_type = 'reply'
                ORDER BY agent_user_id
                """,
                ('Mreply-default',),
            ).fetchall()
        ]
        self.assertEqual(recipients, ['author', 'follower'])

    def test_muted_root_author_does_not_receive_reply_notifications(self) -> None:
        self._disable_inbox_cooldowns()
        self.channel_manager.set_thread_subscription(
            user_id='follower',
            channel_id=self.channel_id,
            message_id=self.root_id,
            subscribed=True,
            source='manual',
        )
        self.channel_manager.set_thread_subscription(
            user_id='author',
            channel_id=self.channel_id,
            message_id=self.root_id,
            subscribed=False,
            source='manual',
        )

        record_thread_reply_activity(
            channel_manager=self.channel_manager,
            inbox_manager=self.inbox_manager,
            channel_id=self.channel_id,
            reply_message_id='Mreply-muted',
            parent_message_id=self.root_id,
            author_id='replier',
            origin_peer='peer-a',
            source_content='reply payload',
            mentioned_user_ids=[],
        )

        recipients = [
            row['agent_user_id']
            for row in self.db.conn.execute(
                """
                SELECT agent_user_id
                FROM agent_inbox
                WHERE source_id = ? AND trigger_type = 'reply'
                ORDER BY agent_user_id
                """,
                ('Mreply-muted',),
            ).fetchall()
        ]
        self.assertEqual(recipients, ['follower'])

    def test_reply_notification_skips_users_already_mentioned(self) -> None:
        self._disable_inbox_cooldowns()
        self.channel_manager.set_thread_subscription(
            user_id='follower',
            channel_id=self.channel_id,
            message_id=self.root_id,
            subscribed=True,
            source='manual',
        )

        record_thread_reply_activity(
            channel_manager=self.channel_manager,
            inbox_manager=self.inbox_manager,
            channel_id=self.channel_id,
            reply_message_id='Mreply-mentioned',
            parent_message_id=self.root_id,
            author_id='replier',
            origin_peer='peer-a',
            source_content='@author explicit mention in reply',
            mentioned_user_ids=['author'],
        )

        recipients = [
            row['agent_user_id']
            for row in self.db.conn.execute(
                """
                SELECT agent_user_id
                FROM agent_inbox
                WHERE source_id = ? AND trigger_type = 'reply'
                ORDER BY agent_user_id
                """,
                ('Mreply-mentioned',),
            ).fetchall()
        ]
        self.assertEqual(recipients, ['follower'])

    def test_legacy_inbox_config_auto_adds_reply_trigger(self) -> None:
        legacy = {
            'allowed_trigger_types': ['mention', 'dm'],
            'cooldown_seconds': 0,
        }
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO agent_inbox_config (user_id, config_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            ('author', json.dumps(legacy)),
        )
        self.db.conn.commit()

        cfg = self.inbox_manager.get_config('author')
        self.assertIn('reply', cfg.get('allowed_trigger_types') or [])
        self.assertTrue(bool(cfg.get('thread_reply_notifications')))


if __name__ == '__main__':
    unittest.main()
