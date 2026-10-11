"""Regressions for large Keno history ingestion and statistics loading."""
import re
import tempfile
import unittest
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT, js_function


@unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
class KenoStatsPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='keno-stats-ui-', dir=ROOT / 'runtime')
        self.addCleanup(self.temp.cleanup)
        self.browser = Browser(CHROME, Path(self.temp.name))
        self.addCleanup(self.browser.close)
        self.data = (ROOT / 'frontend/vietlott-web-data.js').read_text(encoding='utf-8')
        self.stats = (ROOT / 'frontend/vietlott-web-stats.js').read_text(encoding='utf-8')
        self.core = (ROOT / 'frontend/vietlott-web-core.js').read_text(encoding='utf-8')

    def load_history_functions(self):
        code = """
const TYPES={KENO:{label:'Keno'},LOTO_6_55:{label:'Power'}};
const LIVE_HISTORY_TYPES=Object.keys(TYPES).map(key=>({key,label:TYPES[key].label}));
const DRAW_PRIZE_COLUMNS={LOTO_6_55:[{key:'jackpot1'},{key:'jackpot2'}]};
"""
        code += js_function(self.core, 'normalizeKy')
        for name in ('emptyLiveHistoryFeed', 'cloneDraw', 'kySortValue', 'formatLiveKy', 'normalizeLiveHistoryKy',
                     'mergeLiveHistoryDraw', 'normalizeLiveHistoryRepairErrors', 'getDrawPrizeAmount',
                     'getDrawPrizeFields', 'getDrawPrizeHit', 'buildLiveHistoryFeedFromResponse'):
            code += '\n' + js_function(self.data, name)
        self.browser.value(code)

    def test_bulk_history_sorts_once_preserves_rows_and_overwrites_duplicates(self):
        self.load_history_functions()
        result = self.browser.value("""(() => {
 const rows=Array.from({length:25000},(_,i)=>({ky:String(25000-i),main:[20,2,1],date:'07/10/2026',time:'17:00'}));
 rows.push({ky:'#0007',main:[4,3,2],date:'07/10/2026',time:'17:08'});
 rows.push({ky:'invalid',main:[1,2,3]});
 const original=Array.prototype.sort;
 let largeSorts=0;
 Array.prototype.sort=function(compare){if(this.length>80) largeSorts++;return original.call(this,compare);};
 try {
  const feed=buildLiveHistoryFeedFromResponse('KENO',rows,'loaded','all',{canonicalCount:25000});
  return {largeSorts,count:feed.order.length,canonicalCount:feed.canonicalCount,
   ordered:feed.order.every((ky,i)=>i===0||kySortValue(feed.order[i-1])<kySortValue(ky)),
   first:feed.order[0],last:feed.order.at(-1),duplicate:feed.results['#0007'].main,
   inputUnchanged:rows[0].main.join(',')==='20,2,1'};
 } finally {Array.prototype.sort=original;}
})()""")
        self.assertEqual(1, result['largeSorts'])
        self.assertEqual(25000, result['count'])
        self.assertEqual(25000, result['canonicalCount'])
        self.assertTrue(result['ordered'])
        self.assertTrue(result['inputUnchanged'])
        self.assertEqual('#0001', result['first'])
        self.assertEqual('#25000', result['last'])
        self.assertEqual([2, 3, 4], result['duplicate'])

    def test_single_draw_updates_and_prize_metadata_remain_compatible(self):
        self.load_history_functions()
        result = self.browser.value("""(() => {
 const feed=buildLiveHistoryFeedFromResponse('LOTO_6_55',[
  {ky:'2',main:[6,5,4,3,2,1],special:7,jackpot1:178900548500,jackpot2:3000000000,prizeHit:'Jackpot 1, 2',sourceUrl:'https://example.test',displayLines:['01 02 03 04 05 06']}
 ],'loaded','all',{repairAttempted:true,repairNewRows:1});
 const inserted=mergeLiveHistoryDraw(feed,'1',{main:[1,2,3,4,5,6]});
 const overwritten=mergeLiveHistoryDraw(feed,'#0002',{...feed.results['#0002'],main:[2,3,4,5,6,7]});
 return {inserted,overwritten,order:feed.order,draw:feed.results['#0002'],repairAttempted:feed.repairAttempted};
})()""")
        self.assertTrue(result['inserted'])
        self.assertFalse(result['overwritten'])
        self.assertEqual(['#0001', '#0002'], result['order'])
        self.assertTrue(result['repairAttempted'])
        self.assertEqual(178900548500, result['draw']['jackpot1'])
        self.assertEqual('Jackpot 1, 2', result['draw']['prizeHit'])
        self.assertEqual('https://example.test', result['draw']['sourceUrl'])

    def load_refresh_function(self):
        start = self.stats.index('    async function startStatsPanelRefresh(')
        end = start + re.search(r'^    }', self.stats[start:], re.MULTILINE).end()
        code = """
let statsSelectedType='KENO',statsPanelRefreshToken=0,statsPanelLoading=false,statsPanelError='';
const normalizeStatsType=x=>x;
const getStatsTypeUiMeta=x=>({label:x});
const state={fetched:false,renders:[],requests:[],reconciled:0,cycles:0,saves:0};
const renderStatsPanel=()=>state.renders.push({fetched:state.fetched,loading:statsPanelLoading});
const fetchLiveHistory=async(type,count,options)=>{state.requests.push({type,count,options});state.fetched=true;};
let releaseLedger;
const scorePendingPredictionLedger=()=>new Promise(resolve=>{releaseLedger=resolve;});
const refreshPredictionLedgerForHistory=async()=>false;
const reconcilePredictionLogsForType=()=>state.reconciled++;
const buildStatsEntriesForFeed=()=>[{ky:'1'},{ky:'2'}];
const getLiveHistoryFeed=()=>({});
const ensureStatsPredictionCycle=()=>{state.cycles++;return true;};
const saveStore=async()=>{state.saves++;};
""" + self.stats[start:end]
        self.browser.value(code)
        self.browser.value('window.refreshPromise=startStatsPanelRefresh({force:true,silent:true});true')

    def test_history_displays_before_ledger_sync_without_implicit_repair(self):
        self.load_refresh_function()
        state = self.browser.value('state')
        self.assertTrue(any(render['fetched'] for render in state['renders']))
        self.assertEqual('all', state['requests'][0]['count'])
        self.assertNotIn('repair', state['requests'][0]['options'])
        self.assertNotIn('recentDays', state['requests'][0]['options'])
        self.assertEqual(0, state['cycles'])
        self.browser.value('releaseLedger(false);true')
        self.assertEqual(1, self.browser.value('state.cycles'))
        self.assertEqual(1, self.browser.value('state.saves'))
        self.assertFalse(self.browser.value('statsPanelLoading'))

    def test_stale_refresh_cannot_create_predictions_after_type_changes(self):
        self.load_refresh_function()
        self.browser.value("statsPanelRefreshToken++;statsSelectedType='LOTO_6_55';releaseLedger(true);true")
        self.assertEqual(0, self.browser.value('state.cycles'))
        self.assertEqual(0, self.browser.value('state.saves'))
        self.assertEqual(0, self.browser.value('state.reconciled'))


if __name__ == '__main__':
    unittest.main()
