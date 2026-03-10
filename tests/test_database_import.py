"""Regression tests for settings database import flow."""

import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from io import BytesIO
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


class _FileDbManager:
    def __init__(self, db_path: Path, owner_user_id: str = 'test-user') -> None:
        self.db_path = db_path
        self._owner_user_id = owner_user_id
        self.last_backup_path = None

    @contextmanager
    def get_connection(self, busy_timeout_ms=None, use_pool=False):
        timeout_ms = busy_timeout_ms if busy_timeout_ms is not None else 3000
        conn = sqlite3.connect(self.db_path, timeout=timeout_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def close_pooled_connection(self):
        return None

    def get_instance_owner_user_id(self):
        return self._owner_user_id

    def backup_database(self, suffix: str = 'backup') -> Path:
        backup_path = self.db_path.parent / f"{self.db_path.stem}_{suffix}_{int(time.time() * 1000)}.db"
        src = sqlite3.connect(str(self.db_path))
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        self.last_backup_path = backup_path
        return backup_path

    def _initialize_database(self):
        with self.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    public_key TEXT,
                    password_hash TEXT
                )
                """
            )


class TestDatabaseImport(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        self.db_path = Path(self.tempdir.name) / 'canopy.db'
        self._seed_current_db(user_id='before-user', username='before')

        self.db_manager = _FileDbManager(self.db_path, owner_user_id='test-user')

        components = (
            self.db_manager,          # db_manager
            MagicMock(),             # api_key_manager
            MagicMock(),             # trust_manager
            MagicMock(),             # message_manager
            MagicMock(),             # channel_manager
            MagicMock(),             # file_manager
            MagicMock(),             # feed_manager
            MagicMock(),             # interaction_manager
            MagicMock(),             # profile_manager
            MagicMock(),             # config
            MagicMock(),             # p2p_manager
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

        self.client = app.test_client()

    def _seed_current_db(self, user_id: str, username: str) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    public_key TEXT,
                    password_hash TEXT
                );
                DELETE FROM users;
                """
            )
            conn.execute(
                'INSERT INTO users (id, username, public_key, password_hash) VALUES (?, ?, ?, ?)',
                (user_id, username, 'pk', 'ph'),
            )
            conn.commit()
        finally:
            conn.close()

    def _build_sqlite_file_bytes(self, *, with_users: bool, user_id: str = 'import-user', username: str = 'imported') -> bytes:
        temp_db = Path(self.tempdir.name) / f'import_{int(time.time() * 1000)}.db'
        conn = sqlite3.connect(str(temp_db))
        try:
            if with_users:
                conn.executescript(
                    """
                    CREATE TABLE users (
                        id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        public_key TEXT,
                        password_hash TEXT
                    );
                    """
                )
                conn.execute(
                    'INSERT INTO users (id, username, public_key, password_hash) VALUES (?, ?, ?, ?)',
                    (user_id, username, 'pk-import', 'ph-import'),
                )
            else:
                conn.executescript(
                    """
                    CREATE TABLE notes (
                        id INTEGER PRIMARY KEY,
                        body TEXT
                    );
                    INSERT INTO notes (body) VALUES ('not a canopy db');
                    """
                )
            conn.commit()
        finally:
            conn.close()

        data = temp_db.read_bytes()
        temp_db.unlink(missing_ok=True)
        return data

    def _set_authenticated_session(self, csrf_token: str = 'csrf-test-token', user_id: str = 'test-user') -> None:
        with self.client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['user_id'] = user_id
            sess['_csrf_token'] = csrf_token

    def _get_single_username(self) -> str:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute('SELECT username FROM users ORDER BY username LIMIT 1').fetchone()
            return row['username'] if row else ''
        finally:
            conn.close()

    def test_database_import_requires_csrf(self) -> None:
        self._set_authenticated_session()
        payload = self._build_sqlite_file_bytes(with_users=True)

        response = self.client.post(
            '/ajax/database_import',
            data={
                'confirm_phrase': 'IMPORT DATABASE',
                'database': (BytesIO(payload), 'import.db'),
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 403)

    def test_database_import_requires_admin(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token, user_id='not-admin')
        payload = self._build_sqlite_file_bytes(with_users=True)

        response = self.client.post(
            '/ajax/database_import',
            data={
                'confirm_phrase': 'IMPORT DATABASE',
                'database': (BytesIO(payload), 'import.db'),
            },
            content_type='multipart/form-data',
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 403)
        body = response.get_json() or {}
        self.assertIn('admin', (body.get('error') or '').lower())

    def test_database_import_rejects_bad_confirmation_phrase(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)
        payload = self._build_sqlite_file_bytes(with_users=True)

        response = self.client.post(
            '/ajax/database_import',
            data={
                'confirm_phrase': 'NOPE',
                'database': (BytesIO(payload), 'import.db'),
            },
            content_type='multipart/form-data',
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 400)
        body = response.get_json() or {}
        self.assertIn('confirmation', (body.get('error') or '').lower())

    def test_database_import_rejects_non_sqlite_file(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)

        response = self.client.post(
            '/ajax/database_import',
            data={
                'confirm_phrase': 'IMPORT DATABASE',
                'database': (BytesIO(b'not-a-sqlite-db'), 'broken.db'),
            },
            content_type='multipart/form-data',
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 400)
        body = response.get_json() or {}
        self.assertIn('sqlite', (body.get('error') or '').lower())

    def test_database_import_rejects_missing_users_table(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)
        payload = self._build_sqlite_file_bytes(with_users=False)

        response = self.client.post(
            '/ajax/database_import',
            data={
                'confirm_phrase': 'IMPORT DATABASE',
                'database': (BytesIO(payload), 'import.db'),
            },
            content_type='multipart/form-data',
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 400)
        body = response.get_json() or {}
        self.assertIn('users', (body.get('error') or '').lower())
        self.assertEqual(self._get_single_username(), 'before')

    def test_database_import_successfully_replaces_database_and_creates_backup(self) -> None:
        csrf_token = 'csrf-ok'
        self._set_authenticated_session(csrf_token=csrf_token)
        payload = self._build_sqlite_file_bytes(with_users=True, user_id='after-user', username='after')

        response = self.client.post(
            '/ajax/database_import',
            data={
                'confirm_phrase': 'IMPORT DATABASE',
                'database': (BytesIO(payload), 'import.db'),
            },
            content_type='multipart/form-data',
            headers={'X-CSRFToken': csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json() or {}
        self.assertTrue(body.get('success'))
        self.assertIn('backup', (body.get('message') or '').lower())

        self.assertEqual(self._get_single_username(), 'after')
        self.assertIsNotNone(self.db_manager.last_backup_path)
        self.assertTrue(Path(self.db_manager.last_backup_path).exists())


if __name__ == '__main__':
    unittest.main()
