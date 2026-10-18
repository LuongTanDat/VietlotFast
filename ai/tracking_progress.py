"""Advisory progress sidecars; never write prediction/account tables."""
from __future__ import annotations

import contextvars
import functools
import inspect
import json
import os
import threading
import time
import uuid
from pathlib import Path

from ai.tracking_storage import database_path

_current = contextvars.ContextVar('tracking_progress', default=None)
# Warm estimates from the isolated capacity measurements on this machine.
_rates = {'LOTO_5_35': (21.58 / 1298528, 35.536 / 1298528),
          'LOTO_6_45': (85.739 / 4000000, 117.694 / 4000000),
          'LOTO_6_55': (126.168 / 4000000, 128.533 / 4000000),
          'KENO': (275.349 / 28341600, 367.416 / 28341600)}


class Session:
    def __init__(self, game, db_path):
        self.game = game
        self.path = database_path(db_path).parent / f'effectiveness_progress_{game.lower()}.json'
        self.job = str(uuid.uuid4())
        self.data = None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None

    def start(self, phase, total=1, tickets=0):
        with self.lock:
            self.started = time.monotonic()
            estimate = 10.0 if phase == 'updating' else 3 + tickets * _rates[self.game][phase == 'scoring']
            self.estimate = max(3.0, estimate)
            self.data = {'version': 1, 'type': self.game, 'jobId': self.job, 'pid': os.getpid(),
                         'phase': phase, 'startedAtMs': int(time.time() * 1000),
                         'completedUnits': 0, 'totalUnits': max(1, int(total)), 'error': ''}
            self.write(claim=True)
            if self.thread is None:
                self.thread = threading.Thread(target=self.heartbeat, daemon=True)
                self.thread.start()

    def advance(self, units):
        with self.lock:
            if self.data is None:
                return
            self.data['completedUnits'] = min(self.data['totalUnits'], self.data['completedUnits'] + int(units))
            self.write()

    def write(self, claim=False):
        """Best effort; a progress/disk error cannot alter a scoring transaction."""
        temporary = self.path.with_name(self.path.name + '.' + self.job + '.tmp')
        try:
            if not claim and self.path.exists() and json.loads(self.path.read_text(encoding='utf-8')).get('jobId') != self.job:
                return
            elapsed = max(0, time.monotonic() - self.started)
            fraction = self.data['completedUnits'] / self.data['totalUnits']
            estimated = max(self.estimate, elapsed / fraction) if fraction > 0 else self.estimate
            self.data.update(updatedAtMs=int(time.time() * 1000), elapsedSeconds=round(elapsed, 2),
                             etaSeconds=round(max(0, estimated - elapsed), 1))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.path)
        except (OSError, ValueError):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def heartbeat(self):
        while not self.stop.wait(2):
            with self.lock:
                if self.data is not None:
                    self.write()

    def finish(self, error=''):
        if error and self.data is None:
            self.start('updating')
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
        with self.lock:
            if self.data is not None:
                self.data.update(phase='idle', error=str(error)[:600])
                self.write()


def track(function):
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs).arguments
        game = str(arguments.get('game', 'KENO')).upper()
        if game not in _rates:
            return function(*args, **kwargs)
        session = Session(game, arguments.get('db_path'))
        token = _current.set(session)
        error = ''
        try:
            result = function(*args, **kwargs)
            if isinstance(result, dict) and (result.get('ok') is False or result.get('error')):
                error = result.get('error') or '; '.join(str(row.get('error', '')) for row in result.get('errors', []))
            return result
        except BaseException as failure:
            error = str(failure) or 'Tiến trình bị gián đoạn.'
            raise
        finally:
            session.finish(error)
            _current.reset(token)
    return wrapped


def start(phase, total=1, tickets=0):
    session = _current.get()
    if session is not None:
        session.start(phase, total, tickets)


def advance(units):
    session = _current.get()
    if session is not None:
        session.advance(units)
