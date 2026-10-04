"""Run in an isolated process because standalone projects share the src name."""
import sys
from pathlib import Path
from unittest import mock
import numpy as np

root = Path(__file__).resolve().parents[1]
game = sys.argv[1]
project = root / 'ai/standalone_predictors' / f'{game}_predictor'
sys.path.insert(0, str(root))
sys.path.insert(0, str(project))
from src import data_loader, deep_dataset, deep_model, feature_engineering, predictor_api, tracking_engine, backtest

runtime = predictor_api.load_runtime_configuration(project)
cfg = runtime['predictor_config']
draws = data_loader.load_draw_records(root / 'data/canonical' / f'{game}_all_day.csv',
                                     column_mapping_path=project / 'config/column_mapping.json')['records'][:80]
modulo = {'use_mod9': True} if game == 'mega_6_45' else {'use_mod11': True}
history = draws[:-1]
context = feature_engineering.build_prediction_context(history, tracking_engine.clone_default_state(), cfg,
                target_weekday=4, time_slot_enabled=False, **modulo)
training = deep_dataset.build_training_samples(draws, cfg)
with mock.patch.object(deep_dataset, 'build_inference_sample', wraps=deep_dataset.build_inference_sample) as builder, \
     mock.patch.object(deep_model, '_inspect_artifacts', return_value={'deep_enabled': False, 'deep_status_line': 'fixture'}):
    deep_model.score_numbers(context, {}, cfg, runtime['feature_flags'], project)
    assert len(builder.call_args.kwargs['draws']) == len(history), 'production truncated feature context'
    inference = deep_dataset.build_inference_sample(**builder.call_args.kwargs)
    np.testing.assert_array_equal(training['features'][-1], inference['features'][0])

reports = {'heuristic_only': {'average_hits': .6, 'folds': [{'target_draw_id': 10}]},
           'deep_only': {'average_hits': 1.0, 'folds': [{'target_draw_id': 11}]},
           'blended': {'average_hits': .8, 'folds': [{'target_draw_id': 12}]}}
with mock.patch.object(backtest, '_evaluate_mode', side_effect=lambda **kwargs: reports[kwargs['blend_mode']]):
    result = backtest.run_ablation_report(str(root / 'data/canonical' / f'{game}_all_day.csv'), project_root=project)
    assert result['evaluated_mode'] == result['winner_mode'] == 'deep_only'
    assert result['metrics']['folds'] == reports['deep_only']['folds']
    assert result['selection_on_evaluation'] is True
print('Feature parity and evaluated mode passed:', game)
