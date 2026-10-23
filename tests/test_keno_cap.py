import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from ai import prediction_effectiveness as pe, keno_effectiveness as ke


class KenoCapTests(unittest.TestCase):
    def test_only_keno_has_lower_cap_and_invalid_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'private.db'
            pe.configure('KENO', True, 324632, 'fixture', db)
            for game in pe.GAMES:
                self.assertEqual(pe.configure(game, False, 1000000, 'fixture', db)['settings']['maxTicketCount'], 1000000)
            with closing(pe._connect(db)) as connection:
                before = connection.execute('SELECT * FROM effectiveness_settings').fetchall()
                audits = connection.execute('SELECT COUNT(*) FROM effectiveness_config_audit').fetchone()[0]
            for value in (324633, 500000, 1000000, True, 0, -1):
                with self.assertRaises(ValueError):
                    pe.configure('KENO', True, value, 'fixture', db)
            with closing(pe._connect(db)) as connection:
                self.assertEqual([tuple(row) for row in connection.execute('SELECT * FROM effectiveness_settings')], [tuple(row) for row in before])
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM effectiveness_config_audit').fetchone()[0], audits)
            self.assertEqual(pe.settings('KENO', db)['settings']['ticketCount'], 324632)
            self.assertEqual(pe.settings('KENO', db)['settings']['maxTicketCount'], 324632)

    def test_legacy_high_setting_is_clamped_before_expensive_allocation(self):
        from tests.test_keno_effectiveness import KenoEffectivenessTests
        fixture = KenoEffectivenessTests()
        fixture.setUp()
        try:
            with closing(ke._connect(fixture.db)) as connection:
                connection.execute("UPDATE effectiveness_settings SET ticket_count=1000000 WHERE game_type='KENO'")
            with mock.patch.object(ke.portfolio, 'effective_count', side_effect=RuntimeError('stop before allocation')) as allocate:
                with self.assertRaisesRegex(RuntimeError, 'stop before allocation'):
                    ke.cycle(fixture.db)
                allocate.assert_called_once_with(324632, 80, 1)
            with closing(ke._connect(fixture.db)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT ticket_count FROM effectiveness_settings WHERE game_type='KENO'").fetchone()[0], 1000000)
        finally:
            fixture.doCleanups()
