"""Original groups remain separate from their immutable scored child tickets."""
import json
import sqlite3
from contextlib import closing
from unittest import mock

from ai import prediction_effectiveness as pe, tracking_bao as bao
from tests.test_prediction_effectiveness import PredictionEffectivenessTests
from tests.test_tracking_bao_recovery import payload


class BaoDisplayTests(PredictionEffectivenessTests):
    def test_original_groups_pagination_frozen_config_and_child_links(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=11)
        locked = pe.cycle(self.GAME, self.db)
        entry = pe.report(self.GAME, db_path=self.db)['cycles'][0]['methods']['web']
        prediction = entry['predictionId']
        self.assertTrue(entry['baoAvailable'])
        self.assertNotIn('baoParents', entry)  # No eager large-payload reads in the report.
        pe.configure(self.GAME, False, 3, 'fixture', self.db, play_mode='normal')
        before = self._counts()
        page1 = pe.ticket_page(self.GAME, prediction, db_path=self.db, view='bao')
        page2 = pe.ticket_page(self.GAME, prediction, 2, self.db, view='bao')
        self.assertEqual(page1['baoPagination']['total'], 11)
        self.assertEqual(len(page1['baoParents']), 10)
        self.assertEqual(page2['baoPagination']['offset'], 10)
        self.assertEqual(len(page2['baoParents']), 1)  # SQLite single-path extraction.
        self.assertEqual(page2['baoParents'][0]['parentIndex'], 11)
        self.assertEqual(pe.ticket_page(self.GAME, prediction, 999, self.db, view='bao'), page2)
        with closing(pe._connect(self.db)) as connection:
            original = json.loads(connection.execute('SELECT payload_json FROM prediction_runs WHERE prediction_id=?', (prediction,)).fetchone()[0])
        for parent in page1['baoParents'] + page2['baoParents']:
            frozen = original['bao']['parents'][parent['parentIndex'] - 1]
            self.assertEqual({key: parent[key] for key in frozen}, frozen)
            self.assertNotIn('firstTicketIndex', parent)
            self.assertNotIn('ticketPage', parent)
        with self.assertRaisesRegex(ValueError, 'đúng loại vé'):
            pe.ticket_page(self.GAME, prediction, db_path=self.db, view='tickets')
        self.assertEqual(self._counts(), before)
        self._actual()
        pe.score_cycles(self.GAME, self.db)
        scored = pe.ticket_page(self.GAME, prediction, 2, self.db, view='bao')
        self.assertEqual(scored['baoParents'][0]['main'], page2['baoParents'][0]['main'])
        export = pe.export_cycle(self.GAME, locked['cycleId'], self.db)
        entry = export['methods']['web']
        code = next((code for code in entry['prizeCounts'] if code not in ('NONE', 'UNKNOWN', 'PENDING')), None)
        if code:
            found = pe.ticket_page(self.GAME, prediction, 1, self.db, code)
            self.assertEqual(found['view'], 'bao')
            self.assertTrue(any(row['parentIndex'] == found['jumpBaoIndex'] for row in found['baoParents']))

    def test_all_games_and_low_high_bao_levels_read_original_parent(self):
        for game, levels in [('LOTO_5_35', (4, 6, 15)), ('LOTO_6_45', (5, 7, 18)), ('LOTO_6_55', (5, 7, 18))]:
            for level in levels:
                with self.subTest(game=game, level=level), closing(sqlite3.connect(':memory:')) as connection:
                    source = bao.expand(payload(game), game, level, 1, 324632 if game == self.GAME else 1000000)
                    connection.execute('CREATE TABLE prediction_runs(prediction_id TEXT,payload_json TEXT)')
                    connection.execute('INSERT INTO prediction_runs VALUES(?,?)', ('fixture', json.dumps(source)))
                    parents, pagination = pe._bao_slice(connection, 'fixture', source['bao'])
                    self.assertEqual(parents[0]['main'], source['bao']['parents'][0]['main'])
                    self.assertEqual(len(parents[0]['main']), level)
                    self.assertEqual(parents[0]['special'], source['bao']['parents'][0]['special'])
                    self.assertEqual(pagination['total'], 1)
                    self.assertEqual(pe._bao_slice(connection, 'fixture', {'playMode': 'normal'}), ([], {}))

    def test_view_validation_and_wrong_game_do_not_expose_groups(self):
        pe.configure(self.GAME, True, 3, 'fixture', self.db, play_mode='bao', bao_level=6, bao_count=1)
        pe.cycle(self.GAME, self.db)
        prediction = pe.report(self.GAME, db_path=self.db)['cycles'][0]['methods']['web']['predictionId']
        for game, view, prize in [('LOTO_6_45', 'bao', None), ('KENO', 'bao', None), (self.GAME, 'other', None), (self.GAME, 'bao', 'FIRST')]:
            with self.subTest(game=game, view=view, prize=prize), self.assertRaises(ValueError):
                pe.ticket_page(game, prediction, db_path=self.db, view=view, prize_code=prize)
