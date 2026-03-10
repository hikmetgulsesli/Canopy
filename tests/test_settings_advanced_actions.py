"""Regression tests for settings advanced actions (cleanup/export/reset)."""

import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def __init__(self, conn: sqlite3.Connection, workdir: str) -> None:
        self._conn = conn
        self._workdir = Path(workdir)
        self.cleanup_days = None

    def get_connection(self) -> sqlite3.Connection:
        return self._conn

    def cleanup_old_data(self, days: int) -> None:
        self.cleanup_days = days

    def backup_database(self, suffix: str = 'backup') -> Path:
        backup_path = self._workdir / f'canopy_{suffix}.db'
        dst = sqlite3.connect(str(backup_path))
        self._conn.backup(dst)
        dst.close()
        return backup_path


class TestSettingsAdvancedActions(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE channel_messages (id INTEGER PRIMARY KEY, user_id TEXT);
            CREATE TABLE channel_members (id INTEGER PRIMARY KEY, user_id TEXT, channel_id TEXT);
            CREATE TABLE feed_posts (id INTEGER PRIMARY KEY, author_id TEXT, content TEXT);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, sender_id TEXT, content TEXT);
            CREATE TABLE trust_scores (id INTEGER PRIMARY KEY, peer_id TEXT, score INTEGER);
            CREATE TABLE delete_signals (id INTEGER PRIMARY KEY, target_peer_id TEXT, data_type TEXT, data_id TEXT);
            CREATE TABLE processed_messages (id INTEGER PRIMARY KEY, message_hash TEXT);
            """
        )
        self.conn.executemany(
            'INSERT INTO channel_messages (user_id) VALUES (?)',
            [('u1',), ('u2',)],
        )
        self.conn.executemany(
            'INSERT INTO channel_members (user_id, channel_id) VALUES (?, ?)',
            [('system', 'general'), ('u1', 'general')],
        )
        self.conn.executemany(
            'INSERT INTO feed_posts (author_id, content) VALUES (?, ?)',
            [('u1', 'post')],
        )
        self.conn.executemany(
            'INSERT INTO messages (sender_id, content) VALUES (?, ?)',
            [('u1', 'dm')],
        )
        self.conn.executemany(
            'INSERT INTO trust_scores (peer_id, score) VALUES (?, ?)',
            [('peer-a', 80)],
        )
        self.conn.executemany(
            'INSERT INTO delete_signals (target_peer_id, data_type, data_id) VALUES (?, ?, ?)',
            [('peer-a', 'message', 'm1')],
        )
        self.conn.executemany(
            'INSERT INTO processed_messages (message_hash) VALUES (?)',
            [('hash-a',)],
        )
        self.conn.commit()

        self.db_manager = _FakeDbManager(self.conn, self.tempdir.name)
        channel_manager = MagicMock()
        channel_manager.prune_processed_messages.return_value = 4

        # Order must match get_app_components in canopy.core.utils.
        components = (
            self.db_manager,          # db_manager
            MagicMock(),              # api_key_manager
            MagicMock(),              # trust_manager
            MagicMock(),              # message_manager
            channel_manager,          # channel_manager
            MagicMock(),              # file_manager
            MagicMock(),              # feed_manager
            MagicMock(),              # interaction_manager
            MagicMock(),              # profile_manager
            MagicMock(),              # config
            MagicMock(),              # p2p_manager
        )

        self.get_components_patcher = patch(
            'canopy.ui.routes.get_app_components',
            return_value=components,
        )
        self.get_components_patcher.start()
        self.addCleanup(self.get_components_patcher.stop)

        app = Flask(__name__)
        app.config['TESTING'] = True
        app.secret_key = 'test-secret'
        app.register_blueprint(create_ui_blueprint())

        self.app = app
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.conn.close()

    def _set_authenticated_session(self, csrf_token: str = 'csrf-test-token') -> None:
        with self.client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['user_id'] = 'test-user'
            sess['_csrf_token'] = csrf_token

    def _count(self, table_name: str) -> int:
        row = self.conn.execute(f'SELECT COUNT(*) AS cnt FROM {table_name}').fetchone()
        return int((row['cnt'] if row else 0) or 0)

    def test_database_cleanup_requires_csrf(self) -> None:
        self._set_authenticated_session()
        response = self.client.post('/ajax/database_cleanup', json={'days': 30})
        self.assertEqual(response.status_code, 403)

    def test_database_cleanup_succeeds_with_csrf(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)

        response = self.client.post(
            '/ajax/database_cleanup',
            json={'days': 30},
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(self.db_manager.cleanup_days, 30)

    def test_database_export_returns_attachment(self) -> None:
        self._set_authenticated_session()

        response = self.client.get('/ajax/database_export')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/x-sqlite3')
        disposition = response.headers.get('Content-Disposition') or ''
        self.assertIn('attachment', disposition)
        self.assertIn('.db', disposition)
        self.assertGreater(len(response.data), 0)

    def test_system_reset_requires_csrf(self) -> None:
        self._set_authenticated_session()
        response = self.client.post('/ajax/system_reset')
        self.assertEqual(response.status_code, 403)

    def test_system_reset_succeeds_with_csrf(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)

        response = self.client.post(
            '/ajax/system_reset',
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('success'))

        self.assertEqual(self._count('channel_messages'), 0)
        self.assertEqual(self._count('feed_posts'), 0)
        self.assertEqual(self._count('messages'), 0)
        self.assertEqual(self._count('trust_scores'), 0)
        self.assertEqual(self._count('delete_signals'), 0)
        self.assertEqual(self._count('processed_messages'), 0)
        self.assertEqual(self._count('channel_members'), 1)

    def test_set_landing_requires_csrf(self) -> None:
        self._set_authenticated_session()
        response = self.client.post('/ajax/set_landing', json={'page': 'feed'})
        self.assertEqual(response.status_code, 403)

    def test_set_landing_succeeds_with_csrf_and_sets_cookie(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)

        response = self.client.post(
            '/ajax/set_landing',
            json={'page': 'feed'},
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('landing'), 'feed')
        cookie = response.headers.get('Set-Cookie') or ''
        self.assertIn('canopy_landing=feed', cookie)


if __name__ == '__main__':
    unittest.main()
