"""Regression test: registration should auto-join only open public channels."""

import os
import sqlite3
import sys
import types
import unittest

from flask import Flask

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

from canopy.ui.routes import create_ui_blueprint


class _FakeDbManager:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                public_key TEXT,
                password_hash TEXT,
                display_name TEXT
            );

            CREATE TABLE user_keys (
                user_id TEXT PRIMARY KEY,
                ed25519_pub TEXT,
                ed25519_priv TEXT,
                x25519_pub TEXT,
                x25519_priv TEXT
            );

            CREATE TABLE channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                created_by TEXT NOT NULL,
                description TEXT,
                privacy_mode TEXT
            );

            CREATE TABLE channel_members (
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                UNIQUE(channel_id, user_id)
            );
            """
        )
        self.conn.executemany(
            """
            INSERT INTO channels (id, name, channel_type, created_by, description, privacy_mode)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ('general', 'general', 'public', 'system', 'General', 'open'),
                ('Copen', 'open-room', 'public', 'owner', 'Open room', 'open'),
                ('Crestricted', 'restricted-room', 'public', 'owner', 'Restricted room', 'private'),
            ],
        )
        self.conn.commit()

    def get_connection(self):
        return self.conn

    def has_any_registered_users(self):
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE COALESCE(password_hash, '') != ''"
        ).fetchone()
        return bool((row['n'] if row else 0) > 0)

    def get_user_by_username(self, username: str):
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None

    def create_user(self, user_id: str, username: str, public_key: str, password_hash: str, display_name: str):
        try:
            self.conn.execute(
                """
                INSERT INTO users (id, username, public_key, password_hash, display_name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, public_key, password_hash, display_name),
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def store_user_keys(self, user_id: str, ed25519_pub: str, ed25519_priv: str, x25519_pub: str, x25519_priv: str):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO user_keys
            (user_id, ed25519_pub, ed25519_priv, x25519_pub, x25519_priv)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, ed25519_pub, ed25519_priv, x25519_pub, x25519_priv),
        )
        self.conn.commit()


class TestRegisterChannelMembershipPrivacy(unittest.TestCase):
    def setUp(self) -> None:
        self.db_manager = _FakeDbManager()

        app = Flask(__name__)
        app.config['TESTING'] = True
        app.secret_key = 'test-secret'
        app.config['DB_MANAGER'] = self.db_manager
        app.register_blueprint(create_ui_blueprint())
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.db_manager.conn.close()

    def test_register_joins_only_open_public_channels(self) -> None:
        response = self.client.post(
            '/register',
            data={
                'username': 'new_user',
                'display_name': 'New User',
                'password': 'StrongPass123!',
                'password_confirm': 'StrongPass123!',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        row = self.db_manager.conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ('new_user',),
        ).fetchone()
        self.assertIsNotNone(row)
        user_id = row['id']

        memberships = self.db_manager.conn.execute(
            "SELECT channel_id FROM channel_members WHERE user_id = ? ORDER BY channel_id",
            (user_id,),
        ).fetchall()
        channel_ids = [m['channel_id'] for m in memberships]

        self.assertIn('general', channel_ids)
        self.assertIn('Copen', channel_ids)
        self.assertNotIn('Crestricted', channel_ids)


if __name__ == '__main__':
    unittest.main()
