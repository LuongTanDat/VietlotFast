"""Clean predictor snapshots and scoring CSVs after auditing canonical history.

Back up all inputs, validate every output before writing, and enrich snapshot
prizes only after matching canonical draw identity. Existing draw ranges remain.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.live_results as lr
from scripts.clean_canonical_data import normalize_row

SNAPSHOTS = {
    "LOTO_5_35": "loto_5_35_predictor/data/loto_5_35.csv",
    "LOTO_6_45": "mega_6_45_predictor/data/mega_6_45.csv",
    "LOTO_6_55": "power_6_55_predictor/data/power_6_55.csv",
}
SCORING_HEADER = ["rank", "number", "frequencyCount", "recentCount", "currentDelay",
                  "F_i", "D_i", "T_i", "C_i", "Score_i"]
SCORING_UNIVERSES = {
    "keno": range(1, 81), "loto_5_35": range(1, 36),
    "loto_5_35_special": range(1, 13), "loto_6_45": range(1, 46),
    "loto_6_55": range(1, 56), "max_3d": range(1000), "max_3d_pro": range(1000),
}


def read_csv(path):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
    headers = reader.fieldnames
    if not headers or len(set(headers)) != len(headers):
        raise ValueError(f"Missing or duplicate headers: {path}")
    rows = []
    blank_rows = 0
    for line, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV row at {path}:{line}")
        if all(not value.strip() for value in row.values()):
            blank_rows += 1
            continue
        rows.append(row)
    return raw, headers, rows, blank_rows


def clean_snapshot(key, headers, rows, canonical):
    money_headers = [lr.PRIZE_CSV_HEADERS[f] for f in lr.PRIZE_FIELDS_BY_TYPE[key]]
    expected = lr.get_csv_header(key)
    if headers not in (lr.CSV_HEADER, lr.CSV_HEADER + money_headers, expected,
                       [h for h in expected if h != lr.PRIZE_HIT_HEADER]):
        raise ValueError(f"Unexpected snapshot schema: {key}")
    cleaned, duplicates, changed = {}, 0, Counter()
    for original in rows:
        row = lr.expand_csv_record(key, {name: value.strip() for name, value in original.items()})
        ky = row["Kỳ"].lstrip("#")
        if not re.fullmatch(r"[0-9]+", ky):
            raise ValueError(f"Invalid snapshot draw ID: {key} {ky}")
        ky = str(int(ky))
        source = canonical.get(ky)
        if source is None:
            raise ValueError(f"Snapshot draw missing from canonical: {key} #{ky}")
        if lr.PRIZE_HIT_HEADER not in original:
            row[lr.PRIZE_HIT_HEADER] = source.get(lr.PRIZE_HIT_FIELD, "")
        elif row[lr.PRIZE_HIT_HEADER] != source.get(lr.PRIZE_HIT_FIELD, ""):
            raise ValueError(f"Snapshot prize hit contradicts canonical: {key} #{ky}")
        if not row["Loại"]:
            row["Loại"] = source["Label"]
        # Older snapshots contain truncated source URLs and source dates. Recover
        # provenance from the canonical row, then verify its full draw identity.
        if not lr.parse_csv_date(row["Ngày cập nhật"]):
            row["Ngày cập nhật"] = source["SourceDate"]
            row["Link cập nhật"] = source["SourceUrl"]
        elif not re.fullmatch(r"https?://[^\s]+", row["Link cập nhật"]):
            row["Link cập nhật"] = source["SourceUrl"]
        for field in lr.PRIZE_FIELDS_BY_TYPE[key]:
            header = lr.PRIZE_CSV_HEADERS[field]
            source_amount = source.get(field, "")
            if not source_amount:
                raise ValueError(f"Canonical prize missing: {key} #{ky} {field}")
            if not row.get(header):
                row[header] = source_amount
        row = normalize_row(key, row)
        if (row["Ngày"] != source["Ngay"] or row["Giờ"] != source["Time"]
                or sorted(map(int, row["Bộ Số"].split(","))) != sorted(map(int, source["Main"].split(",")))
                or row["ĐB"] != source["Special"]):
            raise ValueError(f"Snapshot draw contradicts canonical: {key} #{ky}")
        for field in lr.PRIZE_FIELDS_BY_TYPE[key]:
            if row[lr.PRIZE_CSV_HEADERS[field]] != source[field]:
                raise ValueError(f"Snapshot prize contradicts canonical: {key} #{ky} {field}")
        if ky in cleaned:
            if row != cleaned[ky]:
                raise ValueError(f"Conflicting snapshot duplicate: {key} #{ky}")
            duplicates += 1
            continue
        cleaned[ky] = row
        changed.update(name for name in expected if row[name] != original.get(name, ""))
    output = [{name: row[name] for name in expected}
              for row in sorted(cleaned.values(), key=lambda row: int(row["Kỳ"]), reverse=True)]
    return expected, output, {
        "duplicateRowsRemoved": duplicates, "changedCells": sum(changed.values()),
        "changesByColumn": dict(changed), "prizeColumnsAdded": [h for h in money_headers if h not in headers],
        "removedColumns": [h for h in headers if h not in expected],
        "drawIdentityVerified": len(cleaned), "completePrizeRows": len(cleaned),
    }


def clean_scoring(slug, headers, rows):
    if headers != SCORING_HEADER:
        raise ValueError(f"Unexpected scoring schema: {slug}")
    expected_numbers = set(SCORING_UNIVERSES[slug])
    cleaned, duplicates, changed = {}, 0, Counter()
    for original in rows:
        row = {name: value.strip() for name, value in original.items()}
        for name in SCORING_HEADER[:5]:
            if not re.fullmatch(r"[0-9]+", row[name]):
                raise ValueError(f"Invalid scoring integer: {slug} {name}")
        number = int(row["number"])
        if number not in expected_numbers or int(row["rank"]) < 1:
            raise ValueError(f"Out-of-range scoring rank or number: {slug}")
        for name in ("rank", "frequencyCount", "recentCount", "currentDelay"):
            row[name] = str(int(row[name]))
        row["number"] = f"{number:03d}" if slug.startswith("max_3d") else str(number)
        if int(row["recentCount"]) > int(row["frequencyCount"]):
            raise ValueError(f"Recent count exceeds total frequency: {slug} {number}")
        for name in SCORING_HEADER[5:]:
            value = float(row[name])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Invalid scoring value: {slug} {number} {name}")
        if number in cleaned:
            if row != cleaned[number]:
                raise ValueError(f"Conflicting scoring duplicate: {slug} {number}")
            duplicates += 1
            continue
        cleaned[number] = row
        changed.update(name for name in headers if row[name] != original[name])
    if set(cleaned) != expected_numbers:
        raise ValueError(f"Incomplete scoring number universe: {slug}")
    output = sorted(cleaned.values(), key=lambda row: int(row["rank"]))
    if [int(row["rank"]) for row in output] != list(range(1, len(output) + 1)):
        raise ValueError(f"Missing or duplicate scoring ranks: {slug}")
    if any(float(a["Score_i"]) < float(b["Score_i"]) for a, b in zip(output, output[1:])):
        raise ValueError(f"Ranks contradict scoring values: {slug}")
    return headers, output, {"duplicateRowsRemoved": duplicates,
        "changedCells": sum(changed.values()), "changesByColumn": dict(changed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--canonical-report", type=Path, required=True)
    args = parser.parse_args()
    canonical_report = json.loads(args.canonical_report.read_text(encoding="utf-8"))
    if canonical_report.get("errors"):
        raise ValueError("Resolve canonical audit errors before cleaning related CSVs")
    stamp = datetime.now()
    run = ROOT / "runtime" / f"csv_cleaning_{stamp.date().isoformat()}" / stamp.strftime("%H%M%S_%f")
    (run / "before").mkdir(parents=True)
    report = {"startedAt": lr.now_iso(), "applied": False, "files": {}, "errors": [],
              "canonicalReport": str(args.canonical_report.resolve()),
              "canonicalTypes": canonical_report["types"], "warnings": canonical_report.get("warnings", []),
              "backupDirectory": str(run / "before")}
    jobs = [(key, ROOT / "ai/standalone_predictors" / rel, "snapshot") for key, rel in SNAPSHOTS.items()]
    jobs += [(slug, ROOT / "data/exports/scoring" / f"{slug}_number_scoring_full_latest.csv", "scoring")
             for slug in SCORING_UNIVERSES]
    pending, source_hashes = [], {}
    for key, path, kind in jobs:
        relative = path.relative_to(ROOT)
        backup = run / "before" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        try:
            raw, headers, rows, blanks = read_csv(path)
            if kind == "snapshot":
                source_path = lr.get_canonical_output_paths(key)["all"]
                source_hashes[source_path] = hashlib.sha256(source_path.read_bytes()).hexdigest()
                canonical, info = lr.load_csv_rows(source_path, return_info=True)
                if info["sanitized"]:
                    raise ValueError(f"Canonical loader sanitized input: {key}")
                output_headers, output_rows, info = clean_snapshot(key, headers, rows, canonical)
            else:
                output_headers, output_rows, info = clean_scoring(key, headers, rows)
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=output_headers)
            writer.writeheader()
            writer.writerows(output_rows)
            text = buffer.getvalue()
            changed = headers != output_headers or rows != output_rows or blanks > 0
            report["files"][relative.as_posix()] = {"kind": kind, "inputRows": len(rows),
                "outputRows": len(output_rows), "blankRowsRemoved": blanks, "changed": changed, **info}
            pending.append((path, hashlib.sha256(raw).hexdigest(), text, changed))
        except (ValueError, KeyError, csv.Error) as exc:
            report["errors"].append({"file": relative.as_posix(), "message": str(exc)})
    if args.apply and not report["errors"]:
        for path, digest in list(source_hashes.items()) + [(p, h) for p, h, _, _ in pending]:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Input changed during cleaning: {path}")
        for path, _, text, changed in pending:
            if changed:
                lr.atomic_replace_text(path, text)
        report["applied"] = True
    report["finishedAt"] = lr.now_iso()
    lr.write_json_file(run / "report.json", report)
    lines = ["# Làm sạch CSV dự án", "",
             f"Áp dụng: {report['applied']}. Lỗi: {len(report['errors'])}.", "",
             "| CSV | Số dòng | Ô thay đổi |", "|---|---:|---:|"]
    lines += [f"| {path} | {info['outputRows']} | {info['changedCells']} |" for path, info in report["files"].items()]
    lines += ["", "CSV bộ dự đoán được giữ nguyên phạm vi kỳ; tiền thưởng đối chiếu với CSV canonical.",
              "CSV điểm số được kiểm tra đủ số, hạng duy nhất, điểm hữu hạn và thứ tự xếp hạng."]
    for warning in report["warnings"]:
        lines.append(f"Cảnh báo nguồn {warning['type']}: {warning.get('draws', [])}, {warning.get('times', [])}; giữ nguyên giờ đã xác minh.")
    lr.atomic_replace_text(run / "report.md", "\n".join(lines) + "\n")
    print(json.dumps({"applied": report["applied"], "files": report["files"],
                      "errors": report["errors"], "report": str(run / "report.md")}, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
