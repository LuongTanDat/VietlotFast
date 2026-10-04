# Power 6/55 Adaptive Predictor

Standalone heuristic-first predictor for Vietlott Power 6/55.

This project treats the 6 main numbers and the special number as separate scoring subsystems.
It is designed as an adaptive scoring engine built from CSV history, not as a proof of predictability.

Project layout:

- `config/` stores predictor weights, schema aliases, and feature flags.
- `data/` stores the Power 6/55 CSV snapshot and optional processed exports.
- `state/` stores tracking memory, the unresolved prediction, and run metrics.
- `models/` stores CNN–GRU NumPy model, scaler and metadata artifacts.
- `src/` contains the loader, feature, scoring, ticket, API, and backtest modules.
- `tests/` contains focused regression tests for loader, features, tracking, and ticket generation.

Install the dependencies from the repository requirements.txt (including NumPy).
Deep scoring uses a trained CNN–GRU NumPy model when its artifact, schema and cutoff are valid; otherwise it falls back to heuristic scoring.
Inference uses complete history to construct the final sequence, matching training features.
Regime-head validation measures the observed-history label, not evidence of future winning numbers.

Quick start:

```powershell
cd "c:\Users\Luong Tan Dat\OneDrive\Vsuacode\Dự Án\Lotto\ai\standalone_predictors\power_6_55_predictor"
python main.py predict --csv data/power_6_55.csv
python main.py update --csv data/power_6_55.csv --actual-main "09,21,32,34,52,53" --actual-special "22"
python main.py backtest --csv data/power_6_55.csv
```
