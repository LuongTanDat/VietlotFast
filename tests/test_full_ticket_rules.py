"""Ticket identity, grouped expansion and recoverable payment invariants."""
from copy import deepcopy
from unittest import TestCase, mock

from ai import tracking_bao as bao, prediction_effectiveness as pe
from tests import test_tracking_bao_recovery as fixtures
from tests import test_personal_prediction_billing as payments


class FullTicketRulesTests(TestCase):
    def validate(self, game, tickets):
        source = fixtures.payload(game)
        source.update(tickets=tickets, latestKy='40', nextKy='41')
        pe._validate(source, game, len(tickets), {'cutoff': '40', 'target': '41'})

    def test_lotto_same_main_different_special_allowed(self):
        self.validate('LOTO_5_35', [{'main': [1, 2, 3, 4, 5], 'special': 2},
                                   {'main': [5, 4, 3, 2, 1], 'special': 3}])

    def test_lotto_exact_duplicate_rejected_despite_order(self):
        with self.assertRaisesRegex(ValueError, 'trùng hoàn toàn'):
            self.validate('LOTO_5_35', [{'main': [1, 2, 3, 4, 5], 'special': 2},
                                       {'main': [5, 4, 3, 2, 1], 'special': 2}])

    def test_power_seventh_forecast_does_not_make_a_new_ticket(self):
        with self.assertRaisesRegex(ValueError, 'trùng hoàn toàn'):
            self.validate('LOTO_6_55', [{'main': [1, 2, 3, 4, 5, 6], 'special': 7},
                                       {'main': [6, 5, 4, 3, 2, 1], 'special': 8}])

    def test_mega_same_six_numbers_rejected_and_partial_overlap_allowed(self):
        with self.assertRaisesRegex(ValueError, 'trùng hoàn toàn'):
            self.validate('LOTO_6_45', [{'main': [1, 2, 3, 4, 5, 6], 'special': None}] * 2)
        self.validate('LOTO_6_45', [{'main': [1, 2, 3, 4, 5, 6], 'special': None},
                                   {'main': [1, 2, 3, 4, 5, 7], 'special': None}])

    def test_lotto_parents_overlap_main_but_children_remain_full_unique(self):
        expanded = bao.expand(fixtures.payload('LOTO_5_35'), 'LOTO_5_35', 6, 24, 324632)
        mains = [tuple(row['main']) for row in expanded['tickets']]
        self.assertLess(len(set(mains)), len(mains))
        self.assertEqual(len({bao.ticket_key('LOTO_5_35', row) for row in expanded['tickets']}), 144)
        self.assertEqual({p['special'] for p in expanded['bao']['parents']}, set(range(1, 13)))
        self.assertEqual(expanded['bao']['parents'][0]['special'], 1)


class FullTicketBillingTests(payments.PersonalPredictionBillingTests):
    def configure_bao(self):
        with self.alice.job():
            return pe.configure(self.fixture.GAME, True, 3, 'alice', self.alice.database,
                                play_mode='bao', bao_level=6, bao_count=2)['settings']

    def test_full_unique_bao_is_charged_once_and_each_child_is_paid(self):
        settings = self.configure_bao()
        with self.alice.job():
            first = pe.cycle(self.fixture.GAME, self.alice.database, configuration_hash=settings['configurationHash'])
        self.assertEqual(first['ticketCount'], 12)
        self.assertEqual(self.wallet()['paypalBalance'], 1520000)
        self.assertEqual(self.cycle(self.alice)['status'], 'already_locked')
        self.assertEqual(self.wallet()['paypalBalance'], 1520000)
        self.assertEqual(len(self.charges()), 1)
        self.assertEqual(self.charges()[0]['ticket_count'], 48)
        self.assertEqual(self.charges()[0]['status'], 'charged')

    def test_duplicate_failure_refunds_then_clean_retry_charges_once(self):
        settings = self.configure_bao()
        real = bao.build
        def duplicate(*args, **kwargs):
            result = real(*args, **kwargs)
            result['bao']['parents'][1]['main'] = deepcopy(result['bao']['parents'][0]['main'])
            result['bao']['parents'][1]['special'] = result['bao']['parents'][0]['special']
            return result
        with mock.patch.object(bao, 'build', side_effect=duplicate):
            with self.alice.job():
                with self.assertRaisesRegex(ValueError, 'trùng hoàn toàn'):
                    pe.cycle(self.fixture.GAME, self.alice.database, configuration_hash=settings['configurationHash'])
        self.assertEqual(self.wallet()['paypalBalance'], 2000000)
        self.assertEqual(self.charges()[0]['status'], 'refunded')
        with self.alice.job():
            pe.cycle(self.fixture.GAME, self.alice.database, configuration_hash=settings['configurationHash'])
        self.assertEqual(self.wallet()['paypalBalance'], 1520000)
        self.assertCountEqual([row['status'] for row in self.charges()], ['refunded', 'charged'])
