from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PREDICTORS = {
    "loto_5_35": {
        "root": REPO_ROOT / "ai" / "standalone_predictors" / "loto_5_35_predictor",
        "csv": REPO_ROOT / "data" / "canonical" / "loto_5_35_all_day.csv",
    },
    "mega_6_45": {
        "root": REPO_ROOT / "ai" / "standalone_predictors" / "mega_6_45_predictor",
        "csv": REPO_ROOT / "data" / "canonical" / "mega_6_45_all_day.csv",
    },
    "power_6_55": {
        "root": REPO_ROOT / "ai" / "standalone_predictors" / "power_6_55_predictor",
        "csv": REPO_ROOT / "data" / "canonical" / "power_6_55_all_day.csv",
    },
}


def _run_backtest(project_root: Path, csv_path: Path) -> dict:
    output = subprocess.check_output(
        [sys.executable, "main.py", "backtest", "--csv", str(csv_path)],
        cwd=str(project_root),
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def main() -> int:
    summary = {}
    for game, payload in PREDICTORS.items():
        raw = _run_backtest(payload["root"], payload["csv"])
        ablation = dict(raw.get("ablation_report") or raw)
        summary[game] = {
            "winner_mode": ablation.get("winner_mode"),
            "winner_summary": ablation.get("winner_summary"),
            "modes": ablation.get("modes"),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
