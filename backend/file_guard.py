"""Cross-process CSV writer lock with optimistic version checks."""
import os
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path


def version(path):
    try:
        stat = Path(path).stat()
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


class VersionedRows(dict):
    def __init__(self, rows, path, source_version):
        super().__init__(rows)
        self.source_path = Path(path).resolve()
        self.source_version = source_version


def retain_version(source, rows):
    return VersionedRows(rows, source.source_path, source.source_version) if isinstance(source, VersionedRows) else rows


@contextmanager
def resource_lock(path, timeout=15):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + '.write.lock')
    with lock_path.open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        started = time.monotonic()
        acquired = False
        while not acquired:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() - started >= timeout:
                    raise TimeoutError(f'CSV writer is busy: {path.name}')
                time.sleep(.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def versioned_loader(function):
    @wraps(function)
    def wrapped(csv_path, *args, **kwargs):
        # Atomic replacement lets readers remain read-only and avoid write locks.
        initial = version(csv_path)
        result = function(csv_path, *args, **kwargs)
        if version(csv_path) != initial:
            raise RuntimeError('CSV changed while reading; reload before updating')
        if isinstance(result, tuple):
            return VersionedRows(result[0], csv_path, initial), result[1]
        return VersionedRows(result, csv_path, initial)
    return wrapped


def guarded_writer(function):
    @wraps(function)
    def wrapped(csv_path, rows_by_ky, *args, **kwargs):
        path = Path(csv_path).resolve()
        with resource_lock(path):
            if isinstance(rows_by_ky, VersionedRows) and rows_by_ky.source_path == path:
                if version(path) != rows_by_ky.source_version:
                    raise RuntimeError('CSV changed since load; refusing stale overwrite, reload and retry')
            result = function(csv_path, rows_by_ky, *args, **kwargs)
            if isinstance(rows_by_ky, VersionedRows) and rows_by_ky.source_path == path:
                rows_by_ky.source_version = version(path)
            return result
    return wrapped
