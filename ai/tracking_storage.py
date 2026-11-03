"""Separate high-volume tracking writes from account and wallet transactions."""
from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from ai import prediction_ledger as ledger
from ai.configs import data_paths as dp

CONFIG_NAME = 'tracking-storage.json'
DATABASE_NAME = 'tracking_ledger.db'


def database_path(explicit=None):
    if explicit is not None:
        return Path(explicit)
    config = dp.RUNTIME_DIR / CONFIG_NAME
    if not config.exists():
        return Path(ledger.DEFAULT_DB_PATH)
    value = json.loads(config.read_text(encoding='utf-8-sig'))
    if value != {'version': 1, 'mode': 'dedicated'}:
        raise ValueError('Cấu hình lưu dữ liệu theo dõi không hợp lệ.')
    database = dp.RUNTIME_DIR / DATABASE_NAME
    if not database.is_file():
        raise ValueError('Không tìm thấy DB theo dõi đã chuyển; chưa tạo lịch sử trống thay thế.')
    return database


def migrate_tracking(source, destination):
    """Copy only system tracking tables in one snapshot; never copy credentials."""
    from ai import prediction_effectiveness as pe, keno_effectiveness as ke
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or not source.is_file():
        raise ValueError('Nguồn và đích chuyển dữ liệu theo dõi không hợp lệ.')
    if shutil.disk_usage(destination.parent).free < 20 * 1024**3 + source.stat().st_size * 2:
        raise ValueError('Chưa đủ dung lượng dự phòng để chuyển dữ liệu theo dõi.')
    with closing(ke._connect(destination)) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS tracking_storage_migration (name TEXT PRIMARY KEY, details_json TEXT NOT NULL)')
        existing = connection.execute("SELECT details_json FROM tracking_storage_migration WHERE name='legacy_shared_ledger'").fetchone()
        if existing:
            return {'ok': True, 'status': 'already_migrated', **json.loads(existing[0])}
        if connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0]:
            raise ValueError('DB đích đã có dự đoán; không tự ghi đè.')
    # URI mode makes the attached legacy database read-only as well.
    with closing(sqlite3.connect(destination.as_uri(), uri=True, isolation_level=None, timeout=30)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('ATTACH DATABASE ? AS legacy', (source.as_uri() + '?mode=ro',))
        tables = {row[0] for row in connection.execute("SELECT name FROM legacy.sqlite_master WHERE type='table'")}
        connection.execute('BEGIN')
        try:
            if 'effectiveness_settings' not in tables:
                raise ValueError('DB nguồn chưa có cấu hình theo dõi.')
            connection.execute('INSERT INTO main.prediction_runs SELECT * FROM legacy.prediction_runs WHERE username=?', (pe.ACTOR,))
            connection.execute('INSERT INTO main.prediction_scores SELECT * FROM legacy.prediction_scores WHERE prediction_id IN (SELECT prediction_id FROM main.prediction_runs)')
            counts = {}
            for table in ['effectiveness_settings', 'effectiveness_cycles', 'effectiveness_predictions',
                          'effectiveness_config_audit', 'keno_effectiveness_cycles', 'keno_effectiveness_predictions',
                          'keno_effectiveness_metrics', 'keno_effectiveness_source_state',
                          'effectiveness_ticket_index', 'effectiveness_ticket_chunks']:
                if table not in tables:
                    continue
                if table == 'effectiveness_cycles':
                    columns = 'cycle_id,game_type,target_draw_id,cutoff_draw_id,created_at,deadline,data_hash,source_version_json,config_json'
                    for row in connection.execute(f'SELECT {columns} FROM legacy.effectiveness_cycles').fetchall():
                        connection.execute(f'INSERT INTO main.effectiveness_cycles({columns},selection_key) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                           (*row, pe.cycle_selection_key(json.loads(row[-1]))))
                    counts[table] = connection.execute(f'SELECT COUNT(*) FROM main.{table}').fetchone()[0]
                    continue
                verb = 'INSERT OR REPLACE' if table == 'effectiveness_settings' else 'INSERT'
                scope = ' WHERE prediction_id IN (SELECT prediction_id FROM main.prediction_runs)' if table in ('effectiveness_ticket_index','effectiveness_ticket_chunks') else ''
                connection.execute(f'{verb} INTO main.{table} SELECT * FROM legacy.{table}{scope}')
                counts[table] = connection.execute(f'SELECT COUNT(*) FROM main.{table}').fetchone()[0]
            if connection.execute('PRAGMA main.foreign_key_check').fetchone():
                raise ValueError('Dữ liệu theo dõi cũ có liên kết không hợp lệ; hủy chuyển DB.')
            counts['prediction_runs'] = connection.execute('SELECT COUNT(*) FROM main.prediction_runs').fetchone()[0]
            counts['prediction_scores'] = connection.execute('SELECT COUNT(*) FROM main.prediction_scores').fetchone()[0]
            details = {'source': str(source), 'destination': str(destination), 'counts': counts}
            connection.execute("INSERT INTO main.tracking_storage_migration VALUES('legacy_shared_ledger',?)", (json.dumps(details),))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {'ok': True, 'status': 'migrated', **details}
