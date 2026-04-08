from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import deep_model, predictor_api  # noqa: E402
from src.backtest import run_backtest  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone Mega 6/45 adaptive predictor.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    predict_parser = subparsers.add_parser("predict", help="Generate the next Mega 6/45 ticket and backups.")
    predict_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Path to the Mega 6/45 CSV history.")
    predict_parser.add_argument("--blend-mode", default=None, help="Optional blend mode such as heuristic_only, deep_only, or blended.")

    update_parser = subparsers.add_parser("update", help="Update tracking state after the actual draw is known.")
    update_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Path to the Mega 6/45 CSV history.")
    update_parser.add_argument("--actual", default=None, help='Optional actual draw such as "06,12,18,25,31,42".')

    backtest_parser = subparsers.add_parser("backtest", help="Run chronological backtesting.")
    backtest_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Path to the Mega 6/45 CSV history.")

    retrain_parser = subparsers.add_parser("retrain-deep", help="Train or retrain the real CNN/RNN deep model.")
    retrain_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Path to the Mega 6/45 CSV history.")

    deep_status_parser = subparsers.add_parser("deep-status", help="Inspect whether the real deep model is active.")
    deep_status_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Optional CSV path used for context.")

    blend_status_parser = subparsers.add_parser("blend-status", help="Inspect the active blend profiles and latest ablation report.")
    blend_status_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Optional CSV path used for context.")

    audit_parser = subparsers.add_parser("audit-assembly", help="Inspect disagreement, assembly modes, and the selected ticket.")
    audit_parser.add_argument("--csv", default="data/mega_6_45.csv", help="Path to the Mega 6/45 CSV history.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "predict":
        payload = predictor_api.predict(args.csv, project_root=PROJECT_ROOT, blend_mode=args.blend_mode)
    elif args.command == "update":
        payload = predictor_api.update_after_actual(args.csv, actual_numbers_raw=args.actual, project_root=PROJECT_ROOT)
    elif args.command == "retrain-deep":
        payload = deep_model.train_from_csv(args.csv, project_root=PROJECT_ROOT)
    elif args.command == "deep-status":
        payload = deep_model.get_deep_status(project_root=PROJECT_ROOT)
    elif args.command == "blend-status":
        payload = predictor_api.get_blend_status(project_root=PROJECT_ROOT)
    elif args.command == "audit-assembly":
        payload = predictor_api.audit_assembly(args.csv, project_root=PROJECT_ROOT)
    else:
        payload = run_backtest(args.csv, project_root=PROJECT_ROOT)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
