"""Internal account cards. No external bank connection or payment execution."""
from __future__ import annotations

import json
from ai.configs import data_paths as dp
from ai import prediction_ledger as ledger

MAX_SAFE = 9007199254740991


def policy():
    path = dp.PROJECT_ROOT / 'config/prediction-rewards.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    destination = value.get('destination', 'wallet')
    currency = value.get('cardCurrency', 'PayPal') if destination == 'card' else 'PayPal'
    if destination not in ('wallet','card') or currency not in ('PayPal','VNĐ'):
        raise ValueError('Cấu hình nơi nhận thưởng không hợp lệ.')
    return {'destination':destination,'currency':currency}


def schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS account_cards (
            account_id TEXT PRIMARY KEY, currency TEXT NOT NULL CHECK(currency IN ('PayPal','VNĐ')),
            balance INTEGER NOT NULL CHECK(balance>=0), version INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS card_transactions (
            event_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, currency TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('transfer','topup','withdraw','reward')),
            amount INTEGER NOT NULL, balance_after INTEGER NOT NULL,
            reference TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL,
            source_key TEXT NOT NULL UNIQUE);
        CREATE INDEX IF NOT EXISTS card_transactions_owner ON card_transactions(account_id,created_at);
        CREATE TRIGGER IF NOT EXISTS card_transactions_no_update BEFORE UPDATE ON card_transactions
            BEGIN SELECT RAISE(ABORT,'Immutable card transaction'); END;
        CREATE TRIGGER IF NOT EXISTS card_transactions_no_delete BEFORE DELETE ON card_transactions
            BEGIN SELECT RAISE(ABORT,'Immutable card transaction'); END;
        CREATE TABLE IF NOT EXISTS prediction_payout_routes (
            charge_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, cycle_id TEXT NOT NULL,
            destination TEXT NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
            card_account_id TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reward_card_migrations (
            charge_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, card_account_id TEXT NOT NULL,
            wallet_debit INTEGER NOT NULL, card_credit INTEGER NOT NULL, currency TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS payout_routes_no_update BEFORE UPDATE ON prediction_payout_routes
            BEGIN SELECT RAISE(ABORT,'Immutable payout route'); END;
        CREATE TRIGGER IF NOT EXISTS payout_routes_no_delete BEFORE DELETE ON prediction_payout_routes
            BEGIN SELECT RAISE(ABORT,'Immutable payout route'); END;
        CREATE TRIGGER IF NOT EXISTS card_migrations_no_update BEFORE UPDATE ON reward_card_migrations
            BEGIN SELECT RAISE(ABORT,'Immutable reward transfer'); END;
        CREATE TRIGGER IF NOT EXISTS card_migrations_no_delete BEFORE DELETE ON reward_card_migrations
            BEGIN SELECT RAISE(ABORT,'Immutable reward transfer'); END;
    ''')


def public_id(db, owner):
    row = db.execute("SELECT account_id FROM account_identities WHERE username=? AND deleted_at=''", (owner,)).fetchone()
    if row is None:
        raise ValueError('Không tìm thấy ID tài khoản của chủ thẻ.')
    if len(row[0])!=12 or row[0][0]=='0' or any(c not in '0123456789' for c in row[0]):
        raise ValueError('ID chủ thẻ không hợp lệ.')
    return row[0]


def credit(db, account_id, currency, amount, event, kind, reference, details):
    """Caller holds the account DB transaction; event and source are idempotent."""
    if not db.in_transaction or currency not in ('PayPal','VNĐ') or type(amount) is not int or not 0 <= amount <= MAX_SAFE:
        raise ValueError('Giao dịch thẻ không hợp lệ.')
    if db.execute('SELECT 1 FROM card_transactions WHERE source_key=?', (event,)).fetchone():
        return False
    stamp = ledger.now_iso()
    db.execute('INSERT OR IGNORE INTO account_cards VALUES(?,?,0,0,?,?)', (account_id,currency,stamp,stamp))
    row = db.execute('SELECT currency,balance FROM account_cards WHERE account_id=?', (account_id,)).fetchone()
    if row[0] != currency or type(row[1]) is not int or not 0 <= row[1] + amount <= MAX_SAFE:
        raise ValueError('Đơn vị thẻ không khớp hoặc số dư thẻ vượt giới hạn.')
    balance = row[1] + amount
    db.execute('UPDATE account_cards SET balance=?,version=version+1,updated_at=? WHERE account_id=?', (balance,stamp,account_id))
    db.execute('INSERT INTO card_transactions VALUES(?,?,?,?,?,?,?,?,?,?)',
               (event,account_id,currency,kind,amount,balance,reference,ledger.canonical_json(details),stamp,event))
    return True


def _wallet_rewards(db, scope):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'prediction_payouts' not in tables:
        return []
    migrated = {r[0] for r in db.execute('SELECT charge_id FROM reward_card_migrations')} if 'reward_card_migrations' in tables else set()
    on_card = {r[0] for r in db.execute("SELECT charge_id FROM prediction_payout_routes WHERE destination='card'")} if 'prediction_payout_routes' in tables else set()
    return [dict(row) for row in db.execute('SELECT account_id,cycle_id,charge_id,game_type,target_draw_id,paypal_credit,reward_vnd,event_id FROM prediction_payouts WHERE account_id=? AND paypal_credit>0 ORDER BY created_at,cycle_id',(scope.account_id,))
            if row['charge_id'] not in migrated and row['charge_id'] not in on_card]


def move_wallet_rewards(scope, apply=False):
    """Move already-paid rewards once, preserving wallet + card PayPal total."""
    from contextlib import closing
    import hashlib
    from ai import personal_tracking as billing, account_statistics as stats
    if not apply:
        with closing(stats.readonly(scope.account_db)) as db:
            owner=billing._account(db,scope.account_id,scope.owner,enabled=False)
            card_id=public_id(db,owner);rows=_wallet_rewards(db,scope)
            amount=sum(row['paypal_credit'] for row in rows)
            wallet=billing._wallet(db,owner)
            return {'count':len(rows),'amount':amount,'currency':'PayPal','cardAccountId':card_id,
                    'walletBefore':wallet.get('paypalBalance',0),'canMove':type(wallet.get('paypalBalance',0)) is int and wallet.get('paypalBalance',0)>=amount}
    with closing(billing.account_connection(scope.account_db)) as db:
        schema(db);db.execute('BEGIN IMMEDIATE')
        try:
            owner=billing._account(db,scope.account_id,enabled=False);card_id=public_id(db,owner)
            rows=_wallet_rewards(db,scope);amount=sum(row['paypal_credit'] for row in rows)
            if not rows:
                db.rollback();return {'count':0,'amount':0,'currency':'PayPal'}
            wallet=billing._wallet(db,owner);balance=wallet.get('paypalBalance',0)
            if type(balance) is not int or not 0<=amount<=balance<=MAX_SAFE:
                raise ValueError('Ví không còn đủ số tiền thưởng cần chuyển; chưa chuyển khoản nào.')
            old_card=db.execute('SELECT currency,balance FROM account_cards WHERE account_id=?',(card_id,)).fetchone()
            card_before=old_card[1] if old_card else 0
            if (old_card and old_card[0]!='PayPal') or card_before+amount>MAX_SAFE:
                raise ValueError('Đơn vị/số dư thẻ không phù hợp; chưa chuyển tiền.')
            stamp=ledger.now_iso()
            batch='reward_card_transfer:'+hashlib.sha256('|'.join(r['charge_id'] for r in rows).encode()).hexdigest()
            for row in rows:
                audit=db.execute('SELECT action,details_json FROM account_audit WHERE event_id=?',(row['event_id'],)).fetchone()
                if audit is None or audit[0]!='prediction_reward' or json.loads(audit[1]).get('paypal')!=row['paypal_credit']:
                    raise ValueError('Khoản thưởng cũ chưa có chứng từ cộng ví khớp; chưa chuyển tiền.')
                linked=db.execute('SELECT target_account_id FROM account_activity_links WHERE event_id=?',(row['event_id'],)).fetchone()
                if linked is None or linked[0]!=card_id:
                    raise ValueError('Chứng từ thưởng cũ không thuộc ID chủ thẻ; chưa chuyển tiền.')
                label={'LOTO_5_35':'Loto 5/35','LOTO_6_45':'Mega 6/45','LOTO_6_55':'Power 6/55'}.get(row['game_type'],row['game_type'])
                event='reward_card_migration:'+row['charge_id']
                if not credit(db,card_id,'PayPal',row['paypal_credit'],event,'transfer',row['charge_id'],
                              {'label':'Chuyển thưởng từ ví','description':label+' · Kỳ #'+row['target_draw_id'],'cycleId':row['cycle_id'],'originalEventId':row['event_id']}):
                    raise ValueError('Thưởng đã có trên thẻ nhưng thiếu chứng từ chuyển.')
                db.execute('INSERT INTO reward_card_migrations VALUES(?,?,?,?,?,?,?)',(row['charge_id'],scope.account_id,card_id,row['paypal_credit'],row['paypal_credit'],'PayPal',stamp))
            wallet['paypalBalance']=balance-amount;billing._save_wallet(db,owner,wallet)
            db.execute('INSERT INTO account_audit VALUES(?,?,?,?,?,?)',
                       (batch,owner,owner,'card_reward_migration',ledger.canonical_json({'id':batch,'paypal':amount,'count':len(rows),'cardAccountId':card_id,'balanceBefore':balance,'balanceAfter':balance-amount,'cardBefore':card_before,'cardAfter':card_before+amount}),stamp))
            db.commit()
            return {'count':len(rows),'amount':amount,'currency':'PayPal','walletBefore':balance,'walletAfter':balance-amount,'cardBefore':card_before,'cardAfter':card_before+amount}
        except BaseException:
            db.rollback();raise
