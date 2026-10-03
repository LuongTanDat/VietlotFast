"""Backfill only advertised top-prize amounts for existing canonical draws.

Caches source evidence, backs up inputs, and checks draw identity before changing
money columns. Re-running retries missing amounts without changing result data.
"""
import argparse
import copy
import hashlib
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.live_results as lr

LOCAL = threading.local()


def fetch_page(type_key, day, work):
    cfg = lr.LIVE_TYPES[type_key]
    url = lr.HISTORY_URL_PATTERNS[type_key].format(date=day.strftime("%d-%m-%Y"))
    cache = work / "pages" / f"{type_key}_{day.isoformat()}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["results"]
    if not hasattr(LOCAL, "session"):
        LOCAL.session = lr.create_session()
    html = lr.fetch_url_text(LOCAL.session, url)
    if not html:
        raise RuntimeError(f"No source content: {url}")
    results = []
    for section in lr.extract_draw_sections(lr.html_to_lines(html)):
        if lr.section_matches_cfg(cfg, section):
            result = lr.parse_numeric_section(cfg, section, url)
            if result and lr.parse_csv_date(result["date"]) <= day:
                results.append(result)
    if not results:
        raise RuntimeError(f"No draws found: {url}")
    lr.atomic_replace_text(cache, json.dumps({"sourceUrl": url,
        "retrievedAt": lr.now_iso(), "htmlSha256": hashlib.sha256(html.encode()).hexdigest(),
        "results": results}, ensure_ascii=False, indent=2))
    time.sleep(0.2)
    return results


def apply_prizes(type_key, rows, results):
    changed = 0
    for result in results:
        row = rows.get(result["ky"])
        if row is None:
            continue
        parsed = lr.result_to_csv_row(result)
        for field in ("Ngay", "Time", "Main", "Special"):
            if row.get(field, "") != parsed.get(field, ""):
                raise ValueError(f"Draw mismatch: {type_key} #{result['ky']} {field}")
        for field in lr.PRIZE_FIELDS_BY_TYPE[type_key]:
            if parsed.get(field) and row.get(field) != parsed[field]:
                row[field] = parsed[field]
                changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--supplemental-file", type=Path,
                        help="JSON draw results from a verified alternate source; identity is checked")
    args = parser.parse_args()
    work = ROOT / "runtime" / f"prize_backfill_{datetime.now().date().isoformat()}"
    (work / "before").mkdir(parents=True, exist_ok=True)
    (work / "pages").mkdir(exist_ok=True)
    rows_by_type, before = {}, {}
    report = {"source": "https://www.minhchinh.com/", "unit": "VND",
              "amountMeaning": "Advertised draw prize pool, before division among winners",
              "startedAt": lr.now_iso(), "types": {}, "errors": []}
    for key in lr.PRIZE_FIELDS_BY_TYPE:
        path = lr.get_canonical_output_paths(key)["all"]
        for source in (path, lr.get_canonical_meta_path(key)):
            target = work / "before" / source.name
            if not target.exists():
                shutil.copy2(source, target)
        rows, info = lr.load_csv_rows(path, return_info=True)
        if info["sanitized"]:
            raise RuntimeError(f"Malformed input {path}: {info}")
        rows_by_type[key] = rows
        before[key] = copy.deepcopy(rows)

    supplemental_sources = {}
    if args.supplemental_file:
        supplemental = json.loads(args.supplemental_file.read_text(encoding="utf-8"))
        for result in supplemental:
            key = result["key"]
            if result["ky"] not in rows_by_type[key]:
                raise ValueError(f"Unknown supplemental draw: {key} #{result['ky']}")
            if not str(result.get("sourceUrl", "")).startswith("https://"):
                raise ValueError("Supplemental source URL is required")
            apply_prizes(key, rows_by_type[key], [result])
            supplemental_sources.setdefault(key, {})[result["ky"]] = result["sourceUrl"]
        report["supplementalSources"] = supplemental_sources

    def pending(key):
        return sorted((r for r in rows_by_type[key].values()
                       if any(not r.get(f) for f in lr.PRIZE_FIELDS_BY_TYPE[key])),
                      key=lambda r: int(r["Ky"]), reverse=True)

    def checkpoint():
        for key, rows in rows_by_type.items():
            # Reload to retain any new draws written by the live updater.
            path = lr.get_canonical_output_paths(key)["all"]
            current = lr.load_csv_rows(path)
            for ky, row in rows.items():
                if ky not in current:
                    raise RuntimeError(f"Draw removed during backfill: {key} #{ky}")
                for field in lr.CSV_FIELDS:
                    if current[ky].get(field) != row.get(field):
                        raise RuntimeError(f"Draw changed during backfill: {key} #{ky} {field}")
                for field in lr.PRIZE_FIELDS_BY_TYPE[key]:
                    if row.get(field):
                        current[ky][field] = row[field]
            rows.update(current)
            lr.write_csv_rows(path, rows, type_key=key)
            missing = pending(key)
            status = {"totalRows": len(rows), "completeRows": len(rows) - len(missing),
                      "missingRows": len(missing), "missingDraws": [r["Ky"] for r in missing],
                      "columns": [lr.PRIZE_CSV_HEADERS[f] for f in lr.PRIZE_FIELDS_BY_TYPE[key]]}
            report["types"][key] = status
            meta = lr.read_canonical_meta(key)
            meta["prizeAmounts"] = lr.build_prize_amount_meta(key, rows, meta.get("prizeAmounts"))
            if key in supplemental_sources:
                meta["prizeAmounts"].setdefault("sourceOverrides", {}).update(supplemental_sources[key])
            lr.write_canonical_meta(key, meta)
        report["updatedAt"] = lr.now_iso()
        lr.write_json_file(work / "report.json", report)

    # Each page contains up to five consecutive draws, so start with every fifth
    # missing draw, then retry uncovered draws by exact date.
    for phase in range(2):
        jobs = set()
        for key in rows_by_type:
            candidates = pending(key)
            for row in (candidates[::5] if phase == 0 else candidates):
                jobs.add((key, lr.parse_csv_date(row["Ngay"])))
        jobs = sorted(jobs, key=lambda item: item[1], reverse=True)
        print(f"phase={phase + 1} pages={len(jobs)}", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            futures = {pool.submit(fetch_page, key, day, work): (key, day) for key, day in jobs}
            for index, future in enumerate(as_completed(futures), 1):
                key, day = futures[future]
                try:
                    apply_prizes(key, rows_by_type[key], future.result())
                except Exception as exc:
                    error = {"type": key, "date": day.isoformat(), "message": str(exc)}
                    report["errors"].append(error)
                    print(json.dumps(error, ensure_ascii=False), flush=True)
                if index % 50 == 0 or index == len(jobs):
                    checkpoint()
                    counts = {key: len(pending(key)) for key in rows_by_type}
                    print(f"phase={phase + 1} done={index}/{len(jobs)} missing={counts}", flush=True)
        checkpoint()
    for key, original in before.items():
        for ky, row in original.items():
            assert all(rows_by_type[key][ky][f] == row[f] for f in lr.CSV_FIELDS), (key, ky)
    report["finishedAt"] = lr.now_iso()
    lr.write_json_file(work / "report.json", report)
    print(json.dumps(report["types"], ensure_ascii=False, indent=2), flush=True)
    return 1 if any(pending(key) for key in rows_by_type) else 0


if __name__ == "__main__":
    sys.exit(main())
