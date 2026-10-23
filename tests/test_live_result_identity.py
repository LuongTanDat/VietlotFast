"""Upcoming live jackpots reset after a win while historical results stay intact."""
import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT, js_function


@unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
class LiveResultIdentityTests(unittest.TestCase):
    def test_result_identity_countdowns_cache_and_all_six_games(self):
        source=(ROOT/'frontend/vietlott-web-data.js').read_text(encoding='utf-8')
        core=(ROOT/'frontend/vietlott-web-core.js').read_text(encoding='utf-8')
        code=source[source.index('    const DRAW_PRIZE_COLUMNS'):source.index('    function getDrawPrizeAmount')]
        code+=core[core.index('    const LIVE_DRAW_SCHEDULES'):core.index('    const KENO_LIVE_HISTORY_RANGE_KEYS')]
        names=('formatLiveKy','parseLiveDate','formatLiveWeekdayShortFromDate','formatLiveDateShortFromDate',
               'parseScheduleTimeToMinutes','buildScheduleDate','formatDrawCountdown','computeNextLiveKy',
               'findNextLiveDrawDate','buildUpcomingLiveMetaParts','buildLiveResultMetaParts','resolveLiveDrawDateTime',
               'buildLiveCardMetaParts','getDrawPrizeAmount','formatDrawPrizeAmount','renderLiveNumberToken',
               'renderLiveInlineResultLine','renderLiveCardMainLines','updateLiveResultsCountdownText','renderLiveResultsBoard')
        for name in names:code+=js_function(source,name)+'\n'
        code+=js_function(core,'getLiveResultSignature')
        script='''
const TYPES={LOTO_5_35:{hasSpecial:true},LOTO_6_45:{},LOTO_6_55:{hasSpecial:true},KENO:{},MAX_3D:{threeDigit:true},MAX_3D_PRO:{threeDigit:true}};
const LIVE_RESULT_TYPES=Object.keys(TYPES).map(key=>({key,label:key==='LOTO_6_45'?'Mega_6/45':key}));
const liveSingleRefreshBusy=new Set(),IS_LOCAL_MODE=false;
let currentUser=null,now=new Date('2026-10-23T14:27:50+07:00');
const getSyncedNowDate=()=>new Date(now);
const getLiveResultsBoardSignature=()=>JSON.stringify(liveResultsState);
const getLiveUpdateBadge=()=>({code:'success',label:'Hoàn tất'});
const liveUpdateBadgeClass=()=>'ok';
const formatPredictNumber=(n,type)=>String(n).padStart(TYPES[type]?.threeDigit?3:2,'0');
const escapeHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const api=()=>{throw Error('Unexpected network request');};
let liveResultsState={
 LOTO_6_45:{key:'LOTO_6_45',ky:'1578',date:'21/10/2026',time:'',main:[4,10,14,22,25,44],jackpot:31281381500,prizeHit:'Jackpot'},
 LOTO_6_55:{key:'LOTO_6_55',ky:'1300',date:'22/10/2026',time:'18:00',main:[1,10,20,30,40,50],special:55,jackpot1:35000000000,jackpot2:4000000000,prizeHit:'Jackpot 2'},
 LOTO_5_35:{key:'LOTO_5_35',ky:'800',date:'23/10/2026',time:'13:00',main:[1,5,10,20,30],special:2,specialPrize:7000000000},
 KENO:{key:'KENO',ky:'300000',date:'23/10/2026',time:'14:24',main:Array.from({length:20},(_,i)=>i+1)},
 MAX_3D:{key:'MAX_3D',ky:'1500',date:'21/10/2026',time:'',displayLines:['Đặc biệt: 481 094','Giải nhất: 934 612 794 955','Giải nhì: 272 630 812 929 802 475','Giải ba: 690 649 208 272 060 022 854 480']},
 MAX_3D_PRO:{key:'MAX_3D_PRO',ky:'900',date:'22/10/2026',time:'',displayLines:['Đặc biệt: 481 094','Giải nhất: 934 612 794 955','Giải nhì: 272 630 812 929 802 475','Giải ba: 690 649 208 272 060 022 854 480']}
};
for(const item of Object.values(liveResultsState))if(item.main)item.displayLines=[item.main.map(n=>String(n).padStart(2,'0')).join(' ')+(TYPES[item.key].hasSpecial?' | '+String(item.special).padStart(2,'0'):'')];
window.identityErrors=[];addEventListener('error',e=>identityErrors.push(e.message));addEventListener('unhandledrejection',e=>identityErrors.push(String(e.reason)));
''' + code + '\nrenderLiveResultsBoard({force:true});'
        styles=''.join(f'<link rel="stylesheet" href="{(ROOT/"frontend"/name).as_uri()}">' for name in ('vietlott-web.css','vietlott-web-extra.css'))
        with tempfile.TemporaryDirectory(prefix='live-identity-',dir=ROOT/'runtime') as folder:
            work=Path(folder);page=work/'fixture.html'
            page.write_text('<!doctype html><meta charset="utf-8">'+styles+'<section id="liveBoardSection" class="live-board"><div id="liveResultGrid" class="live-result-grid"></div></section><script>'+script+'</script>',encoding='utf-8')
            browser=Browser(CHROME,work/'profile')
            def text(selector):return browser.value('document.querySelector('+json.dumps(selector)+').textContent')
            mega='[data-live-type=LOTO_6_45]'
            try:
                browser.call('Page.enable',page=True)
                browser.call('Emulation.setTimezoneOverride',dict(timezoneId='Asia/Ho_Chi_Minh'),page=True)
                browser.call('Page.navigate',dict(url=page.as_uri()),page=True)
                for _ in range(200):
                    if browser.value("document.querySelectorAll('.live-card').length===6"):break
                    time.sleep(.03)
                self.assertEqual(browser.value('identityErrors'),[])
                header=text(mega+' .live-card-result-label')
                self.assertEqual(header,'Kết quả · Kỳ #1578 • T4 21/10 • 18:00')
                self.assertEqual(text(mega+' .live-card-meta'),'Kỳ #1579 • T6 23/10 • 18:00 • Còn 03:32:10')
                self.assertIn('12.000.000.000 VNĐ',text(mega+' .live-card-amounts'))
                self.assertIn('Về mốc khởi điểm',text(mega+' .live-card-amounts'))
                self.assertEqual(browser.value('liveResultsState.LOTO_6_45.jackpot'),31281381500)
                self.assertEqual(browser.value('formatDrawPrizeAmount(liveResultsState.LOTO_6_45,"jackpot")'),'31.281.381.500 VNĐ')
                self.assertIn('35.000.000.000 VNĐ',text('[data-live-type=LOTO_6_55] .live-card-amounts'))
                self.assertIn('3.000.000.000 VNĐ',text('[data-live-type=LOTO_6_55] .live-card-amounts'))
                for marker,one,two in [('Jackpot 1',30000000000,None),('Jackpot 2',None,3000000000),('Jackpot 1, 2',30000000000,3000000000),('',None,None),('unknown',None,None)]:
                    self.assertEqual(browser.value('getLivePrizeReset("LOTO_6_55",{prizeHit:'+json.dumps(marker)+'},"jackpot1")'),one)
                    self.assertEqual(browser.value('getLivePrizeReset("LOTO_6_55",{prizeHit:'+json.dumps(marker)+'},"jackpot2")'),two)
                for marker in ('ĐB','Chia Giải'):
                    self.assertEqual(browser.value('getLivePrizeReset("LOTO_5_35",{prizeHit:'+json.dumps(marker)+'},"specialPrize")'),6000000000)
                for winners,expected in [(2,12000000000),(0,None),(-1,None),('1',None),(None,None)]:
                    self.assertEqual(browser.value('getLivePrizeReset("LOTO_6_45",{prizeWinnerCounts:{jackpot:'+json.dumps(winners)+'}},"jackpot")'),expected)
                self.assertTrue(browser.value('getLiveResultSignature(liveResultsState.LOTO_6_45)!==getLiveResultSignature({...liveResultsState.LOTO_6_45,prizeWinnerCounts:{jackpot:1}})'))
                self.assertEqual(browser.value("[...document.querySelectorAll('[data-live-type=LOTO_6_45] .live-card-number')].map(n=>n.textContent)"),['04','10','14','22','25','44'])
                for type in ('LOTO_5_35','LOTO_6_45','LOTO_6_55','KENO','MAX_3D','MAX_3D_PRO'):
                    self.assertNotIn('Còn',text(f'[data-live-type={type}] .live-card-result-label'))
                    self.assertIn('Kỳ #',text(f'[data-live-type={type}] .live-card-meta'))
                browser.value("window.originalBall=document.querySelector('[data-live-type=LOTO_6_45] .live-card-number');now=new Date('2026-10-23T18:00:00+07:00');updateLiveResultsCountdownText(now)")
                self.assertEqual(text(mega+' .live-card-result-label'),header)
                self.assertIn('#1579 • T6 23/10 • 18:00 • Đang chờ kết quả',text(mega+' .live-card-meta'))
                self.assertTrue(browser.value('originalBall.isConnected'))
                browser.value("now=new Date('2026-10-24T00:00:00+07:00');updateLiveResultsCountdownText(now)")
                self.assertEqual(text(mega+' .live-card-result-label'),header)
                self.assertIn('#1579 • T6 23/10',text(mega+' .live-card-meta'))
                # A cached old draw keeps its own identity after restore and render.
                browser.value('liveResultsState=JSON.parse(JSON.stringify(liveResultsState));renderLiveResultsBoard({force:true})')
                self.assertEqual(text(mega+' .live-card-result-label'),header)
                browser.value("liveResultsState.LOTO_6_45={...liveResultsState.LOTO_6_45,ky:'1579',date:'23/10/2026',main:[1,2,3,4,5,6],displayLines:['01 02 03 04 05 06'],jackpot:12500000000,prizeHit:''};renderLiveResultsBoard({force:true,onlyType:'LOTO_6_45'})")
                self.assertEqual(text(mega+' .live-card-result-label'),'Kết quả · Kỳ #1579 • T6 23/10 • 18:00')
                self.assertIn('#1580 • CN 25/10',text(mega+' .live-card-meta'))
                self.assertIn('12.500.000.000 VNĐ',text(mega+' .live-card-amounts'))
                self.assertNotIn('Về mốc khởi điểm',text(mega+' .live-card-amounts'))
                # Without a dated/time-qualified result, show a schedule without guessing an ID.
                for item in ('null',"{ky:'1579',date:'invalid'}","{ky:'800',date:'23/10/2026',time:''}"):
                    type='LOTO_5_35' if '800' in item else 'LOTO_6_45'
                    parts=browser.value(f'buildUpcomingLiveMetaParts("{type}",{item},now)')
                    self.assertEqual(parts[0],'Lịch quay tiếp theo')
                browser.value("now=new Date('2027-01-01T12:00:00+07:00');liveResultsState.LOTO_6_45={...liveResultsState.LOTO_6_45,ky:'1608',date:'30/12/2026'};renderLiveResultsBoard({force:true})")
                self.assertIn('#1608 • T4 30/12',text(mega+' .live-card-result-label'))
                self.assertIn('#1609 • T6 01/01',text(mega+' .live-card-meta'))
                # Restore the reported case for visual verification.
                browser.value("now=new Date('2026-10-23T14:27:50+07:00');liveResultsState.LOTO_6_45={key:'LOTO_6_45',ky:'1578',date:'21/10/2026',time:'',main:[4,10,14,22,25,44],displayLines:['04 10 14 22 25 44'],jackpot:31281381500,prizeHit:'Jackpot'};renderLiveResultsBoard({force:true})")
                images=ROOT/'Bin/session_1_latest/live_jackpot_reset_images';images.mkdir(exist_ok=True)
                for width in (320,390,768,1440):
                    browser.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False),page=True)
                    for light in (False,True):
                        browser.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})');time.sleep(.3)
                        self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+1'))
                        self.assertEqual(text(mega+' .live-card-result-label'),header)
                        if (width,light) in ((390,True),(1440,False)):
                            shot=browser.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True),page=True)
                            (images/f'live_{width}.png').write_bytes(base64.b64decode(shot['data']))
                browser.value('delete liveResultsState.LOTO_6_45;renderLiveResultsBoard({force:true})')
                self.assertEqual(browser.value("document.querySelectorAll('[data-live-type=LOTO_6_45] .live-card-number').length"),0)
                self.assertIn('Chưa có kết quả',text(mega))
                self.assertTrue(text(mega+' .live-card-meta').startswith('Lịch quay tiếp theo'))
                self.assertEqual(browser.value('identityErrors'),[])
            finally:browser.close()
