import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai import keno_prize_context as k
from ai import account_statistics as stats
from ai.prizes import KENO_WINNING_HITS


def expected():
    return k.identity('298889',{'main':list(range(1,21))},'2026-10-11T06:52:00Z')


def source(counts=None):
    counts=counts or {}
    result='<div id="divKenoResultContent"><table class="table-result-info"><tr><td>11/10/2026</td><td>#0298889</td><td><div class="day_so_ket_qua_v2">'+''.join(f'<span class="bong_tron">{n}</span>' for n in range(1,21))+'</div></td></tr></table>'
    for level in range(10,0,-1):
        result+='<table class="tabSelNumberInfo"><tr><th>Xác định kết quả</th><th>Giá trị trúng thưởng (Số lượng trúng thưởng)</th></tr>'
        for hits in sorted(KENO_WINNING_HITS[level],reverse=True):
            amount=k.NOMINAL[level] if hits==level and level in k.NOMINAL else stats.KENO[level][hits]
            quantity=counts.get(level) if hits==level else 3
            suffix=f' ( Số lượng: {quantity} )' if quantity is not None else ''
            result+=f'<tr><td>Trùng {hits:02} trong 20 số</td><td>{amount:,} đ{suffix}</td></tr>'.replace(',','.')
        result+='</table>'
    return result+'<table class="tabSelNumberInfo"></table><table class="tabSelNumberInfo"></table></div>'


class KenoPrizeContextTests(unittest.TestCase):
    def test_complete_published_zero_encoding_and_explicit_counts(self):
        data=k.parse_official(source({8:1,9:0}),expected())
        self.assertEqual(data['winnerCounts'],{'8':1,'9':0,'10':0})
        self.assertEqual(data['countEncoding']['10'],'omitted_zero_in_complete_published_level_table')
        self.assertEqual(data['countEncoding']['9'],'explicit_count')

    def test_missing_rows_placeholders_wrong_identity_are_not_zero(self):
        html=source()
        for broken in (html.replace('11/10/2026','12/10/2026'),html.replace('#0298889','#0298890'),
                       html.replace('Trùng 08 trong 20 số','Trùng 07 trong 20 số',1),
                       html.replace('200.000.000 đ','—'),html.replace('Số lượng: 3','Số lượng: —'),
                       html.replace('class="bong_tron">20','class="bong_tron">21'),
                       html.replace('<table class="tabSelNumberInfo"></table>','',1)):
            with self.subTest(broken=broken[-50:]),self.assertRaises(ValueError):k.parse_official(broken,expected())
        no_stats=html.replace(' ( Số lượng: 3 )','')
        with self.assertRaises(ValueError):k.parse_official(no_stats,expected())

    def test_shared_caps_thresholds_actual_plus_simulated_and_rounding(self):
        for level in (8,9,10):
            threshold=k.THRESHOLD[level]
            self.assertEqual(k.unit_amount(level,threshold-1,1),k.NOMINAL[level])
            self.assertEqual(k.unit_amount(level,threshold,1),k.POOL//(threshold+1))
            self.assertEqual(k.unit_amount(level,2,3),k.NOMINAL[level])
            self.assertEqual(k.unit_amount(level,2,79),k.POOL//81)
            for invalid in (True,-1,None,'0'):
                self.assertIsNone(k.unit_amount(level,invalid,1))
            self.assertIsNone(k.unit_amount(level,0,0))
            self.assertIsNone(k.unit_amount(level,k.MAX_SAFE,1))

    def test_cache_identity_and_account_payout_all_top_levels(self):
        draw=expected()
        record=k.parse_official(source({8:49,9:12,10:5}),draw)
        records={draw['ky']:record}
        at=stats.stamp(draw['drawAt'])
        for level in (8,9,10):
            amount,missing,won,unknown=stats.reward_amount('KENO',{f'KENO_{level}_{level}':2},
                {'main':draw['main']},at,draw['ky'],records,level)
            self.assertEqual(amount,k.unit_amount(level,record['winnerCounts'][str(level)],2)*2)
            self.assertEqual((missing,won,unknown),(False,2,0))
        wrong=copy.deepcopy(record)
        wrong['draw']['time']='14:00'
        self.assertEqual(k.context_for(draw['ky'],{'main':draw['main']},at,{draw['ky']:wrong})['status'],'mismatch')
        incomplete=copy.deepcopy(record)
        incomplete['winnerCounts'].pop('9')
        self.assertEqual(k.context_for(draw['ky'],{'main':draw['main']},at,{draw['ky']:incomplete})['status'],'missing')
        self.assertTrue(stats.reward_amount('KENO',{'KENO_8_8':1},{'main':draw['main']},at,draw['ky'],{},8)[1])

    def test_cache_read_is_safe_and_refresh_writes_only_separate_evidence(self):
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)/'prizes.json'
            self.assertEqual(k.load_cache(path)['draws'],{})

            with patch.object(k,'needed_draws',return_value={'298889':expected()}), \
                 patch('backend.live_results.fetch_official_counts_html',return_value=source()+'\r\n'), \
                 patch.object(k.time,'sleep'):
                result=k.refresh(Path(work)/'never-created.db',cache_path=path,evidence_dir=Path(work)/'source')
            self.assertEqual(result['updated'],1)
            self.assertFalse(result['errors'])
            self.assertFalse((Path(work)/'never-created.db').exists())
            import hashlib
            self.assertEqual(hashlib.sha256((Path(work)/'source/298889.html').read_bytes()).hexdigest(),k.load_cache(path)['draws']['298889']['htmlSha256'])
            before=path.read_bytes()
            with patch.object(k,'needed_draws',return_value={'298889':expected()}), \
                 patch('backend.live_results.fetch_official_counts_html') as fetch:
                self.assertEqual(k.refresh('unused',cache_path=path)['updated'],0)
                fetch.assert_not_called()
            self.assertEqual(path.read_bytes(),before)
            path.write_text('bad json',encoding='utf-8')
            self.assertEqual(k.load_cache(path)['draws'],{})


    def test_global_source_cooldown_skips_network_and_database(self):
        with tempfile.TemporaryDirectory() as work:
            cooldown=Path(work)/'cooldown.json'
            cooldown.write_text(json.dumps({'blockedUntil':time.time()+600}),encoding='utf-8')
            with patch('backend.live_results.OFFICIAL_PRIZE_COUNTS_COOLDOWN_FILE',cooldown), \
                 patch.object(k,'needed_draws') as needed, \
                 patch('backend.live_results.fetch_official_counts_html') as fetch:
                self.assertEqual(k.refresh('unused')['status'],'source_cooldown')
                needed.assert_not_called()
                fetch.assert_not_called()


if __name__=='__main__':unittest.main()
