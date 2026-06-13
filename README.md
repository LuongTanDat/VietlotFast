# VietlotFast

Project structure after reorganization:

- `ai/`: predictors, models, training, configs
  Included inside `ai/standalone_predictors/`: standalone VIP engines for `Loto 5/35`, `Mega 6/45`, `Power 6/55`, plus legacy `predictor_v2`
- `docs/`: project notes and architecture documents
- `data/`: canonical data and scoring exports
- `backend/`: Python backend jobs, Java web server, JDBC library
- `frontend/`: HTML/CSS/JS assets
- `runtime/`: runtime database and logs
- `scripts/`: launch scripts
- `tests/`: test area
- `Bin/`: packaged versions and binary snapshots

`Bin/` structure:

- `Bin/session_1_latest/files/ai/`
- `Bin/session_1_latest/files/backend/`
- `Bin/session_1_latest/files/frontend/`
- `Bin/session_1_latest/files/data/`
- `Bin/session_1_latest/manifest.json`
- `Bin/session_2_previous/files/ai/`
- `Bin/session_2_previous/files/backend/`
- `Bin/session_2_previous/files/frontend/`
- `Bin/session_2_previous/files/data/`
- `Bin/session_2_previous/manifest.json`

## Python dependencies

Install shared Python dependencies before running backend jobs, AI predictors, or tests:

```bash
python -m pip install -r requirements.txt
```

## Controlled ML pipeline

The controlled ML workflow is enabled for `KENO`, `LOTO_5_35`, `LOTO_6_45`, and `LOTO_6_55`.
It keeps the existing `ai/predictors/ai_predict.py` entrypoint and the three standalone predictors, but stores immutable prediction runs in SQLite.

Common commands:

```bash
python ai/predictors/ai_predict.py ml_status
python ai/predictors/ai_predict.py predict_json KENO 1 10 --engine=classic --pure
python ai/predictors/ai_predict.py ml_backtest KENO --mode=fast --window=expanding
python ai/predictors/ai_predict.py ml_backtest LOTO_6_45 --mode=fast --window=expanding
python ai/predictors/ai_predict.py ml_score_pending LOTO_6_45
python ai/predictors/ai_predict.py ml_train_candidate LOTO_6_45 --mode=fast
python ai/predictors/ai_predict.py ml_promote LOTO_6_45 --model-id=MODEL_ID
python ai/predictors/ai_predict.py ml_rollback LOTO_6_45
```

Backtests are walk-forward by draw order. Each fold uses only history before the target draw, rejects deep artifacts whose `trained_on_latest_draw_id` is not before the target draw, simulates tracking sequentially, and writes fold audit JSON under `runtime/backtests/` when launched through the ML pipeline.

Keno `--pure` mode reads the existing canonical history without writing canonical files, model state, or the prediction ledger. Web prediction history synchronizes ledger status and score metrics for the authenticated user only. Promotion gates cannot be bypassed; candidates that fail the configured baseline or validation requirements are recorded as rejected.
