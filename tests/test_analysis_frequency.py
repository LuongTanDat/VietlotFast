"""Canonical occurrence counts, full domains and independent denominators."""
import csv
import hashlib
import io
import tempfile
import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from ai.analysis import analysis as an
from tests.test_analysis import SAMPLE_LOTO_535


def frequency_draw_fixture(count=120, type_key='LOTO_5_35'):
    power = type_key == 'LOTO_6_55'
    rows = []
    for index in range(count):
        numbers = [1 + (index + offset) % (54 if power else 35) for offset in range(6 if power else 5)]
        rows.append({'Kỳ': str(index + 1), 'Ngày': (date(2026, 1, 1) + timedelta(days=index if power else index // 2)).strftime('%d/%m/%Y'),
                     'Giờ': '18:00' if power else ('13:00' if index % 2 == 0 else '21:00'),
                     'Bộ Số': ','.join(map(str, numbers)), 'ĐB': str(55 if power else 1 + index % 12)})
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(reversed(rows))
    return stream.getvalue()


class AnalysisFrequencyTests(unittest.TestCase):
    @staticmethod
    def counts(items):
        return [{key: item[key] for key in ('number', 'count')} for item in items]

    def payload(self, text=SAMPLE_LOTO_535, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'draws.csv'
            path.write_text(text, encoding='utf-8')
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = an.build_analysis_payload(kwargs.pop('type_key', 'LOTO_5_35'),
                period=kwargs.pop('period', 'all'), mode='frequency', csv_path=path, **kwargs)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            return result

    def test_full_domains_sorted_and_main_special_never_mixed(self):
        result = self.payload(limit=1)
        self.assertTrue(result['ok'], result)
        main, special = result['data']['main'], result['data']['special']
        self.assertEqual((len(main['items']), len(special['items'])), (35, 12))
        self.assertEqual((main['totalOccurrences'], special['totalOccurrences']), (25, 5))
        self.assertEqual(self.counts(main['items'][:4]), [{'number': n, 'count': 4} for n in ['01', '02', '03', '05']])
        self.assertEqual(self.counts(special['items'][:1]), [{'number': '01', 'count': 3}])
        self.assertEqual(self.counts(main['items'][-1:]), [{'number': '35', 'count': 0}])
        self.assertEqual(self.counts(special['items'][-1:]), [{'number': '12', 'count': 0}])
        for group in [main, special]:
            self.assertEqual(sum(row['count'] for row in group['items']), group['totalOccurrences'])

    def test_custom_range_filters_both_groups_together(self):
        result = self.payload(period='custom', from_date='2026-01-02', to_date='2026-01-03')
        self.assertEqual(result['totalDraws'], 2)
        self.assertEqual(result['data']['main']['totalOccurrences'], 10)
        self.assertEqual(result['data']['special']['totalOccurrences'], 2)
        self.assertEqual(self.counts(result['data']['special']['items'][:2]),
                         [{'number': '01', 'count': 1}, {'number': '03', 'count': 1}])

    def test_missing_special_uses_observed_total_instead_of_draw_count(self):
        rows = list(csv.DictReader(io.StringIO(SAMPLE_LOTO_535)))
        rows[0]['ĐB'] = ''
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        result = self.payload(stream.getvalue())
        self.assertEqual(result['totalDraws'], 5)
        self.assertEqual(result['data']['main']['totalOccurrences'], 25)
        self.assertEqual(result['data']['special']['totalOccurrences'], 4)

    def test_no_special_numbers_is_explicitly_unsupported(self):
        result = self.payload(type_key='LOTO_6_45')
        self.assertEqual(len(result['data']['main']['items']), 45)
        self.assertEqual(result['data']['special'], {'supported': False, 'totalOccurrences': 0, 'items': []})

    def test_all_six_games_keep_their_full_number_domains(self):
        for type_key, size in [('LOTO_5_35', 35), ('LOTO_6_45', 45), ('LOTO_6_55', 55),
                               ('KENO', 80), ('MAX_3D', 1000), ('MAX_3D_PRO', 1000)]:
            with self.subTest(type=type_key):
                data, _ = an.build_frequency(type_key, [{'numbers': ['001', '007'] if size == 1000 else ['01', '02'], 'special': ''}])
                self.assertEqual(len(data['main']['items']), size)
                self.assertEqual(data['main']['totalOccurrences'], 2)
                self.assertEqual(data['special']['totalOccurrences'], 0)
                if size == 1000:
                    self.assertIn({'number': '000', 'count': 0}, self.counts(data['main']['items']))
                    self.assertIn({'number': '007', 'count': 1}, self.counts(data['main']['items']))

    def test_delays_count_nonappearance_draws_and_only_completed_internal_gaps(self):
        result = self.payload()
        main = {row['number']: row for row in result['data']['main']['items']}
        special = {row['number']: row for row in result['data']['special']['items']}
        for number, delay, average, lower in [('01', 0, .3333, False), ('04', 0, 1, False),
                                              ('06', 1, None, False), ('07', 2, 0, False), ('35', 5, None, True)]:
            self.assertEqual((main[number]['currentDelay'], main[number]['averageDelay'], main[number]['delayLowerBound']),
                             (delay, average, lower))
        self.assertEqual((special['01']['currentDelay'], special['01']['averageDelay']), (0, 1))
        self.assertEqual((special['03']['currentDelay'], special['03']['averageDelay']), (3, None))

    def test_delays_use_selected_window_without_boundary_or_prior_history_guesses(self):
        result = self.payload(draw_count=2)
        main = {row['number']: row for row in result['data']['main']['items']}
        self.assertEqual((main['04']['currentDelay'], main['04']['averageDelay']), (0, 0))
        self.assertEqual((main['06']['currentDelay'], main['06']['averageDelay']), (1, None))
        self.assertEqual((main['07']['currentDelay'], main['07']['averageDelay'], main['07']['delayLowerBound']), (2, None, True))
        for row in self.payload(draw_count=1)['data']['main']['items']:
            self.assertIsNone(row['averageDelay'])
            self.assertEqual(row['currentDelay'], 0 if row['count'] else 1)
        result = self.payload(period='custom', from_date='2026-01-02', to_date='2026-01-03')
        main = {row['number']: row for row in result['data']['main']['items']}
        self.assertEqual((main['07']['currentDelay'], main['07']['averageDelay']), (0, 0))

    def test_repeated_three_digit_occurrences_in_one_draw_are_one_delay_event(self):
        data, _ = an.build_frequency('MAX_3D', [{'numbers': ['001', '001']}, {'numbers': ['001']}, {'numbers': ['007']}])
        rows = {row['number']: row for row in data['main']['items']}
        self.assertEqual((rows['001']['count'], rows['001']['currentDelay'], rows['001']['averageDelay']), (3, 1, 0))
        self.assertEqual((rows['000']['currentDelay'], rows['000']['delayLowerBound']), (3, True))

    def test_empty_period_returns_no_data_instead_of_invented_frequencies(self):
        result = self.payload(period='custom', from_date='2025-01-01', to_date='2025-01-02')
        self.assertFalse(result['ok'])
        self.assertNotIn('data', result)

    def test_previous_streak_uses_same_rolling_count_before_latest_hit(self):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['Kỳ', 'Ngày', 'Giờ', 'Bộ Số', 'ĐB'])
        for i in range(13):
            writer.writerow([i + 1, (date(2026, 1, 1) + timedelta(days=i)).strftime('%d/%m/%Y'),
                             '21:00', '1,2,3,4,5' if i in [0, 2, 4, 12] else '6,7,8,9,10',
                             '1' if i in [0, 2, 4, 12] else '2'])
        text = stream.getvalue()
        result = self.payload(text, draw_count=12)
        for group in ['main', 'special']:
            row = next(r for r in result['data'][group]['items'] if r['number'] == '01')
            self.assertEqual((row['currentDelay'], row['averageDelay']), (0, 4))
            self.assertEqual((row['previousDelay'], row['previousAverageDelay']), (7, 1))
            # This is exactly the data shown before the new draw, not a mean including its hit.
            before = self.payload('\n'.join(text.splitlines()[:-1]) + '\n', draw_count=12)
            old = next(r for r in before['data'][group]['items'] if r['number'] == '01')
            self.assertEqual((row['previousDelay'], row['previousAverageDelay']),
                             (old['currentDelay'], old['averageDelay']))

    def test_previous_streak_no_guesses_or_duplicate_events(self):
        draws = [{'numbers': ['001', '001']}, {'numbers': ['007']},
                 {'numbers': ['001']}, {'numbers': ['007']}, {'numbers': ['001']}]
        data, _ = an.build_frequency('MAX_3D', draws)
        rows = {r['number']: r for r in data['main']['items']}
        self.assertEqual((rows['001']['previousDelay'], rows['001']['previousAverageDelay']), (1, 1))
        self.assertEqual((rows['000']['previousDelay'], rows['000']['previousAverageDelay']), (None, None))
        result = self.payload(draw_count=1)
        for group in ['main', 'special']:
            self.assertTrue(all(r['previousAverageDelay'] is None for r in result['data'][group]['items']))
        one, _ = an.build_frequency('LOTO_5_35', [{'numbers': ['01'], 'special': '01'}])
        self.assertTrue(all(r['previousDelay'] is None and r['previousAverageDelay'] is None
                            for group in ['main', 'special'] for r in one[group]['items']))

    def test_latest_presets_and_custom_count_use_draws_not_days_or_csv_order(self):
        fixture = frequency_draw_fixture()
        source = list(csv.DictReader(io.StringIO(fixture)))
        for count in [1, 7, 10, 30, 50, 80, 100, 120, 150]:
            with self.subTest(count=count):
                result = self.payload(fixture, period='7d', draw_count=count)
                selected = source[:count]
                self.assertEqual(result['requestedDrawCount'], count)
                self.assertEqual(result['availableDraws'], 120)
                self.assertEqual(result['availableFromDate'], datetime.strptime(source[-1]['Ngày'], '%d/%m/%Y').date().isoformat())
                self.assertEqual(result['availableToDate'], datetime.strptime(source[0]['Ngày'], '%d/%m/%Y').date().isoformat())
                self.assertEqual(result['totalDraws'], min(count, 120))
                self.assertEqual(result['period'], 'draws')
                self.assertEqual(result['latestDraw']['drawId'], '120')
                self.assertEqual(result['previousDraw']['drawId'], '119')
                self.assertEqual(result['previousDraw']['time'], '13:00')
                expected = Counter(f'{int(number):02d}' for row in selected for number in row['Bộ Số'].split(','))
                actual = {row['number']: row['count'] for row in result['data']['main']['items'] if row['count']}
                self.assertEqual(actual, dict(expected))
                self.assertEqual(result['data']['main']['totalOccurrences'], len(selected) * 5)
                self.assertEqual(result['data']['special']['totalOccurrences'], len(selected))

    def test_535_cutoff_session_includes_only_published_draws_up_to_that_time(self):
        fixture = frequency_draw_fixture(count=5)
        for slot, count, latest in [('13:00',3,'3'),('21:00',4,'4')]:
            result = self.payload(fixture, period='custom', from_date='2026-01-01', to_date='2026-01-02', to_time=slot)
            self.assertTrue(result['ok'])
            self.assertEqual(result['totalDraws'],count)
            self.assertEqual(result['data']['main']['totalOccurrences'], count*5)
            self.assertEqual(result['latestDraw']['drawId'],latest)
            self.assertEqual(result['previousDraw']['drawId'],str(int(latest)-1))
            self.assertEqual(result['toTime'],slot)
            self.assertEqual(result['fromTime'],'13:00')
            self.assertEqual(result['availableToTime'],'13:00')
        self.assertFalse(self.payload(fixture, period='custom', from_date='2026-01-01', to_date='2026-01-03', to_time='21:00')['ok'])
        self.assertFalse(self.payload(fixture, period='custom', from_date='2026-01-01', to_date='2026-01-02', to_time='18:00')['ok'])
        self.assertFalse(self.payload(fixture, period='custom', from_date='2026-01-01', to_date='2026-01-02', to_time='13:00', draw_count=2)['ok'])

    def test_two_sessions_on_same_day_are_two_draws(self):
        result = self.payload(frequency_draw_fixture(), draw_count=2)
        self.assertEqual(result['totalDraws'], 2)
        self.assertEqual(result['fromDate'], result['toDate'])
        self.assertEqual(result['data']['main']['totalOccurrences'], 10)

    def test_invalid_draw_counts_are_rejected(self):
        for count in [0, -1, 1.5, True, 2147483648]:
            with self.subTest(count=count):
                self.assertFalse(self.payload(draw_count=count)['ok'])

    def test_previous_draw_is_canonical_predecessor_even_outside_count_or_date_filter(self):
        result = self.payload(draw_count=1)
        self.assertEqual(result['latestDraw']['drawId'], '5')
        self.assertEqual(result['previousDraw']['drawId'], '4')
        self.assertEqual(result['previousDraw']['numbers'], ['02', '03', '04', '05', '06'])
        self.assertEqual(result['previousDraw']['special'], '02')
        self.assertEqual(result['totalDraws'], 1)
        self.assertEqual(result['data']['main']['totalOccurrences'], 5)
        result = self.payload(period='custom', from_date='2026-01-03', to_date='2026-01-03')
        self.assertEqual(result['latestDraw']['drawId'], '3')
        self.assertEqual(result['previousDraw']['drawId'], '2')
        result = self.payload(period='custom', from_date='2026-01-01', to_date='2026-01-01')
        self.assertEqual(result['latestDraw']['drawId'], '1')
        self.assertIsNone(result['previousDraw'])


if __name__ == '__main__':
    unittest.main()
