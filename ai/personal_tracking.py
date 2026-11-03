"""Private prospective ledgers and recoverable wallet reservations.

Account transactions are short. A receipt committed WITH the private portfolio
decides whether a reservation is charged or refunded after an interrupted job.
Only the authenticated Java bridge supplies an account's opaque tracking ID.
"""
from __future__ import annotations

import contextvars
import functools
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from ai import prediction_ledger as ledger
from ai import tracking_portfolio as portfolio
from ai.configs import data_paths as dp
from backend.file_guard import resource_lock

UNIT_VND = 10000
UNIT_PAYPAL = 10000
MAX_SAFE = 9007199254740991
_scope = contextvars.ContextVar('personal_tracking', default=None)


def schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS personal_tracking_accounts (
            id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS prediction_charges (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, game_type TEXT NOT NULL,
            target_draw_id TEXT NOT NULL, ticket_count INTEGER NOT NULL,
            paypal_cost INTEGER NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, settled_at TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS prediction_charges_pending
            ON prediction_charges(account_id,status);
    """)


def account_connection(path=None):
    connection = sqlite3.connect(str(path or ledger.DEFAULT_DB_PATH), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA busy_timeout=30000')
    return connection


def private_path(account_id, runtime=None):
    # UUID validation is mandatory; neither username nor a client path is used.
    if str(uuid.UUID(account_id)) != account_id:
        raise ValueError('Mã danh mục không hợp lệ.')
    return Path(runtime or dp.RUNTIME_DIR) / 'personal_tracking' / account_id / 'tracking.db'


def _account(connection, account_id, owner=None, enabled=True):
    row = connection.execute('SELECT p.username,u.enabled FROM personal_tracking_accounts p '
                             'JOIN users u ON u.username=p.username WHERE p.id=?', (account_id,)).fetchone()
    if row is None or (owner is not None and row['username'] != owner) or (enabled and not row['enabled']):
        raise ValueError('Tài khoản không còn quyền sử dụng danh mục này.')
    return row['username']


def _wallet(connection, owner):
    row = connection.execute('SELECT store_json FROM stores WHERE username=?', (owner,)).fetchone()
    return json.loads(row[0]) if row else {}


def _save_wallet(connection, owner, wallet):
    wallet['walletVersion'] = int(wallet.get('walletVersion', 0)) + 1
    connection.execute('INSERT OR REPLACE INTO stores(username,store_json) VALUES(?,?)',
                       (owner, ledger.canonical_json(wallet)))


def _audit(connection, owner, action, details):
    connection.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',
                       (str(uuid.uuid4()), owner, owner, action, ledger.canonical_json(details), ledger.now_iso()))


def quote(game, count):
    from ai import ml_pipeline
    from ai.prediction_effectiveness import ticket_limit
    if type(count) is not int or not 1 <= count <= ticket_limit(game):
        raise ValueError('Số vé nằm ngoài giới hạn.')
    if game == 'KENO':
        levels = {str(level): portfolio.effective_count(count, 80, level) for level in range(1, 11)}
        total = 4 * sum(levels.values())
    else:
        config = ml_pipeline.game_config(game)
        levels = {}
        total = 4 * portfolio.effective_count(count, config['universe_size'], config['draw_size'])
    return {'unitVnd': UNIT_VND, 'unitPayPal': UNIT_PAYPAL, 'totalTickets': total,
            'totalVnd': total * UNIT_VND, 'totalPayPal': total * UNIT_PAYPAL,
            'ticketCountsByLevel': levels}


class Scope:
    def __init__(self, account_id, owner, account_db=None, runtime=None):
        self.account_id, self.owner = account_id, owner
        self.account_db = Path(account_db or ledger.DEFAULT_DB_PATH)
        self.database = private_path(account_id, runtime)

    def prepare(self, allow_disabled=False):
        self.validate(allow_disabled)
        from ai import keno_effectiveness as ke
        with resource_lock(self.database.parent / 'schema'):
            with closing(ke._connect(self.database)) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS paid_cycle_receipts '
                                   '(charge_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL UNIQUE, ticket_count INTEGER NOT NULL)')

    def validate(self, allow_disabled=False):
        with closing(account_connection(self.account_db)) as connection:
            _account(connection, self.account_id, self.owner, enabled=not allow_disabled)

    def reserve(self, game, target, tickets):
        from ai.prediction_effectiveness import ticket_limit
        maximum = quote(game, ticket_limit(game))['totalTickets']
        if type(tickets) is not int or tickets < 1 or tickets > maximum:
            raise ValueError('Số vé tính phí không hợp lệ.')
        cost, event = tickets * UNIT_PAYPAL, str(uuid.uuid4())
        with closing(account_connection(self.account_db)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                owner = _account(connection, self.account_id, self.owner)
                wallet = _wallet(connection, owner)
                balance = wallet.get('paypalBalance', 0)
                if type(balance) is not int or not 0 <= balance <= MAX_SAFE:
                    raise ValueError('Số dư PayPal không hợp lệ.')
                if balance < cost:
                    raise ValueError(f'Không đủ PayPal: cần {cost:,} PayPal cho {tickets:,} vé.'.replace(',', '.'))
                wallet['paypalBalance'] = balance - cost
                _save_wallet(connection, owner, wallet)
                connection.execute('INSERT INTO prediction_charges VALUES(?,?,?,?,?,?,?,?,?)',
                                   (event, self.account_id, game, target, tickets, cost, 'reserved', ledger.now_iso(), ''))
                _audit(connection, owner, 'prediction_reserve', {'id': event, 'tickets': tickets, 'paypal': cost, 'game': game, 'draw': target})
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return event

    def reconcile(self):
        # Caller holds the per-account OS lock. No live generator can still
        # commit a receipt while this recovery decides to refund its reservation.
        with closing(account_connection(self.account_db)) as accounts, closing(sqlite3.connect(self.database)) as tracking:
            pending = accounts.execute("SELECT * FROM prediction_charges WHERE account_id=? AND status='reserved'",
                                       (self.account_id,)).fetchall()
            for row in pending:
                receipt = tracking.execute('SELECT ticket_count FROM paid_cycle_receipts WHERE charge_id=?', (row['id'],)).fetchone()
                if receipt and receipt[0] != row['ticket_count']:
                    raise ValueError('Biên nhận phí không khớp số vé đã khóa.')
                accounts.execute('BEGIN IMMEDIATE')
                try:
                    if accounts.execute('SELECT status FROM prediction_charges WHERE id=?', (row['id'],)).fetchone()[0] != 'reserved':
                        accounts.rollback()
                        continue
                    owner_row = accounts.execute('SELECT p.username FROM personal_tracking_accounts p JOIN users u '
                                                 'ON u.username=p.username WHERE p.id=?', (self.account_id,)).fetchone()
                    if owner_row is None:
                        accounts.execute("UPDATE prediction_charges SET status='owner_deleted',settled_at=? WHERE id=?",
                                         (ledger.now_iso(), row['id']))
                        accounts.commit()
                        continue
                    owner = owner_row[0]
                    status = 'charged' if receipt else 'refunded'
                    if not receipt:
                        wallet = _wallet(accounts, owner)
                        balance = int(wallet.get('paypalBalance', 0)) + row['paypal_cost']
                        if balance > MAX_SAFE:
                            raise ValueError('Chưa thể hoàn phí vì số dư vượt giới hạn.')
                        wallet['paypalBalance'] = balance
                        _save_wallet(accounts, owner, wallet)
                    accounts.execute('UPDATE prediction_charges SET status=?,settled_at=? WHERE id=?',
                                     (status, ledger.now_iso(), row['id']))
                    _audit(accounts, owner, 'prediction_' + status, {'id': row['id'], 'paypal': row['paypal_cost']})
                    accounts.commit()
                except BaseException:
                    accounts.rollback()
                    raise

    @contextmanager
    def job(self, timeout=15):
        with resource_lock(self.database.parent / 'billing_job', timeout=timeout):
            self.reconcile()
            token = _scope.set(self)
            try:
                yield
            finally:
                _scope.reset(token)
                self.reconcile()

    def details(self, game, count):
        with closing(account_connection(self.account_db)) as connection:
            owner = _account(connection, self.account_id, self.owner)
            wallet = _wallet(connection, owner)
            recent = [dict(row) for row in connection.execute(
                'SELECT id,game_type,target_draw_id,ticket_count,paypal_cost,status,created_at '
                'FROM prediction_charges WHERE account_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20', (self.account_id,))]
        return {**quote(game, count), 'owner': owner, 'balance': wallet.get('paypalBalance', 0),
                'walletVersion': wallet.get('walletVersion', 0), 'charges': recent}

    def settle_rewards(self, refresh_context=False):
        try:
            return self._settle_rewards(refresh_context)
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as error:
            # A deferred reward must not turn a successfully purchased portfolio
            # into an apparent failed purchase after its fee has been committed.
            return {'status':'pending', 'errors':[{'reason':str(error)}]}

    def _settle_rewards(self, refresh_context):
        from ai import prediction_rewards
        policy = dp.PROJECT_ROOT / 'config/prediction-rewards.json'
        if not policy.is_file() or json.loads(policy.read_text(encoding='utf-8')).get('enabled') is not True:
            return {'status':'disabled'}
        result = prediction_rewards.settle(self, apply=True)
        if refresh_context and any(row['game'] == 'KENO' and row['reason'].startswith('Chờ dữ liệu quỹ') for row in result['waiting']):
            from ai import keno_prize_context
            try:
                synced = keno_prize_context.refresh(self.database, limit=1)
                if synced.get('updated'):
                    retried = prediction_rewards.settle(self, apply=True)
                    retried['credited'] += result['credited']
                    retried['creditedPayPal'] += result['creditedPayPal']
                    retried['errors'] = result['errors'] + retried['errors']
                    result = retried
                result['prizeSync'] = synced
            except Exception as error:
                result['prizeSync'] = {'error':str(error)}
        return prediction_rewards.summary(result)


def reserve(game, target, tickets):
    scope = _scope.get()
    return scope.reserve(game, target, tickets) if scope else None


def receipt(connection, charge_id, cycle_id, tickets):
    if charge_id is not None:
        scope = _scope.get()
        with closing(account_connection(scope.account_db)) as accounts:
            _account(accounts, scope.account_id)
        connection.execute('INSERT INTO paid_cycle_receipts VALUES(?,?,?)', (charge_id, cycle_id, tickets))


def settle(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            scope = _scope.get()
            if scope is not None:
                scope.reconcile()
    return wrapped


def execute(args):
    from ai import prediction_effectiveness as pe
    scope = Scope(args.personal_id, args.owner)
    scope.prepare()
    args.db_path = scope.database
    if args.command in ('configure', 'cycle'):
        with scope.job():
            if args.command == 'cycle' and args.game in pe.GAMES:
                pe.sync_source(args.game, scope.database)
            result = pe.dispatch(args)
    else:
        result = pe.dispatch(args)
    if args.command in ('configure', 'cycle', 'score', 'tick'):
        result['rewards'] = scope.settle_rewards(refresh_context=True)
    if args.command in ('report', 'settings', 'configure', 'cycle'):
        settings = pe.settings(args.game, scope.database)['settings']
        valid_count = min(settings['ticketCount'], settings['maxTicketCount'])
        result['billing'] = scope.details(args.game, valid_count)
        if not settings.get('configurationValid', True):
            result['billing']['configurationValid'] = False
            result['billing']['configurationError'] = settings['configurationError']
    return result


def tick_all():
    from ai import prediction_effectiveness as pe, keno_effectiveness as ke
    with closing(account_connection()) as connection:
        rows = connection.execute('SELECT p.id,p.username,u.enabled FROM personal_tracking_accounts p '
                                  'JOIN users u ON u.username=p.username').fetchall()
    results, synced = [], False
    for row in rows:
        scope = Scope(row['id'], row['username'])
        try:
            scope.prepare(allow_disabled=True)
            with scope.job(timeout=.1):
                if not row['enabled']:
                    for game in pe.GAMES:
                        pe.score_cycles(game, scope.database)
                    ke.score_cycles(scope.database)
                    results.append({'accountId':row['id'], 'rewards':scope.settle_rewards(refresh_context=True)})
                    continue
                with closing(pe._connect(scope.database)) as connection:
                    enabled = connection.execute('SELECT 1 FROM effectiveness_settings WHERE enabled=1 LIMIT 1').fetchone()
                    pending = connection.execute("SELECT 1 FROM prediction_runs WHERE status='locked' LIMIT 1").fetchone()
                    keno_active = connection.execute("SELECT enabled FROM effectiveness_settings WHERE game_type='KENO'").fetchone()[0]
                    keno_pending = connection.execute("SELECT 1 FROM keno_effectiveness_cycles WHERE status='locked' LIMIT 1").fetchone()
                if not enabled and not pending:
                    results.append({'accountId':row['id'], 'rewards':scope.settle_rewards(refresh_context=True)})
                    continue
                # Canonical is shared, portfolios and charges are private.
                if not synced and (keno_active or keno_pending):
                    try:
                        ke._sync_source(scope.database)
                    except Exception as error:
                        results.append({'accountId': row['id'], 'sourceError': str(error)})
                    synced = True
                result = pe.tick(scope.database, sync_sources=True)
                try:
                    result['prizeSync'] = ke.prize_contexts.refresh(scope.database, limit=1)
                except Exception as error:
                    result['prizeSync'] = {'error': str(error)}
            # job() has reconciled newly committed fee receipts before payout.
            result['rewards'] = scope.settle_rewards(refresh_context=True)
            results.append({'accountId': row['id'], 'result': result})
        except Exception as error:
            results.append({'accountId': row['id'], 'error': str(error)})
    return {'ok': True, 'accounts': results}
