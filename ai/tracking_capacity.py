"""Conservative free-space guard for large immutable tracking portfolios."""
from pathlib import Path
import shutil

RESERVE_BYTES = 20 * 1024 ** 3


def ensure_storage(database, counts_by_pick):
    # Ticket JSON, immutable payload, page chunks, WAL, and staging may coexist.
    # Include conservative per-ticket JSON overhead; do not delete old forecasts.
    estimated = sum(count * (40 + 3 * pick) * 7 for pick, count in counts_by_pick)
    required = RESERVE_BYTES + max(512 * 1024 ** 2, estimated)
    available = shutil.disk_usage(Path(database).resolve().parent).free
    if available < required:
        raise ValueError(f"Tạm dừng tạo vé: ổ đĩa còn {available / 1024 ** 3:.1f} GB; "
                         f"cần ít nhất {required / 1024 ** 3:.1f} GB, gồm 20 GB dự phòng. "
                         "Giảm số vé hoặc giải phóng dung lượng; lịch sử đã lưu được giữ nguyên.")
    return {"availableBytes": available, "requiredBytes": required, "reserveBytes": RESERVE_BYTES}
