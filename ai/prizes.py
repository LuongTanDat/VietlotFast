"""Pure classification of standard tickets against recorded draw results.

Rules checked 2026-10-05: Vietlott's Lotto 5/35 Decision 95, Article 8,
Mega 6/45 rules, and Power 6/55 rules. Only the highest matching tier is
returned. No prize pool is treated as an individual payout.

Primary sources:
https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535?id=00762&nocatche=1
https://www.scribd.com/document/905941897/Thele535
(mirror of Vietlott Decision 95/QD-VIETLOTT, 18 June 2025, Article 8)
https://media.vietlott.vn/vi/04.2019/system/archivedate/the-le-mega-6.45.pdf
https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/655?id=01382&nocatche=1
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

RULE_VERSION = "official_prize_rules_2026_10_05"
PRIZE_SCOPE = "official_standard_ticket"
GAMES = {"LOTO_5_35": (35, 5), "LOTO_6_45": (45, 6), "LOTO_6_55": (55, 6)}
PRIZE_LABELS = {
    "LOTTO_JACKPOT": "Độc Đắc", "MEGA_JACKPOT": "Jackpot",
    "POWER_JACKPOT_1": "Jackpot 1", "POWER_JACKPOT_2": "Jackpot 2",
    "FIRST": "Giải Nhất", "SECOND": "Giải Nhì", "THIRD": "Giải Ba",
    "FOURTH": "Giải Tư", "FIFTH": "Giải Năm", "CONSOLATION": "Giải Khuyến Khích",
    "NONE": "Không trúng giải", "UNKNOWN": "Chưa xác định giải", "PENDING": "Chờ kết quả",
    "UNSUPPORTED": "Chưa hỗ trợ loại vé", "INVALID": "Bộ số không hợp lệ",
}


def _result(code: str, main_hits: int | None = None, special_matched: bool | None = None,
            reason: str = "") -> dict[str, Any]:
    status = {"NONE": "lost", "UNKNOWN": "unknown", "PENDING": "pending",
              "UNSUPPORTED": "unsupported", "INVALID": "invalid"}.get(code, "won")
    return {"mainHits": main_hits, "specialMatched": special_matched,
            "prizeCode": code, "prizeLabel": PRIZE_LABELS[code], "status": status,
            "isWinning": True if status == "won" else False if status == "lost" else None,
            "ruleVersion": RULE_VERSION, "reason": reason}


def _valid_numbers(values: Any, size: int, universe: int) -> bool:
    return isinstance(values, (list, tuple)) and len(values) == size and all(
        type(number) is int and 1 <= number <= universe for number in values) and len(set(values)) == size


def classify_ticket(game: str, ticket: Any, actual: dict | None) -> dict[str, Any]:
    """Classify one standard ticket without I/O or inferred missing special balls.

    Power's actual seventh ball must occur in the ticket's SIX purchased numbers
    for Jackpot 2. ``ticket.special`` is an auxiliary forecast and is ignored.
    Missing result balls remain unknown; they are never converted to a loss.
    """
    game = str(game or "").strip().upper()
    if game not in GAMES:
        return _result("UNSUPPORTED", reason="Chỉ hỗ trợ vé chuẩn Loto 5/35, Mega 6/45 và Power 6/55.")
    universe, size = GAMES[game]
    main = ticket.get("main") if isinstance(ticket, dict) else ticket
    if isinstance(main, (list, tuple)) and len(main) > size:
        return _result("UNSUPPORTED", reason="Vé bao cần tách thành vé chuẩn trước khi phân loại giải.")
    if not _valid_numbers(main, size, universe):
        return _result("INVALID", reason="Số chính phải đủ cỡ vé, khác nhau và nằm trong miền của game.")
    selected_special = ticket.get("special") if isinstance(ticket, dict) else None
    if game == "LOTO_5_35" and (type(selected_special) is not int or not 1 <= selected_special <= 12):
        return _result("INVALID", reason="Vé Loto 5/35 cần một số đặc biệt từ 1 đến 12.")
    if game == "LOTO_6_45" and selected_special is not None:
        return _result("INVALID", reason="Vé Mega 6/45 không có số đặc biệt.")
    if actual is None:
        return _result("PENDING", reason="Chưa có kết quả thực tế đã ghi nhận.")
    if not isinstance(actual, dict):
        return _result("UNKNOWN", reason="Kết quả thực tế không hợp lệ.")
    actual_main = actual.get("main", actual.get("main_numbers"))
    if not actual_main:
        return _result("UNKNOWN", reason="Thiếu số chính của kết quả đã ghi nhận.")
    if not _valid_numbers(actual_main, size, universe):
        return _result("UNKNOWN", reason="Số chính kết quả thiếu, lặp hoặc nằm ngoài miền.")
    hits = len(set(main) & set(actual_main))
    special = actual.get("special")
    matched = None
    if game == "LOTO_5_35":
        if special is None:
            return _result("UNKNOWN", hits, reason="Điểm cũ thiếu ĐB thực tế; không suy diễn từ dữ liệu hiện tại.")
        if type(special) is not int or not 1 <= special <= 12:
            return _result("UNKNOWN", hits, reason="ĐB thực tế Loto 5/35 không hợp lệ.")
        matched = selected_special == special
        if hits == 5:
            code = "LOTTO_JACKPOT" if matched else "FIRST"
        elif hits == 4:
            code = "SECOND" if matched else "THIRD"
        elif hits == 3:
            code = "FOURTH" if matched else "FIFTH"
        else:
            code = "CONSOLATION" if matched else "NONE"
    elif game == "LOTO_6_45":
        if special is not None:
            return _result("UNKNOWN", hits, reason="Kết quả Mega không có số đặc biệt.")
        code = {6: "MEGA_JACKPOT", 5: "FIRST", 4: "SECOND", 3: "THIRD"}.get(hits, "NONE")
    else:
        if special is not None and (type(special) is not int or not 1 <= special <= 55 or special in actual_main):
            return _result("UNKNOWN", hits, reason="Số thứ bảy thực tế Power không hợp lệ.")
        matched = special in main if special is not None else None
        if hits == 6:
            code = "POWER_JACKPOT_1"
        elif hits == 5:
            if special is None:
                return _result("UNKNOWN", hits, reason="Thiếu số thứ bảy thực tế; chưa phân biệt Giải Nhất và Jackpot 2.")
            code = "POWER_JACKPOT_2" if matched else "FIRST"
        else:
            code = {4: "SECOND", 3: "THIRD"}.get(hits, "NONE")
    return _result(code, hits, matched)


def classify_tickets(game: str, tickets: Iterable[Any], actual: dict | None) -> list[dict[str, Any]]:
    return [{"ticketIndex": index + 1, **classify_ticket(game, ticket, actual)}
            for index, ticket in enumerate(tickets)]


def prize_counts(results: Iterable[dict]) -> dict[str, int]:
    return dict(sorted(Counter(result["prizeCode"] for result in results).items()))


def prize_statistics(results: Iterable[dict]) -> dict[str, Any]:
    results = list(results)
    classified = [result for result in results if result["status"] in ("won", "lost")]
    winning = sum(result["status"] == "won" for result in classified)
    return {"ticketCount": len(results), "classifiedTicketCount": len(classified), "winningTicketCount": winning,
            "winningTicketRate": winning / len(classified) if classified else None,
            "unknownTicketCount": sum(result["status"] == "unknown" for result in results),
            "pendingTicketCount": sum(result["status"] == "pending" for result in results),
            "invalidTicketCount": sum(result["status"] in ("invalid", "unsupported") for result in results),
            "scope": PRIZE_SCOPE, "ruleVersion": RULE_VERSION,
            "note": "Chỉ phân loại hạng giải của bộ số dự đoán; không xác nhận vé đã mua hoặc giá trị lĩnh thưởng."}
