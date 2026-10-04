"""Verify top-prize winner counts and add a sparse hit marker to existing CSVs."""
import argparse
import hashlib
import json
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.live_results as lr
from scripts.clean_related_csv import SNAPSHOTS

LOCAL = threading.local()


def parse_page(key, html, url, day):
    cfg = lr.LIVE_TYPES[key]
    results = []
    for section in lr.extract_draw_sections(lr.html_to_lines(html)):
        if lr.section_matches_cfg(cfg, section):
            result = lr.parse_numeric_section(cfg, section, url)
            if result and lr.parse_csv_date(result["date"]) <= day:
                results.append(result)
    return results


def fetch_page(key, day, work):
    url = lr.HISTORY_URL_PATTERNS[key].format(date=day.strftime("%d-%m-%Y"))
    cache = work / "pages" / f"{key}_{day.isoformat()}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["results"]
    if not hasattr(LOCAL, "session"):
        LOCAL.session = lr.create_session()
    html = lr.fetch_url_text(LOCAL.session, url)
    results = parse_page(key, html, url, day)
    if not results:
        raise ValueError(f"No source draws: {url}")
    lr.atomic_replace_text(cache.with_suffix(".html"), html)
    lr.write_json_file(cache, {"sourceUrl": url, "retrievedAt": lr.now_iso(),
                              "htmlSha256": hashlib.sha256(html.encode()).hexdigest(), "results": results})
    return results


def verify_result(key, row, result):
    parsed = lr.result_to_csv_row(result)
    if any(row.get(field, "") != parsed.get(field, "") for field in ("Ky", "Ngay", "Time", "Main", "Special")):
        raise ValueError(f"Source identity mismatch: {key} #{result['ky']}")
    if not result.get("prizeHitKnown"):
        return None
    marker = parsed[lr.PRIZE_HIT_FIELD]
    if not lr.valid_prize_hit(key, marker):
        raise ValueError(f"Invalid source marker: {key} #{result['ky']}")
    fields = lr.PRIZE_FIELDS_BY_TYPE[key]
    counts = result.get("prizeWinnerCounts", {})
    if set(counts) != {lr.PRIZE_RESULT_KEYS[field] for field in fields} or any(type(v) is not int or v < 0 for v in counts.values()):
        raise ValueError(f"Missing or invalid source winner counts: {key} #{result['ky']}")
    hits = [label for field, label in zip(fields, lr.PRIZE_HIT_LABELS[key]) if counts[lr.PRIZE_RESULT_KEYS[field]] > 0]
    expected = "Jackpot 1, 2" if len(hits) == 2 else (hits[0] if hits else "")
    if marker != expected:
        raise ValueError(f"Marker contradicts source winner counts: {key} #{result['ky']}")
    return marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--supplemental-file", type=Path,
                        help="Verified draw JSON from an alternate source, including winner counts and URL")
    args = parser.parse_args()
    work = ROOT / "runtime" / f"prize_hits_{datetime.now().date().isoformat()}"
    (work / "pages").mkdir(parents=True, exist_ok=True)
    paths = {key: lr.get_canonical_output_paths(key)["all"] for key in lr.PRIZE_FIELDS_BY_TYPE}
    rows = {}
    for key, path in paths.items():
        rows[key], info = lr.load_csv_rows(path, return_info=True, type_key=key)
        if info["sanitized"]:
            raise ValueError(f"Malformed canonical input: {key}")
    verified = {key: {} for key in paths}
    report = {"startedAt": lr.now_iso(), "applied": False, "types": {}, "errors": [], "sourceMismatches": []}

    def absorb(key, results):
        for result in results:
            ky = result["ky"]
            if ky not in rows[key]:
                continue
            try:
                marker = verify_result(key, rows[key][ky], result)
                if marker is None:
                    continue
                previous = verified[key].get(ky)
                if previous and previous["prizeHit"] != marker:
                    raise ValueError(f"Conflicting source winner counts: {key} #{ky}")
                verified[key][ky] = result
            except ValueError as exc:
                report["sourceMismatches"].append({"type": key, "ky": ky, "sourceUrl": result["sourceUrl"], "message": str(exc)})

    for cache in sorted((work / "pages").glob("*.json")):
        for result in json.loads(cache.read_text(encoding="utf-8"))["results"]:
            if result.get("key") in paths:
                absorb(result["key"], [result])
    if args.supplemental_file:
        supplemental = json.loads(args.supplemental_file.read_text(encoding="utf-8"))
        for result in supplemental:
            if result.get("key") not in paths or not str(result.get("sourceUrl", "")).startswith("https://"):
                raise ValueError("Invalid supplemental type or source URL")
            absorb(result["key"], [result])
        report["supplementalSources"] = [{"type": result["key"], "ky": result["ky"],
                                          "sourceUrl": result["sourceUrl"]} for result in supplemental]

    # Every source page shows several consecutive draws; use sparse pages first,
    # then fetch the exact date for any draw still missing verified counts.
    for phase in range(2):
        jobs = set()
        for key in paths:
            pending = sorted((row for ky, row in rows[key].items() if ky not in verified[key]),
                             key=lambda row: int(row["Ky"]), reverse=True)
            for row in (pending[::5] if phase == 0 else pending):
                jobs.add((key, lr.parse_csv_date(row["Ngay"])))
        jobs = sorted(jobs, key=lambda job: job[1], reverse=True)
        print(f"phase={phase + 1} sourcePages={len(jobs)}", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 6))) as pool:
            futures = {pool.submit(fetch_page, key, day, work): (key, day) for key, day in jobs}
            for index, future in enumerate(as_completed(futures), 1):
                key, day = futures[future]
                try:
                    absorb(key, future.result())
                except Exception as exc:
                    report["errors"].append({"type": key, "date": day.isoformat(), "message": str(exc)})
                if index % 25 == 0 or index == len(jobs):
                    print(f"pages={index}/{len(jobs)} verified=" + str({key: len(items) for key, items in verified.items()}), flush=True)

    for key in paths:
        missing = sorted(set(rows[key]) - set(verified[key]), key=int)
        hits = {}
        for result in verified[key].values():
            if result["prizeHit"]:
                hits[result["prizeHit"]] = hits.get(result["prizeHit"], 0) + 1
        report["types"][key] = {"rows": len(rows[key]), "verifiedRows": len(verified[key]),
                                "missingDraws": missing, "hitCounts": hits}
    lr.write_json_file(work / "verified_draws.json", verified)

    if args.apply and all(not info["missingDraws"] for info in report["types"].values()):
        outputs = []
        for key, path in paths.items():
            current, info = lr.load_csv_rows(path, return_info=True, type_key=key)
            if info["sanitized"] or set(current) != set(rows[key]):
                raise RuntimeError(f"History changed during verification: {key}; rerun with cached evidence")
            for ky, result in verified[key].items():
                current[ky][lr.PRIZE_HIT_FIELD] = verify_result(key, current[ky], result)
            outputs.append((key, path, current))
            snapshot_path = ROOT / "ai/standalone_predictors" / SNAPSHOTS[key]
            snapshot, info = lr.load_csv_rows(snapshot_path, return_info=True, type_key=key)
            if info["sanitized"]:
                raise ValueError(f"Malformed predictor snapshot: {key}")
            for ky, row in snapshot.items():
                row[lr.PRIZE_HIT_FIELD] = verify_result(key, row, verified[key][ky])
            outputs.append((key, snapshot_path, snapshot))
        # Prepare and validate every output before committing; the project Bin
        # backup must cover each CSV at its current revision.
        for key, path, _ in outputs:
            backup = ROOT / "Bin/session_1_latest/files" / path.relative_to(ROOT)
            if not backup.exists():
                raise RuntimeError(f"Missing project Bin backup: {path}")
            target = work / "before" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        for key, path, output in outputs:
            lr.write_csv_rows(path, output, type_key=key)
        for key in paths:
            meta = lr.read_canonical_meta(key)
            meta["prizeHits"] = {**report["types"][key], "checkedAt": lr.now_iso(), "complete": True,
                                 "meaning": "At least one winning ticket in the top-prize table",
                                 "evidenceFile": str(work / "verified_draws.json")}
            lr.write_canonical_meta(key, meta)
        report["applied"] = True
    report["finishedAt"] = lr.now_iso()
    lr.write_json_file(work / "report.json", report)
    print(json.dumps({"applied": report["applied"], "types": report["types"], "report": str(work / "report.json")}, ensure_ascii=False, indent=2), flush=True)
    return 0 if report["applied"] or not any(info["missingDraws"] for info in report["types"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
