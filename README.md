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
