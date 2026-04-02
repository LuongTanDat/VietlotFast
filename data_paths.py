import json
from functools import lru_cache
from pathlib import Path, PurePosixPath


LOTTO_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = LOTTO_DIR.parent
DATA_REGISTRY_FILE = LOTTO_DIR / "data_registry.json"

_CANONICAL_FILE_NAMES = {
    "KENO": "keno_all_day",
    "LOTO_5_35": "loto_5_35_all_day",
    "LOTO_6_45": "mega_6_45_all_day",
    "LOTO_6_55": "power_6_55_all_day",
    "MAX_3D": "max_3d_all_day",
    "MAX_3D_PRO": "max_3d_pro_all_day",
}

DEFAULT_REGISTRY = {
    "canonical.KENO.csv": "CSV/canonical/keno_all_day.csv",
    "canonical.KENO.meta": "CSV/canonical/keno_all_day.meta.json",
    "canonical.LOTO_5_35.csv": "CSV/canonical/loto_5_35_all_day.csv",
    "canonical.LOTO_5_35.meta": "CSV/canonical/loto_5_35_all_day.meta.json",
    "canonical.LOTO_6_45.csv": "CSV/canonical/mega_6_45_all_day.csv",
    "canonical.LOTO_6_45.meta": "CSV/canonical/mega_6_45_all_day.meta.json",
    "canonical.LOTO_6_55.csv": "CSV/canonical/power_6_55_all_day.csv",
    "canonical.LOTO_6_55.meta": "CSV/canonical/power_6_55_all_day.meta.json",
    "canonical.MAX_3D.csv": "CSV/canonical/max_3d_all_day.csv",
    "canonical.MAX_3D.meta": "CSV/canonical/max_3d_all_day.meta.json",
    "canonical.MAX_3D_PRO.csv": "CSV/canonical/max_3d_pro_all_day.csv",
    "canonical.MAX_3D_PRO.meta": "CSV/canonical/max_3d_pro_all_day.meta.json",
    "exports.scoring.dir": "CSV/exports/scoring",
}


@lru_cache(maxsize=1)
def load_data_registry():
    payload = {}
    try:
        raw = json.loads(DATA_REGISTRY_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            payload = {str(key): str(value) for key, value in raw.items() if value is not None}
    except Exception:
        payload = {}
    merged = dict(DEFAULT_REGISTRY)
    merged.update(payload)
    return merged


def get_registry_value(key, default=""):
    return str(load_data_registry().get(key, default) or default)


def _resolve_lotto_relative(relative_path):
    text = str(relative_path or "").strip().replace("\\", "/")
    if not text:
        return LOTTO_DIR
    path = LOTTO_DIR
    for part in PurePosixPath(text).parts:
        if part in ("", "."):
            continue
        path = path / part
    return path


def _canonical_registry_key(type_key, kind):
    normalized = str(type_key or "").strip().upper()
    if normalized not in _CANONICAL_FILE_NAMES:
        raise KeyError(f"Unsupported canonical type: {type_key}")
    return f"canonical.{normalized}.{kind}"


def _legacy_canonical_path(type_key, suffix):
    normalized = str(type_key or "").strip().upper()
    stem = _CANONICAL_FILE_NAMES[normalized]
    return PROJECT_ROOT / f"{stem}.{suffix}"


def get_canonical_csv_write_path(type_key):
    return _resolve_lotto_relative(get_registry_value(_canonical_registry_key(type_key, "csv")))


def get_canonical_meta_write_path(type_key):
    return _resolve_lotto_relative(get_registry_value(_canonical_registry_key(type_key, "meta")))


def get_canonical_csv_legacy_path(type_key):
    return _legacy_canonical_path(type_key, "csv")


def get_canonical_meta_legacy_path(type_key):
    return _legacy_canonical_path(type_key, "meta.json")


def _prefer_existing(primary_path, legacy_path):
    if primary_path.exists():
        return primary_path
    if legacy_path.exists():
        return legacy_path
    return primary_path


def get_canonical_csv_read_path(type_key):
    return _prefer_existing(get_canonical_csv_write_path(type_key), get_canonical_csv_legacy_path(type_key))


def get_canonical_meta_read_path(type_key):
    return _prefer_existing(get_canonical_meta_write_path(type_key), get_canonical_meta_legacy_path(type_key))


def get_scoring_export_dir():
    return _resolve_lotto_relative(get_registry_value("exports.scoring.dir"))


def get_legacy_scoring_export_dir():
    return LOTTO_DIR / "runtime_logs" / "scoring_exports"
