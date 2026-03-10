"""Regression test for mention-claim race compatibility behavior."""

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

# Ensure repository root is importable when running tests directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from canopy.core.mentions import MentionManager


class _RaceConnection:
    def __init__(self, conn: sqlite3.Connection, manager: "_RaceDbManager") -> None:
        self._conn = conn
        self._manager = manager

    def execute(self, sql: str, params=()):
        normalized = " ".join(sql.strip().split()).lower()
        if self._manager.inject_race_once and normalized.startswith("insert into mention_claims"):
            self._manager.inject_race_once = False

            winner_conn = sqlite3.connect(str(self._manager.db_path))
            winner_conn.row_factory = sqlite3.Row
            winner_conn.execute(
                """
                INSERT INTO mention_claims
                (id, source_type, source_id, channel_id, claimed_by_user_id,
                 claimed_by_username, claimed_at, expires_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "MCL_winner",
                    params[1],  # source_type
                    params[2],  # source_id
                    params[3],  # channel_id
                    "agent-b",
                    "Agent B",
                    params[6],  # claimed_at
                    params[7],  # expires_at
                    params[8],  # metadata
                ),
            )
            winner_conn.commit()
            winner_conn.close()

            raise sqlite3.IntegrityError(
                "UNIQUE constraint failed: mention_claims.source_type, mention_claims.source_id"
            )

        return self._conn.execute(sql, params)

    def executescript(self, script: str):
        return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _RaceDbManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.inject_race_once = False

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield _RaceConnection(conn, self)
        finally:
            conn.close()


class TestMentionClaimRaceCompat(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        self.db_path = Path(self.tempdir.name) / "race_claims.db"
        self.db_manager = _RaceDbManager(self.db_path)
        self.mention_manager = MentionManager(self.db_manager)

    def test_unique_constraint_race_maps_to_already_claimed(self) -> None:
        self.db_manager.inject_race_once = True

        result = self.mention_manager.claim_source(
            source_type="channel_message",
            source_id="msg-race-1",
            claimer_user_id="agent-a",
            claimer_username="Agent A",
            channel_id="general",
            ttl_seconds=120,
        )

        self.assertFalse(result.get("claimed"))
        self.assertEqual(result.get("reason"), "already_claimed")

        claim = result.get("claim") or {}
        self.assertEqual(claim.get("claimed_by_user_id"), "agent-b")
        self.assertEqual(claim.get("claimed_by_username"), "Agent B")
        self.assertTrue(claim.get("active"))


if __name__ == "__main__":
    unittest.main()
