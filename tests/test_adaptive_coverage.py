import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ai.predictors import ai_predict
from ai.adaptive_coverage import (
    GAME_SPECS,
    _edge_gate,
    _exploration_rate,
    apply_adaptive_coverage,
    candidate_pool_size,
)


class AdaptiveCoverageTests(unittest.TestCase):
    def build_payload(self, game_type, bundle_count=1, pick_size=None):
        spec = GAME_SPECS[game_type]
        minimum = int(spec["universeMin"])
        maximum = int(spec["universeMax"])
        pick_size = int(pick_size or spec["defaultPickSize"])
        special_min = int(spec.get("specialMin") or 0)
        special_max = int(spec.get("specialMax") or 0)
        return {
            "ok": True,
            "ready": True,
            "type": game_type,
            "engine": "classic",
            "latestKy": "100",
            "nextKy": "101",
            "bundleCount": bundle_count,
            "pickSize": pick_size,
            "topRanking": list(range(minimum, maximum + 1)),
            "topSpecialRanking": list(range(special_min, special_max + 1)) if special_min else [],
            "tickets": [],
            "backtest": {"avgHitRate": 0.0, "samples": 0},
        }

    def test_candidate_pool_schedule(self):
        self.assertEqual(500, candidate_pool_size(1))
        self.assertEqual(1000, candidate_pool_size(2))
        self.assertEqual(1000, candidate_pool_size(3))
        self.assertEqual(1500, candidate_pool_size(4))
        self.assertEqual(1500, candidate_pool_size(6))
        self.assertEqual(2000, candidate_pool_size(7))

    def test_all_supported_games_use_gumbel_portfolio(self):
        for game_type, spec in GAME_SPECS.items():
            with self.subTest(game_type=game_type):
                payload = self.build_payload(game_type)
                result = apply_adaptive_coverage(payload, risk_mode="balanced")

                self.assertEqual("adaptive_coverage_v1", result["adaptiveCoverageVersion"])
                self.assertEqual("gumbel_top_k_without_replacement", result["adaptiveCoverage"]["candidateMethod"])
                self.assertEqual(500, result["adaptiveCoverage"]["candidateCountRequested"])
                self.assertEqual(1, len(result["tickets"]))
                main = result["tickets"][0]["main"]
                self.assertEqual(payload["pickSize"], len(main))
                self.assertEqual(len(main), len(set(main)))
                self.assertTrue(all(int(spec["universeMin"]) <= number <= int(spec["universeMax"]) for number in main))

    def test_result_is_deterministic_for_same_draw_and_payload(self):
        payload = self.build_payload("LOTO_5_35", bundle_count=3)

        first = apply_adaptive_coverage(payload, risk_mode="balanced")
        second = apply_adaptive_coverage(payload, risk_mode="balanced")

        self.assertEqual(first["tickets"], second["tickets"])
        self.assertEqual(first["adaptiveCoverage"]["seed"], second["adaptiveCoverage"]["seed"])
        self.assertEqual(1000, first["adaptiveCoverage"]["candidateCountGenerated"])

    def test_power_special_number_is_not_reused_as_main_number(self):
        payload = self.build_payload("LOTO_6_55", bundle_count=3)
        result = apply_adaptive_coverage(payload)

        for ticket in result["tickets"]:
            self.assertNotIn(ticket["special"], ticket["main"])

    def test_keno_level_one_caps_at_unique_search_space(self):
        payload = self.build_payload("KENO", bundle_count=1, pick_size=1)
        result = apply_adaptive_coverage(payload)

        self.assertEqual(500, result["adaptiveCoverage"]["candidateCountRequested"])
        self.assertEqual(80, result["adaptiveCoverage"]["candidateCountTarget"])
        self.assertEqual(80, result["adaptiveCoverage"]["candidateCountGenerated"])

    def test_random_baseline_gate_controls_exploration(self):
        spec = GAME_SPECS["LOTO_6_45"]
        payload = {"backtest": {"avgHits": 0.06, "avgHitRate": 0.01, "samples": 200}}
        gate = _edge_gate(payload, spec, pick_size=6)

        self.assertEqual("below_random", gate["state"])
        self.assertGreaterEqual(_exploration_rate(payload, "balanced", gate), 0.65)

    def test_confidence_field_cannot_masquerade_as_backtest_edge(self):
        spec = GAME_SPECS["LOTO_5_35"]
        payload = {"backtest": {"avgHits": 0.0, "avgHitRate": 0.45, "samples": 500}}

        gate = _edge_gate(payload, spec, pick_size=5)

        self.assertEqual("unverified", gate["state"])
        self.assertFalse(gate["evidenceConsistent"])

    def test_predict_json_applies_profile_only_to_normal_mode(self):
        payload = self.build_payload("LOTO_6_45")
        with patch.object(ai_predict, "_predict_json_unlocked", return_value=payload), patch.object(
            ai_predict,
            "finalize_controlled_prediction_payload",
            side_effect=lambda value, **_: value,
        ):
            normal = ai_predict.predict_json("LOTO_6_45", 1, prediction_mode="normal", lock_ledger=False)
            vip = ai_predict.predict_json("LOTO_6_45", 1, prediction_mode="vip", lock_ledger=False)

        self.assertEqual("adaptive_coverage_v1", normal["adaptiveCoverageVersion"])
        self.assertNotIn("adaptiveCoverageVersion", vip)

    def test_both_engine_merge_deduplicates_and_combines_candidate_metadata(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        start = source.index("function buildSmartInterleavedTickets")
        end = source.index("function renderPredictEngineChoice", start)
        block = source[start:end]

        self.assertIn("const selectedKeys = new Set();", block)
        self.assertIn("const takeNextUnique = sourceKey =>", block)
        self.assertIn("candidateCountGenerated: adaptiveSources.reduce", block)
        self.assertIn("sourceRuns:", block)

    def test_prediction_bundle_limits_are_enforced_by_backend(self):
        with self.assertRaisesRegex(ValueError, "100 Bộ"):
            ai_predict._predict_json_unlocked("LOTO_6_45", 101)
        with self.assertRaisesRegex(ValueError, "VIP tối đa là 10 Bộ"):
            ai_predict._predict_json_unlocked("LOTO_6_45", 11, prediction_mode="vip")
        with self.assertRaisesRegex(ValueError, "bậc 5 là 16 Bộ"):
            ai_predict._predict_json_unlocked("KENO", 17, keno_level=5)

    def test_vip_profile_can_select_up_to_ten_tickets(self):
        payload = self.build_payload("MAX_3D", bundle_count=12)
        payload["topRanking"] = list(range(100, 130))
        payload["tickets"] = [{"main": [value]} for value in range(100, 112)]

        result = ai_predict.apply_vip_prediction_profile(payload, 10)

        self.assertEqual(10, len(result["tickets"]))

    def test_top_ranking_limits_are_normalized_per_game(self):
        expected = {
            "LOTO_5_35": (15, 6),
            "LOTO_6_45": (18, 0),
            "LOTO_6_55": (18, 9),
            "KENO": (20, 0),
            "MAX_3D": (20, 0),
            "MAX_3D_PRO": (20, 0),
        }
        for game_type, (main_count, special_count) in expected.items():
            with self.subTest(game_type=game_type):
                rule = ai_predict.AI_TOP_RANKING_RULES[game_type]
                payload = {
                    "type": game_type,
                    "topRanking": list(range(rule["mainUniverseMin"], rule["mainUniverseMax"] + 1)),
                    "topSpecialRanking": list(range(rule["specialUniverseMin"], rule["specialUniverseMax"] + 1))
                    if rule["specialMax"] else [1, 2, 3],
                    "tickets": [],
                }

                result = ai_predict.normalize_prediction_top_rankings(payload)

                self.assertEqual(main_count, len(result["topRanking"]))
                self.assertEqual(special_count, len(result["topSpecialRanking"]))
                self.assertEqual(len(result["topRanking"]), len(set(result["topRanking"])))
                self.assertEqual(len(result["topSpecialRanking"]), len(set(result["topSpecialRanking"])))

    def test_power_top_special_does_not_overlap_top_main(self):
        result = ai_predict.normalize_prediction_top_rankings({
            "type": "LOTO_6_55",
            "topRanking": list(range(1, 56)),
            "topSpecialRanking": list(range(1, 56)),
            "tickets": [],
        })

        self.assertEqual(18, len(result["topRanking"]))
        self.assertEqual(9, len(result["topSpecialRanking"]))
        self.assertTrue(set(result["topRanking"]).isdisjoint(result["topSpecialRanking"]))

    def test_frontend_uses_the_same_top_ranking_contract(self):
        root = Path(__file__).resolve().parents[1]
        core_source = (root / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        data_source = (root / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        stats_source = (root / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")

        self.assertIn("const PREDICTION_TOP_RANKING_RULES", core_source)
        self.assertIn("function normalizePredictionTopRankings", core_source)
        self.assertIn("specialExcludesMain: true", core_source)
        self.assertIn("result = normalizePredictionResultTopRankings(result, type);", data_source)
        self.assertIn("normalizePredictionTopRankings(", stats_source)
        self.assertNotIn("Số phụ ưu tiên", data_source)

    def test_prediction_form_clamps_count_and_deduplicates_errors(self):
        root = Path(__file__).resolve().parents[1]
        core_source = (root / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        data_source = (root / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        html_source = (root / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")

        self.assertIn("function getPredictBundleLimit", core_source)
        self.assertIn("Math.floor(TYPES.KENO.mainMax / normalizedLevel)", core_source)
        self.assertIn("syncPredictBundleLimit({ clampValue: true, forceMinimum: true })", data_source)
        self.assertIn('id="pdCountLimit"', html_source)
        self.assertIn('max="100"', html_source)
        self.assertIn("const VIP_PREDICT_MAX_BUNDLES = 10;", core_source)
        self.assertIn("function syncVipPredictBundleLimit", core_source)
        self.assertIn('id="vipPdCount" type="number" min="1" max="10"', html_source)
        self.assertIn("syncVipPredictBundleLimit({ clampValue: true, forceMinimum: true }).value", data_source)
        self.assertIn("function normalizePredictionErrorDetail", data_source)
        self.assertNotIn("Không thể dự đoán bằng AI backend:", data_source)

    def test_keno_target_skips_draw_slots_that_are_already_in_the_past(self):
        payload = {
            "ok": True,
            "ready": True,
            "type": "KENO",
            "latestKy": "288150",
            "latestDate": "13/07/2026",
            "latestTime": "10:00",
            "nextKy": "#288151",
        }

        aligned = ai_predict.align_prediction_target_with_schedule(
            payload,
            now_value=datetime(2026, 7, 13, 10, 11, 50),
        )

        self.assertEqual("#288152", aligned["nextKy"])
        self.assertEqual("288152", aligned["target_draw_id"])
        self.assertEqual("2026-07-13T10:16:00", aligned["targetDrawAt"])

    def test_keno_target_rolls_to_next_morning_after_last_draw(self):
        payload = {
            "ok": True,
            "ready": True,
            "type": "KENO",
            "latestKy": "288120",
            "latestDate": "12/07/2026",
            "latestTime": "21:52",
            "nextKy": "#288121",
        }

        aligned = ai_predict.align_prediction_target_with_schedule(
            payload,
            now_value=datetime(2026, 7, 12, 22, 5),
        )

        self.assertEqual("#288121", aligned["nextKy"])
        self.assertEqual("2026-07-13T06:08:00", aligned["targetDrawAt"])

    def test_prediction_history_uses_backend_target_time_and_waiting_state(self):
        root = Path(__file__).resolve().parents[1]
        data_source = (root / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        core_source = (root / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")

        self.assertIn("const storedTargetDate = parsePredictionLogDate(entry.targetDrawAt);", data_source)
        self.assertIn('countdownText: "Đang chờ KQ"', data_source)
        self.assertIn("waitingForResult: true", data_source)
        self.assertIn('targetDrawAt: String(result?.targetDrawAt || result?.target_draw_at || "")', data_source)
        self.assertIn('targetDrawAt: String(entry.targetDrawAt || "")', core_source)


if __name__ == "__main__":
    unittest.main()
