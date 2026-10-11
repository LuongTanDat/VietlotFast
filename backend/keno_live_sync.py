"""Bounded latest-result polling for prospective Keno tracking, without backfill/training."""
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from backend import live_results as live

LOCAL_TZ = timezone(timedelta(hours=7))
POLL_TIMEOUT = (4, 12)


def _at(day, clock):
    parsed = live.parse_csv_date(day)
    if parsed is None:
        raise ValueError("Ngày kết quả Keno từ nguồn không hợp lệ.")
    try:
        hour, minute = map(int, str(clock).split(":"))
        at = datetime(parsed.year, parsed.month, parsed.day, hour, minute, tzinfo=LOCAL_TZ)
    except (TypeError, ValueError):
        raise ValueError("Giờ kết quả Keno từ nguồn không hợp lệ.")
    slot = hour * 60 + minute
    if not live.KENO_FIRST_DRAW_MINUTES <= slot <= live.KENO_LAST_DRAW_MINUTES or (slot - live.KENO_FIRST_DRAW_MINUTES) % 8:
        raise ValueError("Giờ Keno từ nguồn không khớp lịch 8 phút.")
    return at


def _next(at):
    return ((at + timedelta(days=1)).replace(hour=6, minute=8)
            if at.hour * 60 + at.minute == live.KENO_LAST_DRAW_MINUTES else at + timedelta(minutes=8))


def _checked(result, now):
    identity = str(result.get("ky", "")).lstrip("#")
    numbers = result.get("main", [])
    if (result.get("key") != "KENO" or not identity.isdigit() or int(identity) <= 0
            or len(numbers) != 20 or any(type(n) is not int or not 1 <= n <= 80 for n in numbers)
            or len(set(numbers)) != 20):
        raise ValueError("Bộ số/mã kỳ Keno từ nguồn không hợp lệ.")
    if _at(result.get("date"), result.get("time")) > now:
        raise ValueError("Nguồn Keno chứa kết quả có giờ quay trong tương lai.")
    return {**result, "ky": str(int(identity))}


def _page(session, now, target=None):
    at = datetime.fromisoformat(target["deadline"]) if target else now
    response = live.request_with_retry(
        session, "post", live.KENO_URL, retry_count=0, timeout=POLL_TIMEOUT,
        data={"date": live.format_minhchinh_date(at.date()),
              "ky": target["target_draw_id"] if target else "0", "number": "", "page": "1"},
    )
    return live.parse_keno_rows(BeautifulSoup(response.text, "html.parser"), source_url=live.KENO_URL)


def refresh(now=None, pending=()):
    """Append verified results, rebase concurrent writes, and preserve all existing rows."""
    now = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    path = live.dp.get_canonical_csv_write_path("KENO")
    if not path.is_file():
        raise ValueError("Chưa có CSV Keno canonical; cần cập nhật dữ liệu lần đầu.")
    # One current page contains fifteen draws. Targeted requests only recover
    # actually locked, overdue draws, never crawl every day or infer results.
    with live.create_session() as session:
        try:
            results = _page(session, now)
            if not results:
                raise ValueError("Trang Keno chưa trả kết quả.")
        except Exception:
            response = live.request_with_retry(session, "get", live.KENO_LIVE_URL,
                                               retry_count=0, timeout=POLL_TIMEOUT)
            results = live.parse_keno_rows(BeautifulSoup(response.text, "html.parser"), source_url=live.KENO_LIVE_URL)
        if not results:
            raise ValueError("Nguồn Keno chưa trả kết quả hợp lệ; sẽ thử lại ở lượt tự cập nhật sau.")
        fetched = {r["ky"]: r for r in (_checked(raw, now) for raw in results)}
        known = live.load_keno_csv_rows(path, normalize_schedule=False)
        missing = [p for p in pending if datetime.fromisoformat(p["deadline"]) <= now
                   and p["target_draw_id"] not in known and p["target_draw_id"] not in fetched]
        for target in missing[:3]:
            for raw in _page(session, now, target):
                result = _checked(raw, now)
                if result["ky"] == target["target_draw_id"]:
                    fetched[result["ky"]] = result

    for attempt in range(3):
        rows = live.load_keno_csv_rows(path, normalize_schedule=False)
        added = 0
        for identity, result in fetched.items():
            row = live.keno_result_to_csv_row(result)
            previous = rows.get(identity)
            if previous is not None:
                old_numbers = sorted(int(n) for n in previous["Numbers"].split(","))
                if (old_numbers != sorted(result["main"])
                        or _at(previous["Ngay"], previous["Time"]) != _at(row["Ngay"], row["Time"])):
                    raise ValueError(f"Nguồn và CSV Keno mâu thuẫn ở kỳ {identity}; giữ nguyên dữ liệu, cần kiểm tra.")
                continue
            rows[identity] = row
            added += 1
        # Validate new adjacent pairs while preserving known historical anomalies.
        ordered = sorted(rows, key=int)
        for before, after in zip(ordered, ordered[1:]):
            if int(after) != int(before) + 1 or (before not in fetched and after not in fetched):
                continue
            first, second = rows[before], rows[after]
            if _at(second["Ngay"], second["Time"]) != _next(_at(first["Ngay"], first["Time"])):
                raise ValueError("Mã kỳ Keno từ nguồn không khớp thứ tự ngày/giờ canonical.")
        latest = rows[ordered[-1]]
        if added:
            try:
                live.write_keno_csv_rows(path, rows, normalize_schedule=False)
            except RuntimeError as exc:
                if "CSV changed" not in str(exc) or attempt == 2:
                    raise
                continue
            meta = live.read_canonical_meta("KENO")
            meta["lastSyncAt"] = now.isoformat(timespec="seconds")
            live.write_canonical_meta("KENO", meta)
        return {"status": "updated" if added else "up_to_date", "newRows": added,
                "latestKy": latest["Ky"], "latestDate": latest["Ngay"], "latestTime": latest["Time"],
                "sourceUrl": live.KENO_URL}
