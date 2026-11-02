"""Only one purchased ticket class may exist for a locked cycle."""
import json
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from contextlib import closing
from unittest import mock

from ai import prediction_effectiveness as pe, tracking_bao as bao, prediction_ledger as ledger
from ai.prizes import classify_tickets, prize_counts, prize_statistics
from ai.effectiveness_xlsx import write_cycle_xlsx
from tests.test_prediction_effectiveness import PredictionEffectivenessTests
from tests.test_tracking_bao_recovery import payload


class SelectedTicketClassTests(PredictionEffectivenessTests):
    def test_normal_only_does_not_invoke_bao_generator(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db)
        with mock.patch.object(bao, 'build', side_effect=AssertionError('Bao not selected')), mock.patch.object(bao, 'expand', side_effect=AssertionError('Bao not selected')):
            pe.cycle(self.GAME, self.db)
        with closing(pe._connect(self.db)) as connection:
            runs = connection.execute('SELECT payload_json FROM prediction_runs').fetchall()
        self.assertEqual(len(runs), 4)
        for run in runs:
            saved = json.loads(run[0])
            self.assertEqual(saved['ticketClass'], 'normal')
            self.assertNotIn('bao', saved)
            self.assertEqual(len(saved['tickets']), 3)
        entry = pe.report(self.GAME, db_path=self.db)['cycles'][0]['methods']['web']
        self.assertEqual(entry['ticketClass'], 'normal')
        self.assertNotIn('baoParents', entry)
        with self.assertRaisesRegex(ValueError, 'đúng loại vé'):
            pe.ticket_page(self.GAME, entry['predictionId'], db_path=self.db, view='bao')

    def test_bao_only_stores_parents_and_never_locks_normal_ticket_array(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=11)
        with mock.patch.object(bao, 'expand', side_effect=AssertionError('Do not generate a normal-ticket array')):
            locked = pe.cycle(self.GAME, self.db)
        self.assertEqual(locked['ticketCount'], 66)  # Fee-equivalent combinations.
        with closing(pe._connect(self.db)) as connection:
            runs = connection.execute('SELECT payload_json,tickets_json FROM prediction_runs').fetchall()
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM effectiveness_ticket_chunks').fetchone()[0], 0)
        self.assertEqual(len(runs), 4)
        for run in runs:
            saved = json.loads(run[0])
            self.assertEqual(saved['ticketClass'], 'bao')
            self.assertEqual(saved['predictionMode'], 'bao')
            self.assertEqual(saved['tickets'], [])
            self.assertEqual(json.loads(run[1]), [])
            self.assertEqual(len(saved['bao']['parents']), 11)
        with mock.patch.object(pe, '_ticket_slice', side_effect=AssertionError('No ordinary-ticket pages in Bao report')):
            cycle = pe.report(self.GAME, db_path=self.db)['cycles'][0]
        entry = cycle['methods']['web']
        self.assertNotIn('tickets', entry)
        self.assertNotIn('ticketResults', entry)
        page = pe.ticket_page(self.GAME, entry['predictionId'], 2, self.db)
        self.assertEqual(page['ticketClass'], 'bao')
        self.assertEqual(len(page['baoParents']), 1)
        self.assertEqual(page['baoParents'][0]['parentIndex'], 11)
        self.assertNotIn('tickets', page)
        self.assertNotIn('firstTicketIndex', page['baoParents'][0])
        with self.assertRaisesRegex(ValueError, 'đúng loại vé'):
            pe.ticket_page(self.GAME, entry['predictionId'], db_path=self.db, view='tickets')
        pe.configure(self.GAME, False, 2, 'fixture', self.db, play_mode='normal')
        self.assertEqual(pe.cycle(self.GAME, self.db)['status'], 'already_locked')
        self.assertEqual(pe.ticket_page(self.GAME, entry['predictionId'], db_path=self.db)['ticketClass'], 'bao')

    def test_bao_score_and_excel_contain_only_selected_groups(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=11)
        locked = pe.cycle(self.GAME, self.db)
        self._actual()
        self.assertTrue(pe.score_cycles(self.GAME, self.db)['ok'])
        cycle = pe.report(self.GAME, db_path=self.db)['cycles'][0]
        self.assertEqual(cycle['status'], 'scored')
        exported = pe.export_cycle(self.GAME, locked['cycleId'], self.db)
        for method, entry in exported['methods'].items():
            self.assertNotIn('tickets', entry)
            self.assertEqual(entry['ticketClass'], 'bao')
            self.assertEqual(entry['ticketCount'], 11)
            self.assertEqual(entry['equivalentTicketCount'], 66)
            self.assertEqual(sum(entry['prizeCounts'].values()), 66)
            code = next((code for code in entry['prizeCounts'] if code not in ('NONE', 'UNKNOWN', 'PENDING')), None)
            if code:
                found = pe.ticket_page(self.GAME, entry['predictionId'], db_path=self.db, prize_code=code)
                self.assertIn('jumpBaoIndex', found)
                self.assertNotIn('jumpTicketIndex', found)
        file = self.root / 'bao.xlsx'
        write_cycle_xlsx(self.GAME, locked['cycleId'], file, self.db)
        with zipfile.ZipFile(file) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        rows = sheet.findall('s:sheetData/s:row', ns)
        self.assertEqual(len(rows), 12)
        header = ''.join(rows[0].itertext())
        self.assertIn('Bộ số Bao gốc', header)
        self.assertNotIn('Vé con', header)

    def test_parent_prize_multiplicities_match_exact_rules_all_games(self):
        for game, levels in [('LOTO_5_35', (4, 6, 15)), ('LOTO_6_45', (5, 7, 18)), ('LOTO_6_55', (5, 7, 18))]:
            n, t, _ = bao.GAMES[game]
            actual = {'main': list(range(1, t + 1)), 'special': 2 if t == 5 else n if game == 'LOTO_6_55' else None}
            for level in levels:
                with self.subTest(game=game, level=level):
                    built = bao.build(payload(game), game, level, 1, 324632 if t == 5 else 1000000)
                    self.assertEqual(built['tickets'], [])
                    parent = built['bao']['parents'][0]
                    labels = classify_tickets(game, list(bao.iter_equivalents(game, [parent])), actual)
                    summary = bao.parent_prizes(game, parent, actual)
                    self.assertEqual(summary['prizeCounts'], prize_counts(labels))
                    self.assertEqual(summary['prizeStatistics'], prize_statistics(labels))
                    if game == 'LOTO_6_55':
                        for special in (None, 1):
                            missing_or_invalid = {**actual, 'special': special}
                            expected = classify_tickets(game, list(bao.iter_equivalents(game, [parent])), missing_or_invalid)
                            self.assertEqual(bao.parent_prizes(game, parent, missing_or_invalid)['prizeCounts'], prize_counts(expected))

    def test_default_maximum_bao_stores_no_other_ticket_class_all_three_games(self):
        for game, level, maximum in [('LOTO_5_35', 6, 324632), ('LOTO_6_45', 7, 1000000), ('LOTO_6_55', 7, 1000000)]:
            with self.subTest(game=game):
                count = bao.limits(game, maximum)[str(level)]
                with mock.patch.object(bao, 'expand', side_effect=AssertionError('Do not expand normal selections')):
                    built = bao.build(payload(game), game, level, count, maximum)
                self.assertEqual(len(built['bao']['parents']), count)
                self.assertEqual(built['tickets'], [])
                self.assertEqual(built['ticketClass'], 'bao')
                self.assertTrue(all(len(parent['main']) == level for parent in built['bao']['parents']))

    def test_legacy_bao_remains_immutable_and_does_not_expose_other_class(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=2)
        lock = ledger.lock_prediction
        def legacy_lock(payload, **kwargs):
            historical = bao.scoring_payload(payload)
            historical.pop('ticketStorage')
            return lock(historical, **kwargs)
        with mock.patch.object(ledger, 'lock_prediction', side_effect=legacy_lock):
            pe.cycle(self.GAME, self.db)
        entry = pe.report(self.GAME, db_path=self.db)['cycles'][0]['methods']['web']
        with closing(pe._connect(self.db)) as connection:
            checksum = connection.execute('SELECT payload_checksum FROM prediction_runs WHERE prediction_id=?', (entry['predictionId'],)).fetchone()[0]
        page = pe.ticket_page(self.GAME, entry['predictionId'], db_path=self.db)
        self.assertEqual(len(page['baoParents']), 2)
        self.assertNotIn('tickets', page)
        with closing(pe._connect(self.db)) as connection:
            self.assertEqual(connection.execute('SELECT payload_checksum FROM prediction_runs WHERE prediction_id=?', (entry['predictionId'],)).fetchone()[0], checksum)
