from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config as cfg, deep_model  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the real Loto 5/35 CNN/RNN model.")
    parser.add_argument("--csv", default="data/loto_5_35.csv", help="Path to the Loto 5/35 CSV history.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = deep_model.train_from_csv(args.csv, config_payload=cfg.load_config())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
