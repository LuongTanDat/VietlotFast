import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai import ml_pipeline
from ai import prediction_ledger as ledger
from ai.predictors.ai_predict import attach_controlled_probability_metadata, build_prediction_bundles


def sample_prediction(target_draw_id="101"):
    return attach_controlled_probability_metadata({
        "ok": True,
        "type": "LOTO_6_45",
        "target_draw_id": str(target_draw_id),
        "latestKy": "100",
        "engine": "test_engine",
        "modelVersion": "test_v1",
        "topRanking": [1, 2, 3, 4, 5, 6, 7, 8],
        "tickets": [{"main": [1, 2, 3, 4, 5, 6]}],
        "qualityScore": 42.0,
    })


def sample_keno_prediction(target_draw_id="2001", pick_size=5):
    return attach_controlled_probability_metadata({
        "ok": True,
        "type": "KENO",
        "target_draw_id": str(target_draw_id),
        "latestKy": "2000",
        "engine": "test_keno_engine",
        "modelVersion": "keno_test_v1",
        "pickSize": int(pick_size),
        "topRanking": list(range(1, 21)),
        "tickets": [{"main": list(range(1, int(pick_size) + 1)), "special": None}],
        "qualityScore": 31.0,
    })


class PredictionLedgerPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "ledger.db"

    def count_rows(self, table):
        connection = ledger.connect(self.db_path)
        try:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            connection.close()

    def test_migration_creates_required_tables(self):
        ledger.migrate(db_path=self.db_path)
        connection = ledger.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        finally:
            connection.close()

        self.assertTrue({"prediction_runs", "prediction_scores", "model_registry", "training_runs"} <= tables)

    def test_locked_prediction_payload_is_immutable(self):
        locked = ledger.lock_prediction(sample_prediction(), username="tester", db_path=self.db_path)
        connection = ledger.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE prediction_runs SET payload_json = '{}' WHERE prediction_id = ?",
                    (locked["prediction_id"],),
                )
        finally:
            connection.close()

    def test_multiple_predictions_same_draw_do_not_overwrite(self):
        ledger.lock_prediction(sample_prediction(), username="tester", db_path=self.db_path)
        ledger.lock_prediction(sample_prediction(), username="tester", db_path=self.db_path)

        self.assertEqual(2, self.count_rows("prediction_runs"))

    def test_score_pending_is_idempotent(self):
        ledger.lock_prediction(sample_prediction("101"), username="tester", db_path=self.db_path)

        def actual_lookup(game_type, target_draw_id):
            self.assertEqual("LOTO_6_45", game_type)
            return {"ky": target_draw_id, "main": [1, 2, 9, 10, 11, 12]}

        first = ledger.score_pending_predictions("LOTO_6_45", actual_lookup, 45, 6, 6, db_path=self.db_path)
        second = ledger.score_pending_predictions("LOTO_6_45", actual_lookup, 45, 6, 6, db_path=self.db_path)

        self.assertEqual(1, len(first["scored"]))
        self.assertEqual(0, len(second["scored"]))
        self.assertEqual(1, self.count_rows("prediction_scores"))
        self.assertEqual("scored", ledger.list_predictions("LOTO_6_45", limit=1, db_path=self.db_path)[0]["status"])

    def test_prediction_listing_is_scoped_by_username_and_includes_score(self):
        ledger.lock_prediction(sample_prediction("101"), username="alice", db_path=self.db_path)
        ledger.lock_prediction(sample_prediction("102"), username="bob", db_path=self.db_path)

        ledger.score_pending_predictions(
            "LOTO_6_45",
            lambda _game_type, draw_id: {"ky": draw_id, "main": [1, 2, 9, 10, 11, 12]} if draw_id == "101" else None,
            45,
            6,
            6,
            db_path=self.db_path,
        )
        alice_rows = ledger.list_predictions("LOTO_6_45", username="alice", db_path=self.db_path)
        bob_rows = ledger.list_predictions("LOTO_6_45", username="bob", db_path=self.db_path)

        self.assertEqual(["alice"], [row["username"] for row in alice_rows])
        self.assertEqual(["bob"], [row["username"] for row in bob_rows])
        self.assertEqual("scored", alice_rows[0]["status"])
        self.assertEqual(2, alice_rows[0]["score_hit_count"])
        self.assertIsNotNone(alice_rows[0]["score_brier_score"])
        self.assertEqual([], bob_rows[0]["score_metrics"].get("actual_main", []))

    def test_candidate_does_not_auto_replace_champion(self):
        ledger.register_model("LOTO_6_45", "candidate_v1", "100", "candidate", db_path=self.db_path)

        self.assertEqual([], ledger.list_models("LOTO_6_45", "champion", db_path=self.db_path))
        self.assertEqual(1, len(ledger.list_models("LOTO_6_45", "candidate", db_path=self.db_path)))

    def test_force_flag_cannot_bypass_promotion_gates(self):
        candidate = {
            "model_id": "keno_candidate_bad_brier",
            "validation_metrics": {"fold_count": 48, "brier_score": 0.20, "log_loss": 0.65},
            "outer_backtest_metrics": {},
        }

        with mock.patch.object(ml_pipeline, "list_models", side_effect=[[candidate], []]), \
                mock.patch.object(ml_pipeline, "reject_candidate") as reject, \
                mock.patch.object(ml_pipeline, "ledger_promote_candidate") as promote:
            result = ml_pipeline.promote_candidate("KENO", candidate["model_id"], force=True)

        self.assertTrue(result["rejected"])
        self.assertFalse(result["promoted"])
        self.assertIn("random baseline", result["reason"])
        reject.assert_called_once()
        promote.assert_not_called()

    def test_promote_and_rollback_are_atomic_registry_operations(self):
        champion = ledger.register_model("LOTO_6_45", "champion_v1", "90", "champion", db_path=self.db_path)
        candidate = ledger.register_model("LOTO_6_45", "candidate_v2", "100", "candidate", db_path=self.db_path)

        promoted = ledger.promote_candidate("LOTO_6_45", candidate["model_id"], "test promotion", db_path=self.db_path)
        self.assertEqual(candidate["model_id"], promoted["champion_model_id"])
        self.assertEqual(champion["model_id"], ledger.list_models("LOTO_6_45", "archived", db_path=self.db_path)[0]["model_id"])

        rolled_back = ledger.rollback_champion("LOTO_6_45", "test rollback", db_path=self.db_path)
        self.assertEqual(champion["model_id"], rolled_back["champion_model_id"])

    def test_legacy_prediction_payload_gets_probability_metadata(self):
        payload = sample_prediction()

        self.assertIn("calibratedProbability", payload)
        self.assertIn("calibrated_probability", payload)
        self.assertAlmostEqual(6.0, sum(payload["probabilities"].values()), places=10)
        self.assertEqual(payload["ticketQualityScore"], payload["ticket_quality_score"])

    def test_keno_payload_uses_pick_size_for_random_baseline(self):
        payload = sample_keno_prediction(pick_size=5)

        self.assertAlmostEqual(20.0, sum(payload["probabilities"].values()), places=10)
        self.assertAlmostEqual(1.25, payload["randomBaseline"]["expected_hits"])
        self.assertEqual(80, payload["probabilitySummary"]["mainUniverseSize"])
        self.assertEqual(20, payload["probabilitySummary"]["mainDrawSize"])

    def test_keno_scoring_uses_payload_pick_size(self):
        payload = sample_keno_prediction(pick_size=5)
        metrics = ledger.score_prediction_payload(
            payload,
            {"ky": "2001", "main": [1, 2, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47]},
            universe_size=80,
            draw_size=20,
            prediction_size=10,
        )

        self.assertEqual(5, metrics["prediction_size"])
        self.assertEqual(2, metrics["hit_count"])
        self.assertAlmostEqual(2 / (5 * 20 / 80) - 1, metrics["lift"])

    def test_ticket_generation_size_uniqueness_and_diversity(self):
        bundles = build_prediction_bundles(list(range(1, 16)), 6, 3)

        self.assertEqual(3, len(bundles))
        self.assertTrue(all(len(ticket) == 6 for ticket in bundles))
        self.assertTrue(all(len(ticket) == len(set(ticket)) for ticket in bundles))
        self.assertGreater(len({tuple(ticket) for ticket in bundles}), 1)

    def test_backend_ml_admin_routes_are_admin_only(self):
        source = Path("backend/LottoWebServer.java").read_text(encoding="utf-8")

        for handler in ("handleMlTrainCandidate", "handleMlPromote", "handleMlRollback"):
            start = source.index(f"private void {handler}")
            block = source[start: source.index("    private void", start + 1)]
            self.assertIn("requireAdmin(ex)", block)

    def test_backend_ml_type_keys_include_keno(self):
        source = Path("backend/LottoWebServer.java").read_text(encoding="utf-8")
        start = source.index("private static final Set<String> ML_TYPE_KEYS")
        block = source[start: source.index("private static final Set<String> ANALYSIS_MODE_KEYS", start)]

        self.assertIn('"KENO"', block)

    def test_backend_ml_predictions_are_scoped_to_authenticated_user(self):
        source = Path("backend/LottoWebServer.java").read_text(encoding="utf-8")
        start = source.index("private void handleMlPredictions")
        block = source[start: source.index("    private void", start + 1)]

        self.assertIn('command.add("--username=" + su.username)', block)

    def test_frontend_history_refreshes_ledger_status_and_scores(self):
        source = Path("frontend/vietlott-web-data.js").read_text(encoding="utf-8")

        self.assertIn("/api/ml/predictions?type=", source)
        self.assertIn("syncLedgerRowsIntoPredictionHistory", source)
        self.assertIn("score_brier_score", source)
        self.assertIn("score_log_loss", source)


if __name__ == "__main__":
    unittest.main()
