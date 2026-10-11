"""Large tracking budgets, saturated combination spaces and exact scoring parity."""
import itertools
import json
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from ai import prediction_effectiveness as pe, prediction_ledger as ledger, tracking_portfolio as portfolio


class TrackingPortfolioTests(unittest.TestCase):
    def test_unique_full_small_spaces_and_large_weighted_portfolios(self):
        for level, expected in ((1, 80), (2, 3160), (3, 10000), (10, 10000)):
            weights = {n: .1 + n / 100 for n in range(1, 81)}
            count = portfolio.effective_count(10000, 80, level)
            mains = portfolio.unique_mains(weights, level, count, 42)
            self.assertEqual(len(mains), expected)
            self.assertEqual(len(set(mains)), expected)
            self.assertTrue(all(len(main) == level and len(set(main)) == level and min(main) >= 1 and max(main) <= 80 for main in mains))
            self.assertEqual(mains, portfolio.unique_mains(weights, level, count, 42))
            if level <= 2:
                self.assertEqual(set(mains), set(itertools.combinations(range(1, 81), level)))

    def test_uniform_unranking_covers_space_and_preserves_prefix(self):
        space = list(itertools.combinations(range(1, 13), 5))
        self.assertEqual([portfolio._unrank(index, 12, 5) for index in range(len(space))], space)
        prefix = [[1, 2, 3, 4, 5], [2, 3, 4, 5, 6]]
        mains = portfolio.unique_mains({n: 1 for n in range(1, 36)}, 5, 10000, 19, prefix)
        self.assertEqual(mains[:2], [tuple(main) for main in prefix])
        self.assertEqual(len(mains), len(set(mains)))
        for invalid in (0, 10001, 3.5, True):
            with self.assertRaises(ValueError):
                portfolio.effective_count(invalid, 80, 1)

    def test_bit_slice_baseline_matches_original_1024_simulations_exactly(self):
        for size, draw, pick, count in ((35, 5, 5, 10), (80, 20, 1, 80), (80, 20, 10, 137), (55, 6, 6, 59)):
            generator = random.Random(29)
            tickets = tuple(tuple(sorted(generator.sample(range(1, size + 1), pick))) for _ in range(count))
            rng = random.Random(20261004)
            total = 0
            for _ in range(1024):
                actual = set(rng.sample(range(1, size + 1), draw))
                total += max(len(set(ticket) & actual) for ticket in tickets)
            self.assertEqual(ledger._portfolio_random_best(tickets, size, draw), total / 1024)

    def test_settings_schema_migration_preserves_all_columns_and_audits(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'private.db'
            with closing(pe._connect(db)) as connection:
                schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='effectiveness_settings'").fetchone()[0]
                connection.execute('DROP TABLE effectiveness_settings')
                connection.execute(schema.replace('BETWEEN 1 AND 10000', 'BETWEEN 1 AND 10'))
                connection.execute("INSERT INTO effectiveness_settings VALUES('KENO',1,5,'before','owner','tick','error','123')")
                connection.execute("INSERT INTO effectiveness_config_audit VALUES('old','KENO','owner','before','{}')")
                before = tuple(connection.execute("SELECT * FROM effectiveness_settings WHERE game_type='KENO'").fetchone())
            with closing(pe._connect(db)) as connection:
                self.assertEqual(tuple(connection.execute("SELECT * FROM effectiveness_settings WHERE game_type='KENO'").fetchone()), before)
                self.assertEqual(connection.execute('SELECT event_id FROM effectiveness_config_audit').fetchone()[0], 'old')
            result = pe.configure('KENO', True, 10000, 'admin_fixture', db)
            self.assertEqual(result['settings']['ticketCount'], 10000)
            pe.configure('KENO', False, 10000, 'admin_fixture', db)
            with closing(pe._connect(db)) as connection:
                self.assertEqual(connection.execute('PRAGMA quick_check').fetchone()[0], 'ok')
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE effectiveness_settings SET ticket_count=10001 WHERE game_type='KENO'")


if __name__ == '__main__':
    unittest.main()
