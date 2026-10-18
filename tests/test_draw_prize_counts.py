import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from backend import live_results as lr
from tests.test_prize_history import draw
from scripts.backfill_minhchinh_winner_counts import apply_evidence, parse_page
from tests import test_effectiveness_web as bridge_module


def official_html(key, row, counts):
    game = {"LOTO_5_35":"5/35", "LOTO_6_45":"6/45", "LOTO_6_55":"6/55"}[key]
    balls = row["Main"].split(",") + ([row["Special"]] if row["Special"] else [])
    labels = {"specialPrize":"Giải Độc Đắc", "jackpot":"Jackpot", "jackpot1":"Jackpot 1", "jackpot2":"Jackpot 2", "first":"Giải Nhất", "second":"Giải Nhì", "third":"Giải Ba", "fourth":"Giải Tư", "fifth":"Giải Năm", "consolation":"Giải Khuyến Khích"}
    return (f'<div class="chitietketqua"><h4>{game}</h4><h5>Kỳ #{int(row["Ky"]):05d} ngày {row["Ngay"]}</h5>'
            + '<div class="day_so_ket_qua">' + ''.join(f'<span class="bong_tron">{ball}</span>' for ball in balls) + '</div>'
            + '<div class="chitietketqua_table"><table><tbody>'
            + ''.join(f'<tr><td>{labels[key]}</td><td>O O</td><td>{value}</td><td>10.000</td></tr>' for key,value in counts.items())
            + '</tbody></table></div></div>')


class DrawPrizeCountTests(unittest.TestCase):
    def test_official_urls_use_verified_game_routes(self):
        for key,path in [('LOTO_5_35','535'),('LOTO_6_45','645'),('LOTO_6_55','655')]:
            self.assertEqual(lr.official_prize_counts_url(key,'941'),f'https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/{path}?id=00941&nocatche=1')

    def test_parse_all_games_preserves_zero_and_grouped_counts(self):
        for key, keys in lr.PRIZE_WINNER_KEYS_BY_TYPE.items():
            result = draw(key)
            row = lr.result_to_csv_row(result)
            source = {name: ("15.914" if name=="consolation" else "0" if index==0 else str(index)) for index,name in enumerate(keys)}
            counts = lr.parse_official_prize_winner_counts(key, official_html(key,row,source), row)
            self.assertEqual(counts, {name:15914 if value=="15.914" else int(value) for name,value in source.items()})

    def test_official_identity_mismatch_is_rejected(self):
        key="LOTO_5_35"
        row=lr.result_to_csv_row(draw(key))
        html=official_html(key,row,{"specialPrize":0,"first":1})
        for field, replacement in (("Ky","9999"),("Ngay","01/01/2026"),("Main","20,21,22,23,24"),("Special","12")):
            wrong={**row,field:replacement}
            with self.subTest(field=field), self.assertRaises(ValueError):
                lr.parse_official_prize_winner_counts(key,html,wrong)
        with self.assertRaises(ValueError):
            lr.parse_official_prize_winner_counts(key,html.replace('5/35','6/45'),row)

    def test_missing_statistics_are_not_zero_and_boolean_is_invalid(self):
        key="LOTO_5_35"
        row=lr.result_to_csv_row(draw(key))
        counts=lr.parse_official_prize_winner_counts(key,official_html(key,row,{"specialPrize":0,"first":"—"}),row)
        self.assertEqual(counts,{"specialPrize":0})
        self.assertEqual(lr.valid_prize_winner_counts(key,{"first":True,"second":-1,"third":None,"fourth":0}),{"fourth":0})

    def test_minhchinh_parser_keeps_all_prize_rows(self):
        lines=["Giải","Trùng khớp","Số lượng","Giá trị","Độc đắc","0","6,000,000,000",
               "Nhất","1","10,000,000","Nhì","7","5,000,000","Ba","77","500,000",
               "Tư","173","100,000","Năm","2,056","30,000","Khuyến khích","15,914","10,000"]
        parsed=lr.parse_numeric_prize_hits(lr.LIVE_TYPES['LOTO_5_35'],lines)
        self.assertEqual(parsed['prizeWinnerCounts'],dict(specialPrize=0,first=1,second=7,third=77,fourth=173,fifth=2056,consolation=15914))
        self.assertEqual(parsed['prizeHit'],'')

    def test_minhchinh_short_consolation_label_and_missing_pool_amount(self):
        lines = ["Giải", "Trùng khớp", "Số lượng", "Giá trị", "Độc đắc", "0", ",,,",
                 "Giải nhất", "0", "10,000,000", "Giải nhì", "10", "5,000,000",
                 "Giải ba", "141", "500,000", "Giải tư", "384", "100,000",
                 "Giải năm", "3,648", "30,000", "Giải kk", "28,696", "10,000"]
        parsed = lr.parse_numeric_prize_hits(lr.LIVE_TYPES['LOTO_5_35'], lines)
        self.assertEqual(parsed['prizeWinnerCounts'], dict(specialPrize=0, first=0, second=10,
                         third=141, fourth=384, fifth=3648, consolation=28696))
        lines = ["Giải", "Trùng khớp", "Số lượng", "Giá trị", "Jackpot", "0", ",,,",
                 "Giải nhất", "32", "10,000,000", "Giải nhì", "1,658", "300,000",
                 "Giải ba", "25,751", "30,000"]
        parsed = lr.parse_numeric_prize_hits(lr.LIVE_TYPES['LOTO_6_45'], lines)
        self.assertEqual(parsed['prizeWinnerCounts'], dict(jackpot=0, first=32, second=1658, third=25751))
        lines[5] = '—'
        self.assertEqual(lr.parse_numeric_prize_hits(lr.LIVE_TYPES['LOTO_6_45'], lines), {})

    def test_backfill_checks_identity_and_only_fills_missing_counts(self):
        key = 'LOTO_6_45'
        row = lr.result_to_csv_row(draw(key))
        row[lr.PRIZE_WINNER_COUNTS_FIELD] = {'jackpot': 0, 'first': 9}
        identity = lr.loto535_draw_identity(row)
        evidence = {row['Ky']: {'identity': identity, 'counts': {'jackpot': 1, 'first': 1, 'second': 500},
                               'sourceUrl': 'https://www.minhchinh.com/source', 'checkedAt': 'now'}}
        with mock.patch.object(lr, 'load_canonical_rows', return_value=({row['Ky']: row}, {'keep': 123}, {})), mock.patch.object(lr, 'write_canonical_meta') as writer:
            self.assertEqual(apply_evidence(key, evidence), 1)
            saved = writer.call_args.args[1]
            self.assertEqual(saved['keep'], 123)
            self.assertEqual(saved['prizeWinners']['countsByDraw'][row['Ky']]['counts'], {'jackpot': 0, 'first': 9, 'second': 500})
            writer.reset_mock()
            self.assertEqual(apply_evidence(key, evidence), 0)
            writer.assert_not_called()
            evidence[row['Ky']]['identity'] = 'wrong draw'
            evidence[row['Ky']]['counts']['third'] = 999
            self.assertEqual(apply_evidence(key, evidence), 0)
            writer.assert_not_called()

    def test_backfill_parses_each_draw_in_a_page_including_prior_dates(self):
        lines = []
        for ky, date, count in [(20, '03/10/2026', 12), (19, '01/10/2026', 34)]:
            lines.extend(['Kết quả Mega 6/45', f'Kết quả QSMT kỳ #{ky} ngày {date}',
                          '01', '02', '03', '04', '05', '06', 'Giải', 'Trùng khớp', 'Số lượng', 'Giá trị',
                          'Jackpot', '0', '10,000,000,000', 'Giải nhất', str(count), '10,000,000',
                          'Giải nhì', '100', '300,000', 'Giải ba', '1000', '30,000'])
        html = ''.join('<div>' + line + '</div>' for line in lines)
        parsed = parse_page('LOTO_6_45', html, 'https://www.minhchinh.com/source')
        self.assertEqual([(r['ky'], r['date'], r['prizeWinnerCounts']['first']) for r in parsed],
                         [('20', '03/10/2026', 12), ('19', '01/10/2026', 34)])

    def test_fallback_and_partial_updates_preserve_verified_counts(self):
        result=draw('LOTO_5_35')
        result['prizeWinnerCounts']=dict(specialPrize=0,first=1,second=7)
        rows={result['ky']:lr.result_to_csv_row(result)}
        fallback=draw('LOTO_5_35')
        lr.merge_result_rows(rows,[fallback])
        self.assertEqual(rows[result['ky']][lr.PRIZE_WINNER_COUNTS_FIELD],result['prizeWinnerCounts'])
        fallback['prizeWinnerCounts']={'first':0}
        lr.merge_result_rows(rows,[fallback])
        self.assertEqual(rows[result['ky']][lr.PRIZE_WINNER_COUNTS_FIELD],dict(specialPrize=0,first=0,second=7))
        fallback['special']=12
        fallback.pop('prizeWinnerCounts')
        lr.merge_result_rows(rows,[fallback])
        self.assertNotIn(lr.PRIZE_WINNER_COUNTS_FIELD,rows[result['ky']])

    def test_metadata_csv_api_roundtrip_keeps_counts_and_csv_header_unchanged(self):
        result=draw('LOTO_5_35')
        result.update(prizeWinnerCounts=dict(specialPrize=0,first=0,second=7,third=77,fourth=173,fifth=2056,consolation=15914))
        rows={result['ky']:lr.result_to_csv_row(result)}
        meta={'prizeWinners':lr.build_prize_winner_meta('LOTO_5_35',rows)}
        with tempfile.TemporaryDirectory() as folder:
            csv=Path(folder)/'loto_5_35_all_day.csv'
            lr.write_csv_rows(csv,rows,type_key='LOTO_5_35')
            header=csv.read_text(encoding='utf-8').splitlines()[0]
            self.assertNotIn('SL',header)
            restored=lr.load_csv_rows(csv,type_key='LOTO_5_35')
            lr.restore_prize_winner_counts('LOTO_5_35',restored,meta)
            item=lr.csv_row_to_history_item(restored[result['ky']])
            self.assertEqual(item['prizeWinnerCounts'],result['prizeWinnerCounts'])
            self.assertEqual(lr.history_item_to_live_result('LOTO_5_35',item)['prizeWinnerCounts'],result['prizeWinnerCounts'])
            restored[result['ky']]['Special']='12'
            restored[result['ky']].pop(lr.PRIZE_WINNER_COUNTS_FIELD)
            lr.restore_prize_winner_counts('LOTO_5_35',restored,meta)
            self.assertNotIn(lr.PRIZE_WINNER_COUNTS_FIELD,restored[result['ky']])

    def test_meta_write_merges_concurrent_evidence_without_erasing_other_prizes(self):
        row=lr.result_to_csv_row(draw('LOTO_5_35'));identity=lr.loto535_draw_identity(row)
        previous={'prizeWinners':{'countsByDraw':{'1':{'identity':identity,'counts':{'specialPrize':0,'first':1}},'2':{'identity':'other','counts':{'first':2}}}}}
        incoming={'prizeWinners':{'countsByDraw':{'1':{'identity':identity,'counts':{'first':0}}}}}
        with mock.patch.object(lr,'read_canonical_meta',return_value=previous), mock.patch.object(lr,'write_text_atomic') as writer:
            lr.write_canonical_meta('LOTO_5_35',incoming)
        saved=json.loads(writer.call_args.args[1])['prizeWinners']['countsByDraw']
        self.assertEqual(saved['1']['counts'],{'specialPrize':0,'first':0})
        self.assertEqual(saved['2'],previous['prizeWinners']['countsByDraw']['2'])

    def test_live_enrichment_is_cached_and_statistics_failure_keeps_result(self):
        base=draw('LOTO_5_35');row=lr.result_to_csv_row(base)
        expected={key:0 for key in lr.PRIZE_WINNER_KEYS_BY_TYPE['LOTO_5_35']}
        cache={};session=mock.Mock()
        with mock.patch.object(lr,'fetch_latest_vietlott_result',side_effect=lambda *args:copy.deepcopy(base)), mock.patch.object(lr,'fetch_history_results_for_date',return_value=[]), mock.patch.object(lr,'fetch_official_counts_html',return_value=official_html('LOTO_5_35',row,expected)) as fetch:
            for _ in range(2):
                result=lr.fetch_live_result(session,cache,'LOTO_5_35')
                self.assertEqual(result['prizeWinnerCounts'],expected)
            self.assertEqual(fetch.call_count,1)
        with mock.patch.object(lr,'fetch_latest_vietlott_result',return_value=base), mock.patch.object(lr,'fetch_history_results_for_date',return_value=[]), mock.patch.object(lr,'fetch_official_counts_html',side_effect=lr.requests.ConnectionError):
            self.assertEqual(lr.fetch_live_result(session,{},'LOTO_5_35'),base)

    def test_rate_limit_stops_further_network_requests_during_cooldown(self):
        response=mock.Mock(status_code=429,headers={'Retry-After':'120'})
        response.raise_for_status.side_effect=lr.requests.HTTPError(response=response)
        session=mock.Mock();session.get.return_value=response
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(lr,'OFFICIAL_PRIZE_COUNTS_COOLDOWN_FILE',Path(folder)/'cooldown.json'):
            for _ in range(2):
                with self.assertRaises(lr.requests.HTTPError):
                    lr.fetch_official_counts_html(session,'https://vietlott.vn/result')
            self.assertEqual(session.get.call_count,1)

@unittest.skipUnless(Path(bridge_module.JAVAC).exists() and Path(bridge_module.JAVA).exists(), 'JDK required')
class DrawPrizeCountsHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge=bridge_module.EffectivenessWebTests
        cls.bridge.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.bridge.tearDownClass()

    def test_java_fast_history_reads_verified_counts_and_ignores_stale_identity(self):
        root=self.bridge.work
        (root/'backend/live_results.py').write_text("raise AssertionError('Counts must use Java CSV path')\n",encoding='utf-8')
        folder=root/'data/canonical';folder.mkdir(parents=True,exist_ok=True)
        for key in lr.PRIZE_WINNER_KEYS_BY_TYPE:
            result=draw(key);row=lr.result_to_csv_row(result)
            unknown=lr.result_to_csv_row(draw(key,ky='1404'))
            counts={name:index for index,name in enumerate(lr.PRIZE_WINNER_KEYS_BY_TYPE[key])}
            csv=folder/(lr.CANONICAL_OUTPUT_STEMS[key]+'_all_day.csv')
            lr.write_csv_rows(csv,{row['Ky']:row,unknown['Ky']:unknown},type_key=key)
            identity=lr.loto535_draw_identity(row)
            metadata={'prizeWinners':{'countsByDraw':{row['Ky']:{'identity':identity,'counts':counts},unknown['Ky']:{'identity':'incorrect draw','counts':counts}}}}
            csv.with_suffix('.meta.json').write_text(json.dumps(metadata),encoding='utf-8')
            code,payload,headers=self.bridge.request('/api/live-history?type='+key+'&count=all',cookie=self.bridge.member)
            self.assertEqual(code,200,payload)
            self.assertEqual(headers.get('X-Lotto-History-Source'),'java-csv')
            by_ky={item['ky']:item for item in payload['history']}
            self.assertEqual(by_ky[row['Ky']]['prizeWinnerCounts'],counts)
            self.assertEqual(by_ky[unknown['Ky']]['prizeWinnerCounts'],{})
            metadata['prizeWinners']['countsByDraw'][row['Ky']]['counts']={'first':True,'second':-1,'third':0}
            csv.with_suffix('.meta.json').write_text(json.dumps(metadata),encoding='utf-8')
            code,payload,_=self.bridge.request('/api/live-history?type='+key+'&count=all',cookie=self.bridge.member)
            self.assertEqual(code,200,payload)
            self.assertEqual(payload['history'][0]['prizeWinnerCounts'],{'third':0})

if __name__=='__main__':
    unittest.main()
