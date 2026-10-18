"""Manual isolated capacity trial; never changes live tracking settings.

Runs the real numeric web/baseline, ledger and scoring paths against a fresh
private database. Only this child process lifts the ticket cap and overrides
the future deadline. The actual result used for scoring is synthetic.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint():
    paths = [p for base in (ROOT / "data/canonical", ROOT / "ai/models")
             for p in base.rglob("*") if p.is_file() and p.suffix in (".csv", ".json")]
    paths += [ROOT / "ai/tracking_portfolio.py", ROOT / "ai/prediction_effectiveness.py",
              ROOT / "ai/prediction_ledger.py", ROOT / "ai/keno_effectiveness.py", ROOT / "ai/tracking_capacity.py", ROOT / "ai/tracking_storage.py"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def worker(args):
    from ai import prediction_effectiveness as pe, prediction_ledger as ledger, tracking_portfolio as portfolio
    from ai.configs import data_paths as dp
    import psutil

    work = Path(args.output).resolve()
    db, canonical = work / "private_ledger.db", work / "canonical.csv"
    if db.exists() or canonical.exists():
        raise RuntimeError("Trial directory must be fresh; existing trial data is preserved.")
    work.mkdir(parents=True, exist_ok=True)
    before = fingerprint()
    save(work / "source_before.json", before)
    shutil.copy2(dp.get_canonical_csv_read_path(args.game), canonical)
    canonical_hash = hashlib.sha256(canonical.read_bytes()).hexdigest()
    ledger.DEFAULT_DB_PATH = db
    portfolio.MAX_TICKETS = args.count  # Child only; source/production remain unchanged.
    with closing(pe._connect(db)) as connection:
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
        schema = re.sub(r"BETWEEN 1 AND \d+", f"BETWEEN 1 AND {args.count}", schema)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ALTER TABLE effectiveness_settings RENAME TO capacity_trial_settings_old")
        connection.execute(schema)
        connection.execute("INSERT INTO effectiveness_settings SELECT * FROM capacity_trial_settings_old")
        connection.execute("DROP TABLE capacity_trial_settings_old")
        connection.commit()

    timings = {}
    started = time.perf_counter()

    def stage(name, action):
        print(json.dumps({"stage": name, "state": "running"}), flush=True)
        begin = time.perf_counter()
        value = action()
        timings[name] = round(time.perf_counter() - begin, 3)
        print(json.dumps({"stage": name, "state": "done", "seconds": timings[name]}), flush=True)
        return value

    from ai import keno_effectiveness as ke
    is_keno = args.game == 'KENO'
    original_snapshot = ke._snapshot if is_keno else pe._snapshot
    real_snapshot = lambda game: original_snapshot() if is_keno else original_snapshot(game)
    deadline = datetime(2035, 1, 6, 21 if args.game == 'LOTO_5_35' else 18, tzinfo=pe.LOCAL_TZ)

    def snapshot(game):
        return {**real_snapshot(game), "deadline": deadline}

    with patch.object(dp, "get_canonical_csv_read_path", return_value=canonical), \
            patch.object(pe, "_now", return_value=deadline - timedelta(hours=1)), \
            patch.object(ke if is_keno else pe, "_snapshot", side_effect=(lambda: snapshot(args.game)) if is_keno else snapshot):
        snapshot_data = real_snapshot(args.game)
        count = args.count if is_keno else min(args.count, math.comb(pe.ml_pipeline.game_config(args.game)["universe_size"],
                                          pe.ml_pipeline.game_config(args.game)["draw_size"]))
        pe.configure(args.game, True, args.count, "isolated_capacity_trial", db)
        locked = stage("create_and_lock_all_methods", lambda: pe.cycle(args.game, db))
        assert locked["status"] == "locked" and locked["ticketCount"] == (args.count if is_keno else count)
        pending = stage("pending_report", lambda: pe.report(args.game, db_path=db))
        assert pending["counts"]["locked"] == 1
        for entry in pending["cycles"][0]["methods"].values():
            assert entry["ticketCount"] == count and len(entry["tickets"]) <= portfolio.TICKET_PAGE_SIZE
        del pending
        gc.collect()
        actual = {"ky": locked["targetDrawId"], "date": deadline.strftime("%d/%m/%Y"),
                  "time": deadline.strftime('%H:%M'), "main": list(range(1, 21)) if is_keno else list(range(1, 6 if args.game == 'LOTO_5_35' else 7)),
                  "special": 7 if args.game == "LOTO_6_55" else 2 if args.game == 'LOTO_5_35' else None}
        with patch.object(pe.ml_pipeline, "load_actual_draws", return_value={**snapshot_data["actual"], actual["ky"]: actual}), \
                patch.object(pe, "_now", return_value=deadline + timedelta(hours=1)):
            scored = stage("score_all_methods_synthetic_actual", lambda: pe.score_cycles(args.game, db))
            assert scored["ok"] and scored["scored"] == [actual["ky"]], scored
        report = stage("scored_report", lambda: pe.report(args.game, db_path=db))
        assert report["counts"]["scored"] == 1
        totals = {}
        for method, entry in report["cycles"][0]["methods"].items():
            assert entry["ticketCount"] == count
            if not is_keno:
                assert sum(entry["hitHistogram"].values()) == count
            assert sum(entry["prizeCounts"].values()) == count
            totals[method] = {"ticketCount": count, "prizeCounts": entry["prizeCounts"]}
            last = stage(f"last_page_{method}", lambda: pe.ticket_page(
                args.game, entry["predictionId"], math.ceil(count / portfolio.TICKET_PAGE_SIZE), db))
            assert last["ticketResults"][-1]["ticketIndex"] == count
            assert len(last["tickets"]) <= portfolio.TICKET_PAGE_SIZE
        with closing(pe._connect(db)) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            query = ("SELECT pr.tickets_json,kp.level FROM prediction_runs pr JOIN keno_effectiveness_predictions kp ON kp.prediction_id=pr.prediction_id"
                     if is_keno else "SELECT tickets_json,NULL FROM prediction_runs")
            for row in connection.execute(query):
                tickets = json.loads(row[0])
                expected = min(args.count, math.comb(80, row[1])) if is_keno else count
                assert len(tickets) == expected and len({tuple(t["main"]) for t in tickets}) == expected
                del tickets
            if is_keno:
                for row in connection.execute("SELECT level,ticket_count,summary_json FROM keno_effectiveness_metrics"):
                    summary = json.loads(row[2])
                    expected = min(args.count, math.comb(80, row[0]))
                    assert row[1] == expected and sum(summary['hitHistogram'].values()) == expected
                    assert sum(summary['prizeCounts'].values()) == expected
            stored_scores = connection.execute("SELECT COUNT(*) FROM prediction_scores").fetchone()[0]
            assert stored_scores == (40 if is_keno else 4)
        duplicate = stage("repeat_cycle_no_reroll", lambda: pe.cycle(args.game, db))
        assert duplicate["status"] == "already_locked" and duplicate["cycleId"] == locked["cycleId"]

    after = fingerprint()
    changes = {key: {"before": value, "after": after.get(key)} for key, value in before.items() if after.get(key) != value}
    # The live Keno collector may legitimately update unrelated canonical data.
    # The game under trial, models and source must still stay fixed.
    relevant_changes = {key: value for key, value in changes.items()
                        if not key.replace('\\', '/').startswith('data/canonical/')}
    save(work / "source_changes.json", changes)
    assert not relevant_changes, "Trial game, model or source changed during the trial."
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == canonical_hash
    memory = psutil.Process().memory_info()
    result = {"ok": True, "game": args.game, "requestedTicketsPerMethod": args.count,
              "actualTicketsPerMethod": count, "totalTickets": locked.get('totalTickets', count * 4),
              "ticketCountsByLevel": locked.get('ticketCountsByLevel'),
              "realWebPipeline": True, "syntheticScoringResult": True,
              "productionSettingsChanged": False, "trialGameModelsSourceUnchanged": not relevant_changes,
              "otherLiveCanonicalChanges": list(changes),
              "seconds": round(time.perf_counter() - started, 3), "timings": timings,
              "workerPeakRssMiB": round(getattr(memory, "peak_wset", memory.rss) / 2**20, 1),
              "databaseMiB": round(db.stat().st_size / 2**20, 1), "methods": totals}
    save(work / "result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--game", choices=("LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO"), default="LOTO_6_55")
    parser.add_argument("--output", required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.count <= 1_000_000:
        parser.error("Manual trial supports 1 to 1,000,000 tickets per method.")
    output = Path(args.output).resolve()
    runtime = (ROOT / "runtime").resolve()
    if not output.is_relative_to(runtime) or output == runtime:
        parser.error("Output must be a fresh subdirectory inside this workspace's runtime directory.")
    if args.worker:
        worker(args)
        return
    import psutil
    if output.exists():
        parser.error("Output already exists; use a fresh directory.")
    output.mkdir(parents=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--count", str(args.count),
               "--game", args.game, "--output", str(output)]
    initial = psutil.virtual_memory()
    started = time.monotonic()
    peak_rss, lowest_available, samples, stopped = 0, initial.available, 0, None
    with (output / "worker.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        child = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                tree = [child] + child.children(recursive=True)
                rss = 0
                for member in tree:
                    try:
                        rss += member.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                available = psutil.virtual_memory().available
                peak_rss = max(peak_rss, rss)
                lowest_available = min(lowest_available, available)
                samples += 1
                if available < 3 * 2**30:
                    stopped = "System available RAM fell below 3 GiB."
                elif rss > 8 * 2**30:
                    stopped = "Trial process exceeded 8 GiB RSS."
                elif time.monotonic() - started > 900:
                    stopped = "Trial exceeded 15 minutes."
                if stopped:
                    for member in reversed(child.children(recursive=True)):
                        try:
                            member.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    process.wait(timeout=15)
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(.25)
        process.wait()
    monitor = {"exitCode": process.returncode, "stoppedReason": stopped, "samples": samples,
               "systemTotalRamGiB": round(initial.total / 2**30, 2),
               "initialAvailableGiB": round(initial.available / 2**30, 2),
               "minimumAvailableGiB": round(lowest_available / 2**30, 2),
               "sampledTreePeakRssMiB": round(peak_rss / 2**20, 1),
               "wallSeconds": round(time.monotonic() - started, 3)}
    save(output / "monitor.json", monitor)
    print(json.dumps(monitor), flush=True)
    sys.exit(0 if process.returncode == 0 and not stopped else 1)


if __name__ == "__main__":
    main()
