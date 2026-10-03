"""Recover missing canonical history; earlier Keno history requires an explicit flag."""
import argparse
import csv
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup, SoupStrainer, FeatureNotFound

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.live_results as lr

LOCAL = threading.local()


def session():
    if not hasattr(LOCAL, "session"):
        LOCAL.session = lr.create_session()
    return LOCAL.session


def audit(type_key, rows):
    ids = sorted(int(ky) for ky in rows)
    gaps = [[a + 1, b - 1] for a, b in zip(ids, ids[1:]) if b > a + 1]
    latest, earliest = lr.get_latest_and_earliest_rows(rows)
    return {"count": len(rows), "earliestKy": earliest.get("Ky"),
            "earliestDate": earliest.get("Ngay"), "latestKy": latest.get("Ky"),
            "latestDate": latest.get("Ngay"), "latestTime": latest.get("Time"),
            "missingKyCount": sum(b - a + 1 for a, b in gaps), "gaps": gaps}


def keno_day(target, cache_dir, today):
    cache = cache_dir / f"{target.isoformat()}.json"
    if cache.exists() and target < today:
        return target, json.loads(cache.read_text(encoding="utf-8"))
    results = {}
    for page in range(1, lr.KENO_MAX_PAGES_PER_DAY + 1):
        for attempt in range(3):
            response = lr.request_with_retry(session(), "post", lr.KENO_URL,
                                            data={"date": target.strftime("%d-%m-%Y"),
                                                  "ky": "", "number": "", "page": str(page)})
            # Restrict parsing to the result container; large menus are irrelevant.
            try:
                soup = BeautifulSoup(response.text, "lxml", parse_only=SoupStrainer(id="containerKQKeno"))
            except FeatureNotFound:
                soup = BeautifulSoup(response.text, "html.parser", parse_only=SoupStrainer(id="containerKQKeno"))
            if soup.select_one("#frmSearch input[name='date']"):
                break
            # Some historical pages still use the old container structure.
            soup = BeautifulSoup(response.text, "html.parser")
            if soup.select_one("#frmSearch input[name='date']"):
                break
            if attempt == 2:
                (cache_dir / f"failed_{target}_{page}.html").write_text(response.text, encoding="utf-8")
            else:
                time.sleep(1 + attempt)
        form_date = lr.get_keno_search_date(soup)
        if lr.parse_csv_date(form_date) != target:
            raise RuntimeError(f"Requested {target}, source returned {form_date}")
        parsed = lr.parse_keno_rows(soup)
        if any(lr.parse_csv_date(item["date"]) != target for item in parsed):
            raise RuntimeError(f"Source returned another date for {target}")
        new = [item for item in parsed if item["ky"] not in results]
        results.update({item["ky"]: item for item in new})
        pager = soup.select_one(".kn-pager")
        if not new or (pager and not pager.select_one('a[title="Trang sau"]')):
            break
        time.sleep(lr.KENO_REQUEST_DELAY_SECONDS)
    else:
        raise RuntimeError(f"Pagination exceeded limit for {target}")
    values = list(results.values())
    cache.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    return target, values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recent-only", action="store_true")
    parser.add_argument("--full-keno-history", action="store_true")
    parser.add_argument("--keno-only", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    today = datetime.now().date()
    work = ROOT / "runtime" / f"minhchinh_sync_{today}"
    backup = work / "before"
    cache_dir = work / "keno_days"
    backup.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    report_path = work / "report.json"
    report = {"source": "https://www.minhchinh.com/", "requestedThrough": today.isoformat(),
              "startedAt": datetime.now().isoformat(timespec="seconds"), "types": {}, "errors": []}

    def save_report():
        report["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        lr.write_json_file(report_path, report)

    all_rows = {}
    baseline_rows = {}
    for key in lr.LIVE_TYPES:
        path = lr.get_canonical_output_paths(key)["all"]
        for source in [path, lr.get_canonical_meta_path(key)]:
            dest = backup / source.name
            if not dest.exists():
                shutil.copy2(source, dest)
        loader = lr.load_keno_csv_rows if key == "KENO" else lr.load_csv_rows
        rows, info = loader(path, return_info=True)
        if info["sanitized"]:
            raise RuntimeError(f"Malformed CSV {path}: {info}")
        all_rows[key] = rows
        baseline_rows[key] = loader(backup / path.name)
        report["types"][key] = {"before": audit(key, baseline_rows[key]), "after": audit(key, rows),
                                "newRows": len(set(rows) - set(baseline_rows[key])), "updatedRows": 0}
    save_report()

    # The existing numeric synchronizer checks all internal gaps and missing dates.
    for key in lr.LIVE_TYPES:
        if key == "KENO" or args.keno_only:
            continue
        result = lr.sync_all_numeric_type(session(), {}, key, allow_bootstrap=True)
        report["types"][key].update({"newRows": result["newRows"], "updatedRows": result["updatedRows"]})
        report["errors"].extend(result["errors"])
        rows = lr.load_csv_rows(lr.get_canonical_output_paths(key)["all"])
        report["types"][key]["after"] = audit(key, rows)
        save_report()
        print(json.dumps({"type": key, **report["types"][key]}, ensure_ascii=True), flush=True)

    rows = all_rows["KENO"]
    initial = baseline_rows["KENO"]
    grouped = lr.rows_grouped_by_date(rows)
    earliest = min(grouped)
    latest = max(grouped)
    _, gap_dates = lr.count_gap_intervals_for_type("KENO", rows)
    recent = set(gap_dates)
    cursor = latest
    while cursor <= today:
        recent.add(cursor)
        cursor += timedelta(days=1)
    recent.update(d for d, items in grouped.items() if len(items) < 119)
    phases = [sorted(recent, reverse=True)]
    if args.full_keno_history and not args.recent_only:
        # The source exposes Keno's first draw on 23 August 2019.
        historical = []
        cursor = earliest - timedelta(days=1)
        while cursor >= date(2019, 8, 23):
            historical.append(cursor)
            cursor -= timedelta(days=1)
        phases.append(historical)

    def checkpoint():
        # Reload before writing so live updates made during this long job are retained.
        current = lr.load_keno_csv_rows(lr.get_canonical_output_paths("KENO")["all"])
        current.update(rows)
        rows.update(current)
        lr.write_keno_csv_rows(lr.get_canonical_output_paths("KENO")["all"], rows)
        meta = lr.read_canonical_meta("KENO")
        status = audit("KENO", rows)
        full = status["earliestKy"] == "1" and status["missingKyCount"] == 0
        meta.update({"lastSyncAt": datetime.now().isoformat(timespec="seconds"),
                     "effectiveEarliestKy": status["earliestKy"],
                     "effectiveEarliestDate": status["earliestDate"],
                     "bootstrapComplete": full, "sourceLimited": not full})
        if full and not meta.get("lastBootstrapAt"):
            meta["lastBootstrapAt"] = meta["lastSyncAt"]
        lr.write_canonical_meta("KENO", meta)
        report["types"]["KENO"].update({"after": status,
                                        "newRows": len(set(rows) - set(initial)),
                                        "updatedRows": sum(rows[k] != v for k, v in initial.items())})
        save_report()

    for phase, dates in enumerate(phases):
        print(f"KENO phase={phase} days={len(dates)} workers={args.workers}", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(keno_day, target, cache_dir, today): target for target in dates}
            for index, future in enumerate(as_completed(futures), 1):
                target = futures[future]
                try:
                    _, values = future.result()
                    lr.merge_keno_result_rows(rows, values)
                except Exception as exc:
                    report["errors"].append({"type": "KENO", "date": str(target), "message": str(exc)})
                    print(f"ERROR {target}: {exc}", flush=True)
                interval = 20 if phase == 0 else 100
                if index % interval == 0 or index == len(dates):
                    checkpoint()
                    print(f"KENO phase={phase} done={index}/{len(dates)} count={len(rows)} earliest={min(map(int,rows))} errors={len(report['errors'])}", flush=True)
        checkpoint()
    report["finishedAt"] = datetime.now().isoformat(timespec="seconds")
    save_report()
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
