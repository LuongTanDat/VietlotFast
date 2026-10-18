"""Live prize differences use adjacent canonical draws, never another draw's pool."""
import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT, js_function


class LivePrizeChangeTests(unittest.TestCase):
    def test_adjacent_draws_loading_cache_errors_and_logout(self):
        source = (ROOT / 'frontend/vietlott-web-data.js').read_text(encoding='utf-8')
        core = (ROOT / 'frontend/vietlott-web-core.js').read_text(encoding='utf-8')
        code = source[source.index('    const DRAW_PRIZE_COLUMNS'):source.index('    function getDrawPrizeAmount')]
        for name in ('getDrawPrizeAmount', 'formatDrawPrizeAmount', 'renderLiveNumberToken', 'renderLiveInlineResultLine', 'renderLiveCardMainLines', 'renderLiveResultsBoard'):
            code += js_function(source, name)
        code += js_function(core, 'getLiveResultSignature')
        script = '''
const TYPES={LOTO_5_35:{hasSpecial:true},LOTO_6_45:{},LOTO_6_55:{hasSpecial:true},KENO:{},MAX_3D:{threeDigit:true},MAX_3D_PRO:{threeDigit:true}};
const gameLabels=['Loto_5/35','Mega_6/45','Power_6/55','Keno','Max 3D','Max 3D Pro'];
const LIVE_RESULT_TYPES=Object.keys(TYPES).map((key,index)=>({key,label:gameLabels[index]}));
const liveSingleRefreshBusy=new Set(), IS_LOCAL_MODE=false;
let currentUser='fixture', calls=[], pending=[];
let liveResultsState={};
const escapeHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const getSyncedNowDate=()=>new Date('2026-10-16T14:00:00Z');
const getLiveResultsBoardSignature=()=>JSON.stringify(liveResultsState);
const getLiveUpdateBadge=()=>({label:'Hoàn tất'});
const liveUpdateBadgeClass=()=>'ok';
const buildUpcomingLiveMetaParts=()=>['Kỳ #10','T7 17/10','18:00','12:08:13'];
const formatPredictNumber=(number,type)=>String(number).padStart(TYPES[type]?.threeDigit?3:2,'0');
const updateLiveResultsCountdownText=()=>{};
const api=url=>{calls.push(url);return new Promise((resolve,reject)=>pending.push({url,resolve,reject}));};
const amounts={LOTO_5_35:{specialPrize:6139472500},LOTO_6_45:{jackpot:22839868000},LOTO_6_55:{jackpot1:156701347950,jackpot2:5217498700}};
const before={LOTO_5_35:{specialPrize:6100000000},LOTO_6_45:{jackpot:20000000000},LOTO_6_55:{jackpot1:150000000000,jackpot2:5300000000}};
const histories={};
for(const type of Object.keys(amounts)){
 const main=type==='LOTO_5_35'?[5,9,10,28,33]:[9,20,26,35,36,38];
 const row={key:type,ky:'10',date:'16/10/2026',time:'18:00',main,special:7,displayLines:[main.map(n=>String(n).padStart(2,'0')).join(' ')+(TYPES[type].hasSpecial?' | 07':'')],...amounts[type]};
 liveResultsState[type]=row;
 const canonicalTime=type==='LOTO_5_35'?row.time:'';
 histories[type]=[{...row,time:canonicalTime},{...row,ky:'9',date:'15/10/2026',time:canonicalTime,...before[type]}];
}
liveResultsState.KENO={key:'KENO',ky:'10',main:[3,4,7,16,29,33,39,44,45,49,51,52,55,60,61,62,64,71,74,79]};
for(const type of ['MAX_3D','MAX_3D_PRO'])liveResultsState[type]={key:type,ky:'10',displayLines:['Đặc biệt: 481 094','Giải nhất: 934 612 794 955','Giải nhì: 272 630 812 929 802 475','Giải ba: 690 649 208 272 060 022 854 480']};
const respondAll=()=>{for(const task of pending.splice(0)){const type=new URL(task.url,'http://fixture').searchParams.get('type');task.resolve({type,history:histories[type]});}};
window.errors=[];window.addEventListener('error',e=>errors.push(e.message));window.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
''' + code + '\nrenderLiveResultsBoard({force:true});'
        styles = ''.join(f'<link rel="stylesheet" href="{(ROOT / "frontend" / name).as_uri()}">' for name in ('vietlott-web.css', 'vietlott-web-extra.css'))
        with tempfile.TemporaryDirectory(prefix='live_prize_change_', dir=ROOT / 'runtime') as folder:
            work = Path(folder)
            page = work / 'fixture.html'
            page.write_text('<!doctype html><meta charset="utf-8">' + styles + '<section id="liveBoardSection" class="live-board"><div id="liveResultGrid" class="live-result-grid"></div></section><script>' + script + '</script>', encoding='utf-8')
            b = Browser(CHROME, work / 'profile')

            def wait(expression):
                end = time.monotonic() + 10
                while time.monotonic() < end:
                    if b.value(expression):
                        return
                    time.sleep(.03)
                self.fail('Timeout: ' + expression + str(b.value('window.errors')))

            try:
                b.call('Page.enable', page=True)
                b.call('Page.navigate', {'url': page.as_uri()}, page=True)
                wait('typeof pending!=="undefined"&&pending.length===3')
                self.assertEqual(b.value('calls.length'), 3)
                self.assertTrue(b.value('calls.every(url=>url.includes("count=2&drawIds=10,9")&&!url.includes("repair"))'))
                b.value('renderLiveResultsBoard({force:true});loadLivePrizeComparisons()')
                self.assertEqual(b.value('calls.length'), 3)
                b.value('respondAll()')
                wait('[...livePrizeComparisonState.values()].every(s=>!s.loading)')
                text = b.value('document.getElementById("liveResultGrid").textContent')
                for expected in ('39.472.500 VNĐ', '2.839.868.000 VNĐ', '6.701.347.950 VNĐ', '82.501.300 VNĐ', '22.839.868.000 VNĐ'):
                    self.assertIn(expected, text)
                self.assertTrue(b.value('document.querySelector(".live-prize-change.is-up").getAttribute("aria-label").startsWith("Tăng ")&&document.querySelector(".live-prize-change.is-down").title.startsWith("Giảm ")'))
                self.assertTrue(b.value('document.querySelectorAll(".live-prize-arrow svg").length===4&&getComputedStyle(document.querySelector(".is-down .live-prize-arrow svg")).transform==="matrix(-1, 0, 0, -1, 0, 0)"'))
                self.assertEqual(b.value('document.querySelectorAll(".live-card").length'), 6)
                self.assertEqual(b.value('[...document.querySelectorAll(".has-prizes")].map(card=>card.querySelectorAll(".live-card-number").length)'), [6, 6, 7])
                self.assertEqual(b.value('document.querySelectorAll(".live-card-foot").length'), 0)
                b.value('loadLivePrizeComparisons()')
                self.assertEqual(b.value('calls.length'), 3)
                # Missing adjacent draw, wrong identity, unknown amount and duplicates cannot become an increase.
                for rows in ('[histories.LOTO_6_45[0],{...histories.LOTO_6_45[1],ky:"8"}]', '[{...histories.LOTO_6_45[0],main:[7,8,9]},histories.LOTO_6_45[1]]', '[histories.LOTO_6_45[0],{...histories.LOTO_6_45[1],jackpot:null}]', '[histories.LOTO_6_45[0],histories.LOTO_6_45[0]]'):
                    self.assertEqual(b.value(f'getLivePrizeChanges("LOTO_6_45",liveResultsState.LOTO_6_45,{rows})'), {})
                b.value('histories.LOTO_6_55[1].jackpot2=5217498700;loadLivePrizeComparisons(true);respondAll()')
                wait('document.querySelector("[data-live-prize-key=jackpot2]").textContent==="Không đổi"')
                # New live amounts are hidden until canonical confirms the same draw and amount.
                b.value('liveResultsState.LOTO_6_45={...liveResultsState.LOTO_6_45,jackpot:30000000000};renderLiveResultsBoard({force:true});respondAll()')
                wait('[...livePrizeComparisonState.values()].every(s=>!s.loading)')
                self.assertIn('Chưa đủ dữ liệu', b.value('document.querySelector("[data-live-prize-key=jackpot]").textContent'))
                b.value('liveResultsState.LOTO_6_45={...histories.LOTO_6_45[0],time:"18:00"};renderLiveResultsBoard({force:true});respondAll()')
                wait('[...livePrizeComparisonState.values()].every(s=>!s.loading)')
                b.value('histories.LOTO_6_55[1].jackpot2=5300000000;loadLivePrizeComparisons(true);respondAll()')
                wait('!!document.querySelector(".live-prize-change.is-down")')
                image_dir = ROOT / 'Bin/session_1_latest/balanced_live_card_images'
                image_dir.mkdir(exist_ok=True)
                for width in (320, 390, 768, 1024, 1280, 1440, 1920):
                    b.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, page=True)
                    for light in (False, True):
                        b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                        self.assertTrue(b.value('[...document.querySelectorAll(".live-card-amount")].every(row=>row.scrollWidth<=row.clientWidth+1)'), (width, light))
                        self.assertTrue(b.value('[...document.querySelectorAll(".live-prize-arrow")].every(a=>a.getBoundingClientRect().width>=22&&a.getBoundingClientRect().height>=22)'), (width, light))
                        self.assertTrue(b.value('document.documentElement.scrollWidth<=innerWidth+1&&[...document.querySelectorAll(".live-card-main")].every(panel=>panel.scrollWidth<=panel.clientWidth+1&&panel.scrollHeight<=panel.clientHeight+1)'), (width, light))
                        self.assertTrue(b.value('(()=>{const p=[...document.querySelectorAll(".has-prizes .live-card-main")].map(el=>el.getBoundingClientRect());return p.every(r=>r.height===64)&&(innerWidth<=1280||p.every(r=>Math.abs(r.top-p[0].top)<1))})()'), (width, light))
                        self.assertEqual(b.value('document.querySelector("[data-live-type=KENO]").querySelectorAll(".live-card-number").length'), 20)
                        self.assertEqual(b.value('document.querySelector("[data-live-type=MAX_3D]").querySelectorAll(".live-card-number").length'), 20)
                        if (width, light) in ((1440, False), (390, True)):
                            b.call('Runtime.evaluate', {'expression':'Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))','awaitPromise':True},page=True)
                            shot = b.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True, 'clip': {'x': 0, 'y': 0, 'width': width, 'height': b.value('document.documentElement.scrollHeight'), 'scale': 1}}, page=True)
                            (image_dir / f'{width}_{"light" if light else "dark"}.png').write_bytes(base64.b64decode(shot['data']))
                b.value('loadLivePrizeComparisons(true);currentUser=null;window.dispatchEvent(new Event("dvlf:auth-changed"));respondAll()')
                wait('livePrizeComparisonState.size===0')
                self.assertEqual(b.value('document.querySelectorAll(".live-prize-arrow").length'), 0)
                b.value('currentUser="other";window.dispatchEvent(new Event("dvlf:auth-changed"));for(const task of pending.splice(0))task.reject(new Error("fixture failure"))')
                wait('livePrizeComparisonState.size===3&&[...livePrizeComparisonState.values()].every(s=>!s.loading)')
                self.assertEqual(b.value('document.querySelectorAll(".live-prize-arrow").length'), 0)
                self.assertEqual(b.value('window.errors'), [])
                proof = {'ok': True, 'layouts': 14, 'allSixGamesRendered': True, 'aligned64pxPrizePanels': True, 'all20KenoAnd3dNumbersPreserved': True, 'adjacentDrawOnly': True, 'rawAmountsUnchanged': True, 'deduplicatedRequests': True, 'logoutStaleResponseIgnored': True}
                (ROOT / 'Bin/session_1_latest/balanced_live_card_verification.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
            finally:
                b.close()
