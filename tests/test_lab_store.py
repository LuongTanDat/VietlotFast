import copy
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from ai import lab_store as store


class LabStoreTests(unittest.TestCase):
    GAME = "LOTO_5_35"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "algorithm_lab.db"
        self.payload = {"ok": True, "status": "completed", "scope": "historical_diagnostic", "type": self.GAME,
                        "parameters": {"ticketCount": 3, "validationCount": 10, "testCount": 20},
                        "selection": {"selectedMethod": "random", "candidateProfileId": "short_stable", "candidateLabel": "Ngắn hạn"},
                        "conclusion": {"status": "insufficient_evidence", "summary": "Chưa đủ kỳ"}}
        self.created, self.finished = "2026-10-06T01:00:00Z", "2026-10-06T01:00:03Z"

    def save(self, owner="owner", run_id="run-1", payload=None):
        return store.save_run(owner, self.GAME, run_id, payload or self.payload, self.created, self.finished, self.db)

    def test_empty_overview_does_not_create_database_or_any_file(self):
        result = store.overview("owner", self.GAME, db_path=self.db)
        self.assertIsNone(result["job"])
        self.assertEqual(result["history"], [])
        self.assertIsNone(result["tracking"]["candidate"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_persisted_completed_report_survives_connections_and_is_owner_game_scoped(self):
        self.save()
        self.assertEqual(store.get_run("owner", self.GAME, "run-1", self.db)["report"], self.payload)
        self.assertIsNone(store.get_run("other", self.GAME, "run-1", self.db))
        self.assertIsNone(store.get_run("owner", "LOTO_6_45", "run-1", self.db))
        self.assertIsNone(store.job("other", self.GAME, "run-1", self.db))
        self.assertEqual(store.history("other", self.GAME, db_path=self.db), [])
        self.assertTrue(store.job("owner", self.GAME, "run-1", self.db)["persisted"])
        self.assertEqual(store.job("owner", self.GAME, "run-1", self.db)["report"], self.payload)
        self.assertEqual(store.history("owner", self.GAME, db_path=self.db)[0]["candidateProfileId"], "short_stable")

    def test_idempotent_save_cannot_overwrite_or_reassign_existing_run(self):
        self.assertEqual(self.save()["reportHash"], self.save()["reportHash"])
        altered = copy.deepcopy(self.payload)
        altered["parameters"]["ticketCount"] = 8
        for owner, payload in (("owner", altered), ("other", self.payload)):
            with self.assertRaisesRegex(ValueError, "không ghi đè"):
                self.save(owner=owner, payload=payload)
        with closing(store.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM lab_runs").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE lab_runs SET owner='other'")

    def test_rejects_incomplete_wrong_game_nonfinite_or_invalid_timestamp(self):
        for changes in ({"ok": False}, {"status": "running"}, {"scope": "prospective"},
                        {"type": "LOTO_6_45"}, {"metric": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.save(payload={**self.payload, **changes})
        with self.assertRaises(ValueError):
            store.save_run("owner", self.GAME, "run-1", self.payload, self.finished, self.created, self.db)
        with self.assertRaises(ValueError):
            store.save_run("owner", self.GAME, "run-1", self.payload, "2026-10-06T01:00:00", self.finished, self.db)
        self.assertFalse(self.db.exists())

    def test_checksum_corruption_is_reported_instead_of_used(self):
        self.save()
        with closing(store.connect(self.db)) as connection:
            connection.execute("DROP TRIGGER lab_run_immutable")
            connection.execute("UPDATE lab_runs SET report_hash='corrupt'")
        with self.assertRaisesRegex(ValueError, "Checksum"):
            store.get_run("owner", self.GAME, "run-1", self.db)

    def test_history_uses_compact_immutable_projection_and_older_database_stays_readable(self):
        self.save()
        with closing(store.connect(self.db)) as connection:
            self.assertIsNotNone(connection.execute("SELECT * FROM lab_run_metadata").fetchone())
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE lab_run_metadata SET metadata_json='{}'")
        from unittest import mock
        with mock.patch.object(store, "_report", side_effect=AssertionError("must not parse full historical reports")):
            self.assertEqual(store.history("owner", self.GAME, db_path=self.db)[0]["candidateLabel"], "Ngắn hạn")
        with closing(store.connect(self.db)) as connection:
            connection.execute("DROP TABLE lab_run_metadata")
        self.assertEqual(store.history("owner", self.GAME, db_path=self.db)[0]["id"], "run-1")
        self.assertEqual(store.job("owner", self.GAME, db_path=self.db)["report"], self.payload)

    def test_cli_save_and_overview_keep_one_json_object(self):
        path = self.root / "report.json"
        path.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            code = store.main(["--action=save", "--owner=owner", f"--game={self.GAME}", "--run-id=run-1",
                               f"--created-at={self.created}", f"--finished-at={self.finished}",
                               f"--report-file={path}", f"--db-path={self.db}"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["persisted"])
        output = io.StringIO()
        with redirect_stdout(output):
            code = store.main(["--action=overview", "--owner=owner", f"--game={self.GAME}", f"--db-path={self.db}"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["job"]["report"], self.payload)


if __name__ == "__main__":
    unittest.main()
