import json
import math
import random
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from ai import controlled_models, ml_pipeline, prediction_ledger as ledger
from ai.configs import data_paths as dp
from backend import live_results
from ai.predictors.ai_predict import finalize_controlled_prediction_payload


class AuditFixTests(unittest.TestCase):
    def test_web_rejects_known_results_and_elapsed_targets_before_locking(self):
        actual = {'100': {'ky': '100', 'date': '01/01/2000', 'time': '18:00', 'main': [1, 2, 3, 4, 5, 6]}}
        with mock.patch.object(ml_pipeline, 'load_actual_draws', return_value=actual), mock.patch.object(ledger, 'lock_prediction') as lock:
            for target in ('100', '101'):
                result = finalize_controlled_prediction_payload({'type': 'LOTO_6_45', 'latestKy': '100', 'nextKy': target,
                    'tickets': [{'main': [1, 2, 3, 4, 5, 6]}]})
                self.assertFalse(result['ready'])
                self.assertEqual('validation_rejected', result['predictionStatus'])
            lock.assert_not_called()
    def test_stale_csv_writer_cannot_remove_newer_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mega_6_45_all_day.csv'
            row = {'Ky': '1', 'Ngay': '01/10/2026', 'Main': '1,2,3,4,5,6'}
            live_results.write_csv_rows(path, {'1': row}, type_key='LOTO_6_45')
            stale = live_results.load_csv_rows(path)
            newer = live_results.load_csv_rows(path)
            newer['2'] = {**row, 'Ky': '2'}
            live_results.write_csv_rows(path, newer, type_key='LOTO_6_45')
            stale['3'] = {**row, 'Ky': '3'}
            with self.assertRaisesRegex(RuntimeError, 'stale overwrite'):
                live_results.write_csv_rows(path, stale, type_key='LOTO_6_45')
            self.assertEqual({'1', '2'}, set(live_results.load_csv_rows(path)))
            self.assertEqual([], list(Path(folder).glob('*.tmp')))

    def test_promotion_requires_valid_artifact_and_identical_holdout(self):
        draws = [{'ky': str(n), 'main': [1, 2, 3, 4, 5, 6], 'date': '01/10/2026', 'time': ''} for n in range(1, 401)]
        cfg = ml_pipeline.game_config('LOTO_6_45')
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(dp, 'RUNTIME_DIR', Path(folder)):
            candidate = controlled_models.train_registered_candidate('LOTO_6_45', cfg, draws, 'fast', db_path=Path(folder) / 'test.db')
            self.assertTrue(ml_pipeline._candidate_passes(candidate, None, cfg)[0])
            champion = {**candidate, 'outer_backtest_metrics': {**candidate['outer_backtest_metrics'], 'evaluation_manifest': {'data_hash': 'other'}}}
            self.assertFalse(ml_pipeline._candidate_passes(candidate, champion, cfg)[0])
            missing = {**candidate, 'artifact_paths': {}}
            self.assertFalse(ml_pipeline._candidate_passes(missing, None, cfg)[0])
    def test_deep_production_input_matches_training_at_same_cutoff(self):
        for game in ('mega_6_45', 'power_6_55'):
            with self.subTest(game=game):
                result = subprocess.run([sys.executable, 'tests/deep_parity_fixture.py', game],
                                         cwd=dp.PROJECT_ROOT, capture_output=True, timeout=60)
                self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
    def test_ledger_rejects_past_target_and_expired_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'ledger.db'
            for target in ('100', '99', 'bad'):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    ledger.lock_prediction({'type': 'LOTO_6_45', 'latestKy': '100', 'nextKy': target}, db_path=database)
            with self.assertRaises(ValueError):
                ledger.lock_prediction({'type': 'LOTO_6_45', 'latestKy': '100', 'nextKy': '101',
                                        'predictionDeadline': '2000-01-01T00:00:00+07:00'}, db_path=database)

    def test_ledger_uses_server_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            record = ledger.lock_prediction({'type': 'LOTO_6_45', 'latestKy': '100', 'nextKy': '101',
                                             'createdAt': '1990-01-01T00:00:00Z'}, db_path=Path(folder) / 'test.db')
            self.assertNotEqual('1990-01-01T00:00:00Z', ledger.list_predictions(db_path=Path(folder) / 'test.db')[0]['created_at'])

    def test_random_portfolio_does_not_gain_lift_from_ticket_count(self):
        rng = random.Random(1741)
        tickets = [{'main': rng.sample(range(1, 46), 6)} for _ in range(10)]
        uniform = {str(n): 6 / 45 for n in range(1, 46)}
        scores = [ledger.score_prediction_payload({'tickets': tickets, 'probabilities': uniform},
                  {'main': rng.sample(range(1, 46), 6)}, 45, 6, 6) for _ in range(1000)]
        self.assertLess(abs(sum(score['lift'] for score in scores) / len(scores)), .08)
        self.assertLess(abs(sum(score['portfolio_best_lift'] for score in scores) / len(scores)), .08)
        self.assertTrue(all(len(score['per_ticket']) == 10 for score in scores))

    def test_promotion_rejects_missing_nonfinite_and_equal_baseline_metrics(self):
        cfg = ml_pipeline.game_config('LOTO_6_45')
        for bad in ({}, {'brier_score': math.nan}, {'brier_score': math.inf}, {'brier_score': .08, 'log_loss': math.nan},
                    {'brier_score': ml_pipeline._random_brier_baseline(45, 6), 'log_loss': .3}):
            with self.subTest(metrics=bad):
                passed, _ = ml_pipeline._candidate_passes({'validation_metrics': {'fold_count': 120, **bad}}, None, cfg)
                self.assertFalse(passed)

    def test_candidate_has_real_artifact_and_separate_chronological_evaluation(self):
        rng = random.Random(413)
        draws = [{'ky': str(i), 'main': sorted(rng.sample(range(1, 46), 6)), 'special': None,
                  'date': '01/10/2026', 'time': ''} for i in range(1, 401)]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(dp, 'RUNTIME_DIR', Path(folder)):
            database = Path(folder) / 'test.db'
            candidate = controlled_models.train_registered_candidate('LOTO_6_45', ml_pipeline.game_config('LOTO_6_45'), draws, 'fast', db_path=database)
            artifact = controlled_models.verify_artifact(candidate)
            self.assertEqual('160', artifact['trained_data_cutoff'])
            validation = candidate['validation_metrics']['evaluation_manifest']['target_draw_ids']
            testing = candidate['outer_backtest_metrics']['evaluation_manifest']['target_draw_ids']
            self.assertEqual('161', validation[0])
            self.assertEqual('281', testing[0])
            self.assertFalse(set(validation) & set(testing))
            self.assertAlmostEqual(6, sum(artifact['probabilities'].values()))
            self.assertEqual([], ledger.list_models('LOTO_6_45', 'champion', db_path=database))
            path = Path(candidate['artifact_paths']['model'])
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                controlled_models.verify_artifact(candidate)

    def test_champion_and_rollback_select_actual_artifact(self):
        cfg = ml_pipeline.game_config('LOTO_6_45')
        draws_a = [{'ky': str(n), 'main': [1, 2, 3, 4, 5, 6]} for n in range(1, 61)]
        draws_b = [{'ky': str(n), 'main': [7, 8, 9, 10, 11, 12]} for n in range(1, 61)]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(dp, 'RUNTIME_DIR', Path(folder)):
            database = Path(folder) / 'test.db'
            for name, draws, status in [('model_a', draws_a, 'champion'), ('model_b', draws_b, 'candidate')]:
                artifact = controlled_models.fit_artifact('LOTO_6_45', draws, cfg)
                paths = controlled_models.save_artifact('LOTO_6_45', artifact, name)
                ledger.register_model('LOTO_6_45', name, '60', status, artifact_paths=paths, model_id=name, db_path=database)
            with mock.patch.object(ml_pipeline, 'load_actual_draws', return_value={'61': {'ky': '61', 'date': '01/10/2026', 'time': '', 'main': [1, 3, 5, 7, 9, 11]}}):
                first = controlled_models.champion_prediction('LOTO_6_45', 1, 6, 'normal', db_path=database)
                self.assertEqual([1, 2, 3, 4, 5, 6], first['tickets'][0]['main'])
                ledger.promote_candidate('LOTO_6_45', 'model_b', 'fixture only', db_path=database)
                second = controlled_models.champion_prediction('LOTO_6_45', 1, 6, 'normal', db_path=database)
                self.assertEqual([7, 8, 9, 10, 11, 12], second['tickets'][0]['main'])
                ledger.rollback_champion('LOTO_6_45', db_path=database)
                last = controlled_models.champion_prediction('LOTO_6_45', 1, 6, 'normal', db_path=database)
                self.assertEqual(first['modelId'], last['modelId'])
                self.assertEqual(first['tickets'], last['tickets'])


if __name__ == '__main__':
    unittest.main()
