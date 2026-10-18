"""Same-draw, conditional sharing estimates with canonical counts and no source writes."""
import base64,json,time,unittest,hashlib
from pathlib import Path
from tests.test_effectiveness_web import EffectivenessWebTests as Bridge
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT,CHROME
from backend import live_results as lr

class PrizeSharingEstimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.t=Bridge;cls.t.setUpClass()
    @classmethod
    def tearDownClass(cls):cls.t.tearDownClass()

    def test_same_draw_math_live_updates_missing_counts_and_account_isolation(self):
        t=self.t;folder=t.work/'data/canonical';folder.mkdir(parents=True,exist_ok=True)
        (t.work/'backend/live_results.py').write_text("import json;print(json.dumps({'ok':True,'results':[],'errors':[]}))\n",encoding='utf-8')
        def source(ky,pool,counts):
            result=lr.build_numeric_result(lr.LIVE_TYPES['LOTO_5_35'],str(ky),'15/10/2026','21:00',[1,2,3,4,5,6],'https://www.minhchinh.com/fixture')
            result['specialPrize']=pool;result['prizeWinnerCounts']=counts
            row=lr.result_to_csv_row(result)
            path=folder/'loto_5_35_all_day.csv'
            lr.write_csv_rows(path,{str(ky):row},type_key='LOTO_5_35')
            path.with_suffix('.meta.json').write_text(json.dumps({'prizeWinners':lr.build_prize_winner_meta('LOTO_5_35',{str(ky):row})},ensure_ascii=False),encoding='utf-8')
            return path
        counts=dict(specialPrize=0,first=2,second=4,third=10,fourth=20,fifth=100,consolation=400)
        path=source(947,18000000000,counts)
        b=Browser(CHROME,t.work/'prize-share-profile')
        def wait(expr,seconds=15):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                if b.value(expr):return
                time.sleep(.05)
            self.fail('Timeout '+expr+' state='+str(b.value('({error:window.shareErrors,auth:typeof currentUser!=="undefined"?currentUser:null,context:document.querySelector("[data-prize-share-context]")?.textContent})')))
        def update(ky,pool,newcounts):
            source(ky,pool,newcounts)
            b.value('renderPrizePanel({refreshSharing:true})')
            wait(f'!lotto535SharingState.loading && lotto535SharingState.row?.ky==="{ky}"')
        try:
            b.call('Network.enable',page=True)
            cookie=t.admin.split(';')[0].split('=',1)[1]
            b.call('Network.setCookie',{'name':'LOTTO_AUTH','value':cookie,'url':t.url},page=True)
            b.call('Page.navigate',{'url':t.url+'/'},page=True)
            wait('typeof renderPrizePanel==="function" && typeof currentUser!=="undefined" && currentUser==="owner_fixture"')
            b.value('window.shareErrors=[];window.addEventListener("error",e=>shareErrors.push(e.message));document.getElementById("prizeType").value="LOTO_5_35";renderPrizePanel({refreshSharing:true})')
            wait('!lotto535SharingState.loading && lotto535SharingState.row?.ky==="947"')
            self.assertIn('≈ 3.010.000.000 ₫/vé',b.value('document.querySelector("[data-prize-share-tier=first]").textContent'))
            self.assertIn('≈ 755.000.000 ₫/vé',b.value('document.querySelector("[data-prize-share-tier=second]").textContent'))
            self.assertIn('Kỳ 947',b.value('document.querySelector("[data-prize-share-context]").textContent'))
            self.assertIn('18.000.000.000',b.value('document.querySelector("[data-prize-share-context]").textContent'))
            self.assertNotIn('4 tỷ ÷ SL',b.value('document.getElementById("prizeOut").textContent'))
            # Pure edge cases use the shipped calculator; booleans/negative/unknown are not zero.
            cases=[
              ({'pool':12000000000,'counts':counts},'below'),
              ({'pool':12000000001,'counts':counts},'estimate'),
              ({'pool':18000000000,'counts':{**counts,'specialPrize':1}},'jackpot'),
              ({'pool':18000000000,'counts':{**counts,'first':None}},'waiting'),
              ({'pool':18000000000,'counts':{**counts,'first':True}},'waiting'),
              ({'pool':18000000000,'counts':{**counts,'first':-1}},'waiting'),
              ({'pool':18000000000,'counts':{}},'waiting'),
            ]
            for data,status in cases:
                expression='getLotto535SharingEstimate({specialPrize:'+str(data['pool'])+',prizeWinnerCounts:'+json.dumps(data['counts'])+'}).status'
                self.assertEqual(b.value(expression),status)
            # Empty first tier: 2/6 gets divided equally among the four occupied tiers.
            update(948,18000000000,{**counts,'first':0})
            self.assertEqual(b.value('document.querySelector("[data-prize-share-tier=first]").textContent'),'0 vé trúng')
            self.assertIn('≈ 1.130.000.000 ₫/vé',b.value('document.querySelector("[data-prize-share-tier=second]").textContent'))
            # Missing tier count blocks all estimates because redistribution is unknown.
            update(949,18000000000,{**counts,'third':None})
            self.assertNotIn('≈',b.value('document.querySelector(".prize-table-lotto-535").textContent'))
            self.assertIn('Chờ đủ số vé',b.value('document.querySelector("[data-prize-share-context]").textContent'))
            update(950,12000000000,counts)
            self.assertNotIn('≈',b.value('document.querySelector(".prize-table-lotto-535").textContent'))
            update(951,18000000000,{**counts,'specialPrize':1})
            self.assertIn('Có vé trúng Độc Đắc',b.value('document.querySelector("[data-prize-share-context]").textContent'))
            # A newer canonical draw refreshes automatically through the live update hook.
            source(952,24000000000,counts)
            b.value('mergeLiveResultIntoState({key:"LOTO_5_35",ky:"952",main:[1,2,3,4,5],special:6,date:"15/10/2026",time:"21:00",specialPrize:24000000000})')
            wait('!lotto535SharingState.loading && lotto535SharingState.row?.ky==="952"')
            self.assertIn('≈ 4.010.000.000 ₫/vé',b.value('document.querySelector("[data-prize-share-tier=first]").textContent'))
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in folder.iterdir()if p.is_file()}
            artifacts=ROOT/'Bin/session_1_latest/prize_sharing_estimate_images';artifacts.mkdir(exist_ok=True)
            layouts=[]
            for width in (320,390,760,1280,1440):
                b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False},page=True)
                for light in (False,True):
                    b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                    bounds=b.value("(()=>{const card=document.getElementById('prizeOut').closest('.prize-card').getBoundingClientRect(),wrap=document.querySelector('.prize-table-lotto-535').closest('.prize-table-wrap'),r=wrap.getBoundingClientRect();return {inside:card.left>=0&&card.right<=innerWidth+1,tableInside:r.left>=card.left&&r.right<=card.right+1,scrollable:getComputedStyle(wrap).overflowX==='auto'}})()")
                    self.assertTrue(all(bounds.values()),(width,light,bounds))
                    self.assertEqual(b.value('document.querySelectorAll("[data-prize-share-tier] .prize-share-estimate").length'),5)
                    layouts.append({'width':width,'light':light,'prizeCardInsideViewport':True,'tableScrollContained':True,'estimates':5})
                    if (width,light)in ((1440,False),(390,True)):
                        b.value("(()=>{const card=document.getElementById('prizeOut').closest('.prize-card');scrollTo(0,card.getBoundingClientRect().top+scrollY-120);const wrap=card.querySelector('.prize-table-wrap');wrap.scrollLeft=innerWidth<600?wrap.scrollWidth:0})()")
                        shot=b.call('Page.captureScreenshot',{'format':'png'},page=True);(artifacts/f'share_estimate_{width}_{light}.png').write_bytes(base64.b64decode(shot['data']))
            # Failed requests do not keep old estimates, and logout discards a late response.
            b.value('window.shareOriginalApi=api;api=async path=>{if(path.includes("/api/live-history"))throw new Error("fixture unavailable");return shareOriginalApi(path)};renderPrizePanel({refreshSharing:true})')
            wait('!lotto535SharingState.loading && !!lotto535SharingState.error')
            self.assertFalse(b.value('!!document.querySelector(".prize-share-estimate")'))
            b.value('api=shareOriginalApi;window.shareResolve=null;api=path=>path.includes("/api/live-history")?new Promise(resolve=>shareResolve=resolve):shareOriginalApi(path);renderPrizePanel({refreshSharing:true})')
            wait('typeof shareResolve==="function"')
            b.value('window.dispatchEvent(new CustomEvent("dvlf:auth-changed",{detail:{authenticated:false}}));shareResolve({type:"LOTO_5_35",history:[{ky:"953",main:[1,2,3,4,5],special:6,specialPrize:30000000000,prizeWinnerCounts:{specialPrize:0,first:1,second:1,third:1,fourth:1,fifth:1}}]})')
            time.sleep(.1)
            self.assertTrue(b.value('lotto535SharingState.row===null'))
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in folder.iterdir()if p.is_file()})
            self.assertEqual(b.value('shareErrors'),[])
            (ROOT/'Bin/session_1_latest/prize_sharing_estimate_verification.json').write_text(json.dumps({'layouts':layouts,'canonicalUnchanged':True,'sameDraw':True,'unknownAndZeroHandled':True,'thresholdStrictlyAbove12Billion':True,'redistributedEmptyTiers':True,'lateAuthResponseIgnored':True},indent=2),encoding='utf-8')
        finally:b.close()

if __name__=='__main__':unittest.main()
