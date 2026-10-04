"""Audit canonical CSVs, optionally applying validated, backed-up corrections.

Invalid or contradictory rows block all writes; no draws are invented or silently
dropped. Max 3D repairs require cached results freshly parsed from source pages.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.live_results as lr

SPECS = {"KENO": (20, 80), "LOTO_5_35": (5, 35), "LOTO_6_45": (6, 45), "LOTO_6_55": (6, 55)}
GROUPS = [("Đặc biệt", 2), ("Giải nhất", 4), ("Giải nhì", 6), ("Giải ba", 8)]
LABEL_ALIASES = {
    "LOTO_5_35": {"5/35", "loto5/35", "lotto5/35"},
    "LOTO_6_45": {"6/45", "mega6/45"},
    "LOTO_6_55": {"6/55", "power6/55"},
    "MAX_3D": {"max3d"}, "MAX_3D_PRO": {"max3dpro", "3dpro"},
}
LOCAL = threading.local()


def max_groups(value):
    groups = value.split(" || ")
    if len(groups) != 4:
        raise ValueError("Max 3D must have four prize groups")
    result = []
    for group, (label, _) in zip(groups, GROUPS):
        name, separator, numbers = group.partition(":")
        if not separator or name.strip() != label or not re.fullmatch(r"\d{3}(?:\s+\d{3})*", numbers.strip()):
            raise ValueError(f"Invalid Max 3D group: {group}")
        result.append(numbers.split())
    return result


def normalize_row(key, original, evidence=None):
    if key != "KENO":
        original = lr.expand_csv_record(key, original)
    row = {k: v.strip() for k, v in original.items()}
    if not re.fullmatch(r"#?\d+", row["Kỳ"]) or int(row["Kỳ"].lstrip("#")) <= 0:
        raise ValueError("Invalid draw ID")
    row["Kỳ"] = str(int(row["Kỳ"].lstrip("#")))
    day = lr.parse_csv_date(row["Ngày"])
    if not day:
        raise ValueError("Invalid draw date")
    row["Ngày"], row["Thứ"] = lr.format_csv_date(day), lr.format_csv_weekday(day)
    if row["Giờ"]:
        if not re.fullmatch(r"\d{1,2}:\d{2}", row["Giờ"]):
            raise ValueError("Invalid draw time")
        row["Giờ"] = lr.normalize_draw_time_slot(row["Giờ"])
        if lr.parse_time_to_minutes(row["Giờ"]) is None or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", row["Giờ"]):
            raise ValueError("Invalid draw time range")
    if key in ("KENO", "LOTO_5_35") and not row["Giờ"]:
        raise ValueError("Missing draw time")
    if key == "LOTO_5_35" and row["Giờ"] not in ("13:00", "21:00"):
        raise ValueError("Unexpected Loto 5/35 time")
    if key != "KENO":
        label = lr.normalize_header_label(row["Loại"]).replace("_", "").replace(" ", "")
        if label not in LABEL_ALIASES[key]:
            raise ValueError("Conflicting game label")
        row["Loại"] = lr.LIVE_TYPES[key].label
        source_day = lr.parse_csv_date(row["Ngày cập nhật"])
        if not source_day:
            raise ValueError("Invalid source date")
        row["Ngày cập nhật"] = lr.format_csv_date(source_day)
    if not re.fullmatch(r"https?://[^\s]+", row["Link cập nhật"]):
        raise ValueError("Invalid source URL")
    if key in SPECS:
        count, limit = SPECS[key]
        tokens = row["Bộ Số"].split(",")
        if any(not token.strip().isdigit() for token in tokens):
            raise ValueError("Invalid draw numbers")
        values = [int(token) for token in tokens]
        if len(values) != count or len(set(values)) != count or any(not 1 <= v <= limit for v in values):
            raise ValueError("Wrong draw count, repeated numbers, or out-of-range number")
        # Retain source order; repeated numbers inside one numeric ticket are invalid.
        row["Bộ Số"] = ",".join(map(str, values))
        if key == "KENO":
            row["Lớn/-/Nhỏ"], row["Chẵn/-/Lẻ"] = lr.calc_keno_ln(values), lr.calc_keno_cl(values)
        else:
            special = row["ĐB"]
            if key in ("LOTO_5_35", "LOTO_6_55"):
                special_limit = 12 if key == "LOTO_5_35" else 55
                if not special.isdigit() or not 1 <= int(special) <= special_limit:
                    raise ValueError("Invalid special number")
                if key == "LOTO_6_55" and int(special) in values:
                    raise ValueError("Power special number occurs among main numbers")
                row["ĐB"] = str(int(special))
            elif special:
                raise ValueError("Mega has no special number")
            row["Hiển thị"] = " ".join(f"{v:02d}" for v in values)
            if row["ĐB"]:
                row["Hiển thị"] += f" | ĐB {int(row['ĐB']):02d}"
    else:
        if any(row[field] for field in ("Giờ", "Bộ Số", "ĐB")):
            raise ValueError("Unexpected Max 3D data in unused columns")
        old_groups = max_groups(row["Hiển thị"])
        if evidence:
            if evidence["ky"] != row["Kỳ"] or evidence["date"] != row["Ngày"]:
                raise ValueError("Source draw identity mismatch")
            source_display = " || ".join(evidence["displayLines"])
            correct_groups = max_groups(source_display)
            for old, correct, (_, count) in zip(old_groups, correct_groups, GROUPS):
                if len(correct) != count:
                    raise ValueError("Incomplete source result")
                # The known parser defect prepends one three-digit winner count.
                if old != correct and not (len(old) == count + 1 and old[1:] == correct):
                    raise ValueError("Source contradicts stored Max 3D balls")
            row["Hiển thị"] = source_display
        elif any(len(group) != count for group, (_, count) in zip(old_groups, GROUPS)):
            raise ValueError("Wrong Max 3D group size; source verification required")
    for field in lr.PRIZE_FIELDS_BY_TYPE.get(key, ()):
        header = lr.PRIZE_CSV_HEADERS[field]
        text = row[header]
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
            text = re.sub(r"[.,]", "", text)
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Missing or invalid prize amount")
        row[header] = str(int(text))
    if key in lr.PRIZE_FIELDS_BY_TYPE and not lr.valid_prize_hit(key, row[lr.PRIZE_HIT_HEADER]):
        raise ValueError("Invalid top prize hit marker")
    return row


def fetch_max_page(day, work):
    cache = work / "max3d_pages" / f"{day.isoformat()}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["results"]
    if not hasattr(LOCAL, "session"):
        LOCAL.session = lr.create_session()
    url = lr.HISTORY_URL_PATTERNS["MAX_3D"].format(date=day.strftime("%d-%m-%Y"))
    html = lr.fetch_url_text(LOCAL.session, url)
    if not html:
        raise ValueError(f"Empty source page: {url}")
    results = []
    for section in lr.extract_draw_sections(lr.html_to_lines(html)):
        if lr.section_matches_cfg(lr.LIVE_TYPES["MAX_3D"], section):
            result = lr.parse_max3d_section(lr.LIVE_TYPES["MAX_3D"], section, url)
            if result and lr.parse_csv_date(result["date"]) <= day:
                results.append(result)
    if not results:
        raise ValueError(f"No valid source results: {url}")
    lr.atomic_replace_text(cache, json.dumps({"sourceUrl": url, "retrievedAt": lr.now_iso(),
        "htmlSha256": hashlib.sha256(html.encode()).hexdigest(), "results": results}, ensure_ascii=False, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-max3d-source", action="store_true")
    parser.add_argument("--keno-evidence-file", type=Path,
                        help="Source draw JSON used to verify and flag existing timestamp anomalies")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    stamp = datetime.now()
    work = ROOT / "runtime" / f"data_cleaning_{stamp.date().isoformat()}"
    run = work / "runs" / stamp.strftime("%H%M%S_%f")
    (run / "before").mkdir(parents=True)
    (work / "max3d_pages").mkdir(parents=True, exist_ok=True)
    inputs, hashes, headers = {}, {}, {}
    for key in lr.LIVE_TYPES:
        path = lr.get_canonical_output_paths(key)["all"]
        raw = path.read_bytes()
        hashes[key] = hashlib.sha256(raw).hexdigest()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        headers[key] = reader.fieldnames
        expected = lr.get_csv_header(key)
        legacy = lr.KENO_CSV_HEADER if key == "KENO" else lr.CSV_HEADER + [
            lr.PRIZE_CSV_HEADERS[f] for f in lr.PRIZE_FIELDS_BY_TYPE.get(key, ())]
        if headers[key] not in (expected, [h for h in expected if h != lr.PRIZE_HIT_HEADER], legacy):
            raise ValueError(f"Unexpected schema: {path}")
        inputs[key] = list(reader)
        for source in (path, lr.get_canonical_meta_path(key)):
            shutil.copy2(source, run / "before" / source.name)
    evidence = {}
    if args.verify_max3d_source:
        rows = sorted(inputs["MAX_3D"], key=lambda row: int(row["Kỳ"]), reverse=True)
        days = {lr.parse_csv_date(row["Ngày"]) for row in rows[::5]}
        print(f"Verifying MAX_3D: {len(days)} source pages", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 6))) as pool:
            futures = [pool.submit(fetch_max_page, day, work) for day in days]
            for index, future in enumerate(as_completed(futures), 1):
                for result in future.result():
                    old = evidence.get(result["ky"])
                    if old and (old["date"], old["displayLines"]) != (result["date"], result["displayLines"]):
                        raise ValueError("Conflicting source pages")
                    evidence[result["ky"]] = result
                if index % 25 == 0 or index == len(days):
                    print(f"MAX_3D pages={index}/{len(days)} verifiedDraws={len(evidence)}", flush=True)
    keno_evidence = {}
    if args.keno_evidence_file:
        for result in json.loads(args.keno_evidence_file.read_text(encoding="utf-8")):
            if result.get("key") != "KENO" or result.get("sourceUrl") != lr.KENO_URL:
                raise ValueError("Unexpected Keno evidence source")
            keno_evidence[result["ky"]] = result
    report = {"startedAt": stamp.isoformat(timespec="seconds"), "applied": False,
              "types": {}, "errors": [], "warnings": [], "changes": [], "backupDirectory": str(run / "before")}
    outputs = {}
    for key, rows in inputs.items():
        cleaned, changes = {}, Counter()
        duplicates = 0
        for line, original in enumerate(rows, 2):
            try:
                if None in original or any(v is None for v in original.values()):
                    raise ValueError("Malformed CSV row width")
                row = normalize_row(key, original, evidence.get(original["Kỳ"]) if key == "MAX_3D" else None)
                ky = row["Kỳ"]
                if ky in cleaned:
                    if cleaned[ky] != row:
                        raise ValueError("Conflicting duplicate draw")
                    duplicates += 1
                    continue
                cleaned[ky] = row
                for field in headers[key]:
                    if row[field] != original[field]:
                        changes[field] += 1
                        item = {"type": key, "ky": ky, "field": field,
                                "before": original[field], "after": row[field]}
                        if key == "MAX_3D" and field == "Hiển thị":
                            item["sourceUrl"] = evidence[ky]["sourceUrl"]
                        report["changes"].append(item)
            except (ValueError, KeyError) as exc:
                report["errors"].append({"type": key, "line": line,
                                         "ky": original.get("Kỳ"), "message": str(exc)})
        outputs[key] = sorted(cleaned.values(), key=lambda r: int(r["Kỳ"]), reverse=True)
        ids = sorted(map(int, cleaned))
        gaps = [[a + 1, b - 1] for a, b in zip(ids, ids[1:]) if b > a + 1]
        timeline = [(lr.parse_csv_date(cleaned[str(ky)]["Ngày"]), cleaned[str(ky)]["Giờ"]) for ky in ids]
        for a, b in zip(ids, ids[1:]):
            first, second = cleaned[str(a)], cleaned[str(b)]
            if (lr.parse_csv_date(first["Ngày"]), first["Giờ"]) >= (lr.parse_csv_date(second["Ngày"]), second["Giờ"]):
                confirmed = key == "KENO" and all(
                    r["Kỳ"] in keno_evidence
                    and keno_evidence[r["Kỳ"]]["date"] == r["Ngày"]
                    and keno_evidence[r["Kỳ"]]["time"] == r["Giờ"]
                    and ",".join(map(str, keno_evidence[r["Kỳ"]]["main"])) == r["Bộ Số"]
                    for r in (first, second))
                item = {"type": key, "draws": [str(a), str(b)], "date": first["Ngày"],
                        "times": [first["Giờ"], second["Giờ"]],
                        "message": "Draw IDs contradict chronological order"}
                if confirmed:
                    item.update({"sourceUrl": lr.KENO_URL, "sourceConfirmed": True,
                                 "resolution": "Preserved source timestamps; no inferred correction"})
                    report["warnings"].append(item)
                else:
                    report["errors"].append(item)
        if any(day > stamp.date() for day, _ in timeline):
            report["errors"].append({"type": key, "message": "Future draw date"})
        report["types"][key] = {"inputRows": len(rows), "outputRows": len(cleaned),
            "removedColumns": [field for field in headers[key] if field not in lr.get_csv_header(key)],
            "outputColumns": lr.get_csv_header(key),
            "duplicateRowsRemoved": duplicates, "changedCells": sum(changes.values()),
            "changesByColumn": dict(changes), "internalGaps": gaps,
            "missingDrawsInsideRange": sum(b - a + 1 for a, b in gaps),
            "earliestKy": str(ids[0]) if ids else "", "latestKy": str(ids[-1]) if ids else "",
            "sourceVerifiedDraws": (sum(ky in evidence for ky in cleaned) if key == "MAX_3D"
                                    else sum(ky in keno_evidence for ky in cleaned) if key == "KENO" else 0),
            "warnings": sum(e["type"] == key for e in report["warnings"]),
            "errors": sum(e["type"] == key for e in report["errors"])}
    if args.apply and not report["errors"]:
        # Validate all inputs again before committing any file.
        for key in inputs:
            path = lr.get_canonical_output_paths(key)["all"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
                raise RuntimeError(f"Input changed during audit: {path}")
        for key, rows in outputs.items():
            path = lr.get_canonical_output_paths(key)["all"]
            output_headers = lr.get_csv_header(key)
            projected = [{field: row[field] for field in output_headers} for row in rows]
            if headers[key] != output_headers or projected != inputs[key]:
                buffer = io.StringIO(newline="")
                writer = csv.DictWriter(buffer, fieldnames=output_headers)
                writer.writeheader()
                writer.writerows(projected)
                lr.atomic_replace_text(path, buffer.getvalue())
            meta = lr.read_canonical_meta(key)
            meta["dataQuality"] = {**report["types"][key], "checkedAt": lr.now_iso(),
                "valid": not report["types"][key]["warnings"], "structuralValid": True,
                "warningDetails": [e for e in report["warnings"] if e["type"] == key],
                "reportFile": str(run / "report.json"),
                "scope": "Existing canonical draws; no history extrapolation"}
            lr.write_canonical_meta(key, meta)
        report["applied"] = True
    report["finishedAt"] = lr.now_iso()
    lr.write_json_file(run / "report.json", report)
    summary = ["# Kiểm tra và làm sạch dữ liệu", "",
               f"Áp dụng: {report['applied']}. Lỗi: {len(report['errors'])}. Cảnh báo nguồn: {len(report['warnings'])}.", "",
               "| Loại | Số kỳ | Ô đã sửa | Kỳ thiếu trong phạm vi | Lỗi |",
               "|---|---:|---:|---:|---:|"]
    for key, info in report["types"].items():
        summary.append(f"| {key} | {info['outputRows']} | {info['changedCells']} | {info['missingDrawsInsideRange']} | {info['errors']} |")
    summary += ["", "Max 3D giữ đủ 2/4/6/8 bộ ba số theo nhóm giải, kể cả bộ lặp và số 0 ở đầu.",
                "Tiền thưởng, kỳ, ngày, giờ và nguồn không bị suy diễn. Lịch sử trước kỳ đầu trong CSV chưa được kiểm chứng."]
    for warning in report["warnings"]:
        summary += ["", f"Cảnh báo {warning['type']} {warning['date']}: kỳ {' → '.join(warning['draws'])}, giờ {' → '.join(warning['times'])}.",
                    f"Trang nguồn cũng ghi như vậy; giữ nguyên và đánh dấu trong metadata. Nguồn: {warning['sourceUrl']}"]
    lr.atomic_replace_text(run / "report.md", "\n".join(summary) + "\n")
    print(json.dumps(report["types"], ensure_ascii=False, indent=2), flush=True)
    print(f"Report: {run / 'report.md'}", flush=True)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
