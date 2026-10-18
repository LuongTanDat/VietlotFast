"""Add verified published winner counts to metadata without changing draw CSVs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import live_results as lr

LOCAL = threading.local()
STOP = threading.Event()

def fetch_counts(type_key, row):
    if STOP.is_set():
        raise RuntimeError("Source rate limited; request skipped")
    if not hasattr(LOCAL, "session"):
        LOCAL.session = lr.create_session()
    url = lr.official_prize_counts_url(type_key, row["Ky"])
    try:
        html = lr.fetch_official_counts_html(LOCAL.session, url)
    except lr.requests.HTTPError as exc:
        if (exc.response is not None and exc.response.status_code == 429) or "giới hạn" in str(exc):
            STOP.set()
        raise
    counts = lr.parse_official_prize_winner_counts(type_key, html, row)
    time.sleep(1)
    return {"type": type_key, "ky": row["Ky"], "identity": lr.loto535_draw_identity(row),
            "counts": counts, "sourceUrl": url, "checkedAt": lr.now_iso(),
            "htmlSha256": hashlib.sha256(html.encode()).hexdigest()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--types", nargs="+", choices=list(lr.PRIZE_WINNER_KEYS_BY_TYPE), default=["LOTO_5_35"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--offline", action="store_true", help="Reuse verified evidence without network requests")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000 or not 1 <= args.workers <= 4:
        parser.error("limit 1–10000; workers 1–4")
    work = ROOT/"runtime"/f"prize_winner_counts_{datetime.now().date().isoformat()}"/datetime.now().strftime("%H%M%S_%f")
    work.mkdir(parents=True)
    rows = {key: lr.load_canonical_rows(key, rewrite_if_needed=False)[0] for key in args.types}
    csv_hashes = {key: hashlib.sha256(lr.get_canonical_output_paths(key)["all"].read_bytes()).hexdigest() for key in args.types}
    verified, errors = {key: {} for key in args.types}, []
    # Reuse prior audited top-prize counts, but only for the same actual draw.
    seed = ROOT/"runtime/prize_hits_2026-10-04/verified_draws.json"
    if seed.exists():
        prior = json.loads(seed.read_text(encoding="utf-8-sig"))
        for key in args.types:
            for ky, result in prior.get(key, {}).items():
                row = rows[key].get(ky)
                counts = lr.valid_prize_winner_counts(key, result.get("prizeWinnerCounts"))
                counts = {name:value for name,value in counts.items()
                          if name not in (row.get(lr.PRIZE_WINNER_COUNTS_FIELD) or {})} if row else {}
                if row and counts and lr.loto535_draw_identity(row) == lr.loto535_draw_identity(lr.result_to_csv_row(result)):
                    verified[key][ky] = {"type": key, "ky": ky, "identity": lr.loto535_draw_identity(row),
                                         "counts": counts, "sourceUrl": result.get("sourceUrl", ""),
                                         "checkedAt": "2026-10-04", "evidenceFile": str(seed.relative_to(ROOT))}
    jobs = []
    for key in ([] if args.offline else args.types):
        latest = sorted(rows[key].values(), key=lambda row: int(row["Ky"]), reverse=True)[:args.limit]
        jobs.extend((key, row) for row in latest
                    if not set(lr.PRIZE_WINNER_KEYS_BY_TYPE[key]).issubset(row.get(lr.PRIZE_WINNER_COUNTS_FIELD) or {}))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(fetch_counts, key, row): (key, row["Ky"]) for key, row in jobs}
        for index, future in enumerate(as_completed(pending), 1):
            key, ky = pending[future]
            try:
                evidence = future.result()
                verified[key][ky] = evidence
            except Exception as exc:
                if not future.cancelled():
                    errors.append({"type": key, "ky": ky, "message": str(exc)})
                if STOP.is_set():
                    for waiting in pending:
                        waiting.cancel()
            if index % 25 == 0 or index == len(jobs):
                print(f"checked={index}/{len(jobs)} errors={len(errors)}", flush=True)
    applied = {}
    if args.apply:
        for key in args.types:
            current, meta, _ = lr.load_canonical_rows(key, rewrite_if_needed=False)
            changed = 0
            for ky, evidence in verified[key].items():
                row = current.get(ky)
                if row is None or evidence["identity"] != lr.loto535_draw_identity(row):
                    errors.append({"type":key,"ky":ky,"message":"Draw changed; counts not applied"})
                    continue
                row[lr.PRIZE_WINNER_COUNTS_FIELD] = {**row.get(lr.PRIZE_WINNER_COUNTS_FIELD, {}), **evidence["counts"]}
                row["_PrizeWinnerCountsSource"] = evidence["sourceUrl"]
                row["_PrizeWinnerCountsCheckedAt"] = evidence["checkedAt"]
                changed += 1
            meta["prizeWinners"] = lr.build_prize_winner_meta(key, current)
            lr.write_canonical_meta(key, meta)
            applied[key] = {"drawsWithCounts":changed, "fullyPublished":sum(set(lr.PRIZE_WINNER_KEYS_BY_TYPE[key]).issubset(row.get(lr.PRIZE_WINNER_COUNTS_FIELD) or {}) for row in current.values())}
    for key, before_hash in csv_hashes.items():
        after_hash = hashlib.sha256(lr.get_canonical_output_paths(key)["all"].read_bytes()).hexdigest()
        if before_hash != after_hash:
            raise RuntimeError(f"Canonical CSV changed concurrently: {key}; review source identity before continuing")
    report = {"finishedAt":lr.now_iso(), "applied":bool(args.apply), "types":applied,
              "csvSha256":csv_hashes,"verified":verified,"errors":errors}
    lr.write_json_file(work/"report.json", report)
    print(json.dumps({"types":applied,"errors":len(errors),"report":str(work/"report.json")},ensure_ascii=False),flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
