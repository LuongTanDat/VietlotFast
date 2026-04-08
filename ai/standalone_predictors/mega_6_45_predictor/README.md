# Mega 6/45 Adaptive Predictor

Standalone heuristic-first predictor for Vietlott Mega 6/45.

The project is intentionally modular:

- `config/` stores predictor knobs, schema aliases, and feature flags.
- `data/` stores the CSV input copied from the repo and optional processed exports.
- `state/` stores tracking memory, the last prediction payload, and run metrics.
- `models/` stores optional future deep-learning artifacts.
- `src/` contains the loader, feature, scoring, ticket, API, and backtest modules.
- `tests/` contains focused regression tests for loader, features, tracking, and ticket generation.

Heuristic mode works with Python standard library only.
Deep-learning support is scaffolded and stays optional.

Quick start:

```powershell
cd "c:\Users\Luong Tan Dat\OneDrive\Vsuacode\Dự Án\Lotto\ai\standalone_predictors\mega_6_45_predictor"
python main.py predict --csv data/mega_6_45.csv
python main.py update --csv data/mega_6_45.csv --actual "06,12,18,25,31,42"
python main.py backtest --csv data/mega_6_45.csv
```
