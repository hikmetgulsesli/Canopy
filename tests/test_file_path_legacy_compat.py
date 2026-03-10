"""Regression tests for legacy file path resolution compatibility."""

import hashlib
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

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

from canopy.core.files import FileManager


class _FakeDbManager:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def get_connection(self, *args, **kwargs):
        yield self.conn


class TestFilePathLegacyCompat(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY
            );

            CREATE TABLE files (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size INTEGER NOT NULL,
                uploaded_by TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                checksum TEXT NOT NULL
            );

            CREATE TABLE file_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                accessed_by TEXT NOT NULL,
                accessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_agent TEXT
            );
            """
        )
        self.conn.execute("INSERT INTO users (id) VALUES (?)", ('user-test',))
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_resolves_legacy_relative_device_path(self) -> None:
        device_id = 'dev12345'
        storage_path = self.root / 'data' / 'devices' / device_id / 'files'
        image_dir = storage_path / 'images'
        image_dir.mkdir(parents=True, exist_ok=True)

        file_id = 'Fabc123legacy'
        file_name = f'{file_id}.jpg'
        payload = b'legacy-avatar-bytes'
        checksum = hashlib.sha256(payload).hexdigest()
        (image_dir / file_name).write_bytes(payload)

        legacy_rel = f'data/devices/{device_id}/files/images/{file_name}'
        self.conn.execute(
            """
            INSERT INTO files (
                id, original_name, stored_name, file_path, content_type,
                size, uploaded_by, uploaded_at, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                'avatar.jpg',
                file_name,
                legacy_rel,
                'image/jpeg',
                len(payload),
                'user-test',
                datetime.now(timezone.utc).isoformat(),
                checksum,
            ),
        )
        self.conn.commit()

        fm = FileManager(_FakeDbManager(self.conn), str(storage_path))
        result = fm.get_file_data(file_id)
        self.assertIsNotNone(result)
        raw, info = result
        self.assertEqual(raw, payload)
        self.assertEqual(info.id, file_id)


if __name__ == '__main__':
    unittest.main()
