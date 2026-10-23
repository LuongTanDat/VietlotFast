"""Authenticated chart endpoint and real navigation on an isolated database."""
import base64
import json
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from tests.test_account_balances import AccountBalanceTests
from tests.test_account_statistics import AccountStatisticsTests
from tests.test_prize_web import ROOT, CHROME
from tests.browser_cdp import Browser


class AccountStatisticsWebTests(AccountBalanceTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        shutil.copytree(ROOT/'ai', cls.work/'ai', ignore=shutil.ignore_patterns('__pycache__','models','standalone_predictors','predictors'))
        (cls.work/'backend').mkdir(exist_ok=True)
        shutil.copy2(ROOT/'backend/file_guard.py',cls.work/'backend/file_guard.py')

    def test_statistics_permissions_filters_navigation_and_layout(self):
        fixture=AccountStatisticsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        shutil.copy2(fixture.tracking,self.work/'runtime/tracking_ledger.db')
        (self.work/'runtime/tracking-storage.json').write_text('{"version":1,"mode":"dedicated"}',encoding='utf-8')
        personal_id = 'aa000000-0000-4000-8000-000000000001'
        private = self.work/'runtime/personal_tracking'/personal_id/'tracking.db'
        private.parent.mkdir(parents=True)
        shutil.copy2(fixture.tracking, private)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db, db:
            db.execute('INSERT INTO personal_tracking_accounts VALUES(?,?)', (personal_id,'owner_fixture'))
            for index,(user,status,environment,amount) in enumerate([
                ('owner_fixture','PAID','production',100000),('member_fixture','PAID','production',20000),
                ('owner_fixture','TEST_PAID','sandbox',900000),('owner_fixture','PENDING','production',900000)]):
                db.execute('INSERT INTO payment_orders(id,username,request_id,environment,tmn_code,amount,base_credit,bonus_credit,credit,status,created_at,expires_at,paid_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (f'chart{index}',user,f'request-chart{index}',environment,'TEST',amount,amount,0,amount,status,'2026-10-18T01:00:00Z','2026-10-18T02:00:00Z','2026-10-18T01:30:00Z' if status=='PAID' else ''))
        query='/api/account/statistics?type=LOTO_5_35&method=web&period=all&date=2026-10-18&level=10'
        self.assertEqual(self.request(query)[0],401)
        self.assertEqual(self.request(query,{},self.admin)[0],405)
        for invalid in (query.replace('period=all','period=bad'), query.replace('2026-10-18','2026-02-31'),query.replace('level=10','level=11')):
            self.assertEqual(self.request(invalid,cookie=self.admin)[0],400)
        code,data,_=self.request(query,cookie=self.admin)
        self.assertEqual(code,200,data)
        self.assertEqual(data['totals']['deposited'],100000)
        self.assertEqual(data['totals']['bought'],60)
        self.assertEqual(data['methodDistribution'],[{'method':name,'tickets':60} for name in ('web','random','bayesian','ewma')])
        self.assertEqual(data['methodWinDistribution'],[{'method':name,'tickets':2 if name=='random' else 4,'scored':40,'unknownTickets':0} for name in ('web','random','bayesian','ewma')])
        self.assertEqual(data['methodPurchaseOutcomes'],[{'method':name,'tickets':60,'won':2 if name=='random' else 4,'scored':40,'unknownTickets':0,'pending':20} for name in ('web','random','bayesian','ewma')])
        self.assertEqual(data['totals']['reward'],2000000)
        code,day_data,_=self.request(query.replace('period=all','period=day'),cookie=self.admin)
        self.assertEqual(code,200,day_data)
        self.assertEqual(day_data['comparison']['from'],'2026-10-17')
        self.assertEqual(day_data['comparison']['changes']['deposited'],100000)
        self.assertEqual(day_data['comparison']['changes']['spent'],400000)
        self.assertEqual(len(day_data['comparison']['series']),24)
        code,data,_=self.request(query.replace('method=web','method=all'),cookie=self.admin)
        self.assertEqual(code,200,data)
        self.assertEqual(data['totals']['deposited'],100000)
        self.assertEqual(data['totals']['bought'],240)
        self.assertEqual(data['totals']['reward'],26000000)
        code,data,_=self.request(query.replace('type=LOTO_5_35','type=all').replace('method=web','method=all'),cookie=self.admin)
        self.assertEqual(code,200,data)
        self.assertEqual(data['type'],'all')
        self.assertEqual(data['totals']['deposited'],100000)
        self.assertEqual(data['totals']['bought'],240)
        code,data,_=self.request(query+'&owner=owner_fixture',cookie=self.member)
        self.assertEqual(code,200,data)
        self.assertEqual(data['owner'],'member_fixture')
        self.assertEqual(data['totals']['deposited'],20000)
        self.assertEqual(data['totals']['bought'],0)
        browser=Browser(CHROME,self.work/'chart-ui')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression): return
                time.sleep(.05)
            self.fail('Timeout: '+expression+'\n'+str(browser.value("document.getElementById('accountStatsStatus')?.textContent")))
        try:
            browser.call('Page.enable',page=True)
            browser.call('Network.enable',page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"""window.chartErrors=[];addEventListener('error',e=>chartErrors.push(e.message));addEventListener('unhandledrejection',e=>chartErrors.push(String(e.reason)));
              window.chartRotations=new Set();const originalInterval=window.setInterval,originalClearInterval=window.clearInterval;
              window.setInterval=(callback,delay,...args)=>{const id=originalInterval(callback,delay,...args);if(delay===10000 && String(callback).includes('showSlide')) chartRotations.add(id);return id;};
              window.clearInterval=id=>{chartRotations.delete(id);originalClearInterval(id);};"""},page=True)
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.admin.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',{'url':self.url+'/'},page=True)
            wait("!!window.VietlottAccountStats && currentUser==='owner_fixture'")
            self.assertTrue(browser.value("!!document.querySelector('#sideMenu #accountStatsMenuBtn') && !document.querySelector('#sideMenu #openAccountBtn')"))
            browser.value("document.getElementById('accountStatsMenuBtn').click()")
            wait("location.pathname==='/bieu-do' && document.querySelectorAll('#accountStatsCards article').length===5")
            self.assertEqual(browser.value("document.getElementById('accountStatsMethod').value"),'all')
            self.assertEqual(browser.value("document.getElementById('accountStatsGame').value"),'all')
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsCards article strong')[3].textContent"),'240')
            self.assertTrue(browser.value("document.getElementById('accountStatsStatus').hidden && !document.getElementById('accountStatsTicketCaption') && !document.getElementById('accountStatsMoneyCaption')"))
            browser.value("document.getElementById('accountStatsGame').value='LOTO_5_35';document.getElementById('accountStatsGame').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('#accountStatsCards article').length===5 && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            browser.value("document.getElementById('accountStatsGame').value='KENO';document.getElementById('accountStatsGame').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('#accountStatsCards article strong')[3]?.textContent==='0'")
            self.assertTrue(browser.value("document.getElementById('accountStatsMethodChart').textContent.includes('Chưa có vé') && !document.querySelector('#accountStatsMethodChart svg')"))
            self.assertFalse(browser.value("document.getElementById('accountStatsLevel').closest('label').hidden"))
            browser.value("document.getElementById('accountStatsGame').value='all';document.getElementById('accountStatsGame').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('#accountStatsCards article strong')[3]?.textContent==='240'")
            self.assertTrue(browser.value("document.getElementById('accountStatsLevel').closest('label').hidden"))
            browser.value("document.getElementById('accountStatsMethod').value='web';document.getElementById('accountStatsMethod').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('#accountStatsCards article strong')[3]?.textContent==='60'")
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-method-legend li').length"),4)
            self.assertEqual(browser.value("document.querySelector('.account-stats-donut-total').textContent"),'240')
            self.assertEqual(browser.value("document.querySelector('.account-stats-donut-won').textContent"),'14')
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMethodChart [data-ring=tickets]').length"),1)
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMethodChart [data-kind=count]').length"),4)
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMethodChart [data-kind=won]').length"),4)
            browser.value("document.getElementById('accountStatsMethod').value='all';document.getElementById('accountStatsMethod').dispatchEvent(new Event('change'))")
            wait("document.querySelectorAll('#accountStatsCards article strong')[3]?.textContent==='240'")
            self.assertTrue(browser.value("document.getElementById('mainContentGrid').hidden && !document.getElementById('accountStatsSection').hidden"))
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart .account-stats-lines path').length"),3)
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-change').length"),0)
            # Manual switching wraps both directions and draws at the actual visible width.
            browser.value("document.getElementById('accountStatsPrevious').click()")
            self.assertTrue(browser.value("document.getElementById('accountStatsMoneyPanel').hidden && !document.getElementById('accountStatsTicketPanel').hidden"))
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChart .account-stats-lines path').length"),2)
            browser.value("document.getElementById('accountStatsNext').click()")
            self.assertFalse(browser.value("document.getElementById('accountStatsMoneyPanel').hidden"))
            self.assertEqual(browser.value('chartRotations.size'),1)
            # Observe one real 10-second rotation; a paused carousel must then stay put.
            time.sleep(10.2)
            self.assertFalse(browser.value("document.getElementById('accountStatsTicketPanel').hidden"))
            browser.value("document.getElementById('accountStatsRotation').click();document.getElementById('accountStatsNext').click()")
            self.assertEqual(browser.value("document.getElementById('accountStatsRotation').getAttribute('aria-pressed')"),'true')
            self.assertEqual(browser.value('chartRotations.size'),0)
            self.assertFalse(browser.value("document.getElementById('accountStatsMoneyPanel').hidden"))
            browser.value("document.getElementById('accountStatsDate').value='2026-10-18'")
            for period,count in [('day',24),('week',7),('month',31),('year',12)]:
                browser.value(f"document.querySelector('[data-account-period={period}]').click()")
                wait(f"document.querySelectorAll('#accountStatsRows tr').length==={count} && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
                self.assertEqual(browser.value("document.querySelectorAll('.account-stats-change').length"),5)
                self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart path[data-line]').length"),5)
                self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart path[stroke-dasharray]').length"),2)
                self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChartLegend .is-previous').length"),2)
                if period=='day':
                    self.assertEqual(browser.value("document.querySelector('#accountStatsMoneyChart circle[data-metric=previousSpent]').dataset.key"),'2026-10-17T00:00')
                    browser.value("document.querySelector('[data-account-line=previousSpent]').click()")
                    self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart path[data-line]').length"),4)
                    browser.value("document.querySelector('[data-account-line=previousSpent]').click();document.activeElement.blur()")
                browser.value("document.getElementById('accountStatsNext').click()")
                self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChart path[data-line]').length"),4)
                self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChart path[stroke-dasharray]').length"),2)
                self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChartLegend .is-previous').length"),2)
                if period=='day':
                    self.assertEqual(browser.value("document.querySelector('#accountStatsTicketChart circle[data-metric=previousBought]').dataset.key"),'2026-10-17T00:00')
                    browser.value("document.querySelector('[data-account-line=previousWon]').click()")
                    self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChart path[data-line]').length"),3)
                    browser.value("document.querySelector('[data-account-line=previousWon]').click();document.activeElement.blur()")
                browser.value("document.getElementById('accountStatsNext').click()")
            browser.value("document.getElementById('accountStatsDate').value='2026-10-17';document.querySelector('[data-account-period=day]').click()")
            wait("document.querySelectorAll('.account-stats-kpi')[1]?.querySelector('.account-stats-change b')?.textContent==='−800.000 ₫'")
            self.assertEqual(browser.value("getComputedStyle(document.querySelectorAll('.account-stats-kpi')[1].querySelector('.account-stats-change')).color"),'rgb(251, 113, 133)')
            browser.value("document.getElementById('accountStatsDate').value='2026-10-18';document.querySelector('[data-account-period=day]').click()")
            wait("document.querySelectorAll('.account-stats-kpi')[1]?.querySelector('.account-stats-change b')?.textContent==='+1.600.000 ₫'")
            self.assertEqual(browser.value("getComputedStyle(document.querySelectorAll('.account-stats-kpi')[1].querySelector('.account-stats-change')).color"),'rgb(52, 211, 153)')
            browser.value("document.querySelector('[data-account-period=month]').click()")
            wait("document.querySelectorAll('#accountStatsRows tr').length===31")
            # Read-only browser fixture: exercise the long amounts in the user's
            # screenshot and a single monthly point without changing any DB.
            browser.value("""window.statisticsOriginalFetch=window.fetch;
                window.fetch=async (...args)=>{
                  const response=await statisticsOriginalFetch(...args);
                  if(!String(args[0]).startsWith('/api/account/statistics?')) return response;
                  const report=await response.json();
                  const row=report.series[0];
                  Object.assign(row,{spent:2073201920000,reward:1031725371500,bought:207320192,won:33439437,
                    scored:195378568,pending:11941624,incomplete:79});
                  Object.assign(report.totals,row);
                  if(report.period==='week' && report.anchor==='2026-10-20'){
                    report.series.forEach((bucket,i)=>bucket.future=i>=2);
                    Object.assign(report.series[1],{scored:20,won:0,reward:0,incomplete:0,unknownTickets:0,drawPending:0});
                    Object.assign(report.series[2],{scored:0,won:0,reward:0,drawPending:40});
                    if(window.statisticsChartMode==='positive-partial') Object.assign(report.series[1],{scored:21991200,won:3903978,reward:117400660000,incomplete:2});
                    if(window.statisticsChartMode==='unknown') Object.assign(report.series[1],{won:0,reward:0,incomplete:1,unknownTickets:10});
                    if(window.statisticsChartMode==='awaiting') Object.assign(report.series[1],{won:0,reward:0,incomplete:0,unknownTickets:0,drawPending:40});
                  }
                  report.methodDistribution=[{method:'web',tickets:82928077},{method:'random',tickets:62196058},{method:'bayesian',tickets:41464038},{method:'ewma',tickets:20732019}];
                  report.methodWinDistribution=[{method:'web',tickets:3343944,unknownTickets:0},{method:'random',tickets:6687887,unknownTickets:0},{method:'bayesian',tickets:10031831,unknownTickets:0},{method:'ewma',tickets:13375775,unknownTickets:0}];
                  report.methodPurchaseOutcomes=report.methodDistribution.map((row,i)=>({...row,won:report.methodWinDistribution[i].tickets,unknownTickets:0,pending:0,scored:row.tickets}));
                  if(window.statisticsPieMode==='user-screenshot'){
                    report.methodDistribution.forEach(row=>row.tickets=65381848);
                    report.methodPurchaseOutcomes=report.methodDistribution.map((row,i)=>({...row,won:[10746556,10806262,10810426,10761015][i],unknownTickets:0,pending:0,scored:row.tickets}));
                  }
                  if(window.statisticsPieMode==='zero-wins') report.methodPurchaseOutcomes.forEach(row=>row.won=0);
                  if(window.statisticsPieMode==='zero-purchases'){
                    report.methodDistribution.forEach(row=>row.tickets=0);
                    report.methodPurchaseOutcomes.forEach(row=>Object.assign(row,{tickets:0,won:0,scored:0}));
                  }
                  if(window.statisticsPieMode==='unknown') report.methodPurchaseOutcomes[0].unknownTickets=7;
                  if(report.comparison){
                    report.comparison.estimated={reward:true};
                    report.comparison.totals.incomplete=2;
                    report.comparison.changes={deposited:0,spent:196496000000,reward:-24000000000,bought:19649600,won:0};
                    for(const key of Object.keys(report.comparison.changes))
                      report.comparison.totals[key]=report.totals[key]-report.comparison.changes[key];
                    if(report.period==='week'){
                      report.comparison.series.forEach(bucket=>Object.assign(bucket,{spent:0,reward:0,incomplete:0}));
                      report.comparison.series[0].spent=4500000000000;
                      report.comparison.series[1].reward=1500000000000;
                      report.comparison.series[0].bought=450000000;
                      Object.assign(report.comparison.series[1],{won:150000000,scored:450000000});
                      Object.assign(report.comparison.totals,{spent:4500000000000,reward:1500000000000,bought:450000000,won:150000000,scored:450000000});
                      report.comparison.changes.spent=report.totals.spent-report.comparison.totals.spent;
                      report.comparison.changes.reward=report.totals.reward-report.comparison.totals.reward;
                      report.comparison.changes.bought=report.totals.bought-report.comparison.totals.bought;
                      report.comparison.changes.won=report.totals.won-report.comparison.totals.won;
                    }
                  }
                  return new Response(JSON.stringify(report),{status:response.status,headers:{'Content-Type':'application/json'}});
                };
                document.querySelector('[data-account-period=month]').click();""")
            wait("document.querySelectorAll('#accountStatsCards article strong')[1]?.textContent==='2.073.201.920.000 ₫' && document.querySelectorAll('.account-stats-change').length===5")
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-change.is-flat').length"),2)
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-kpi')[2].querySelector('.account-stats-change b').textContent"),'−24.000.000.000 ₫ *')
            self.assertTrue(browser.value("(()=>{const e=document.querySelectorAll('.account-stats-kpi')[2].querySelector('.account-stats-change');return e.classList.contains('is-estimated') && e.classList.contains('is-down') && e.title.includes('Tạm tính theo tổng thưởng đã tính') && e.title.includes('79 / 2') && !e.textContent.includes('Chưa đủ dữ liệu')})()"))
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart circle[data-metric=previousSpent]').length"),30)
            self.assertEqual(browser.value("[...document.querySelectorAll('#accountStatsMoneyChart circle[data-metric=previousSpent]')].at(-1).dataset.key"),'2026-09-30')
            self.assertEqual(browser.value("[...document.querySelectorAll('#accountStatsMoneyChartLegend button')].map(e=>e.textContent)"),['Nạp','Vé','Thưởng','Vé trước','Thưởng trước'])
            self.assertTrue(browser.value("[...document.querySelectorAll('#accountStatsMoneyChartLegend button')].every(e=>e.title===e.getAttribute('aria-label') && e.title.length>=e.textContent.length)"))
            output=ROOT/'Bin/session_1_latest/account_statistics_compact_legend_images'
            output.mkdir(parents=True,exist_ok=True)
            for theme in ('dark','light'):
                browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                for width in (320,390,768,1000,1200,1440,1920):
                    browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1800,'deviceScaleFactor':1,'mobile':False},page=True)
                    wait("(()=>{const h=document.getElementById('accountStatsMoneyChart');return Math.abs(h.clientWidth-h.querySelector('svg').viewBox.baseVal.width)<1})()")
                    self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'),(theme,width))
                    self.assertTrue(browser.value("[...document.querySelectorAll('.account-stats-kpi > strong')].every(e=>e.scrollWidth<=e.clientWidth+1 && getComputedStyle(e).whiteSpace==='nowrap')"),(theme,width,'long amounts'))
                    self.assertTrue(browser.value("[...document.querySelectorAll('.account-stats-change b')].every(e=>e.scrollWidth<=e.clientWidth+1)"),(theme,width,'long differences'))
                    self.assertTrue(browser.value("[...document.querySelectorAll('.account-stats-toolbar input,.account-stats-toolbar select,.account-stats-periods')].filter(e=>e.getClientRects().length).every(e=>Math.abs(e.getBoundingClientRect().height-40)<1)"),(theme,width,'control height'))
                    if width>=1200:
                        self.assertTrue(browser.value("(()=>{const h=document.querySelector('#accountStatsMoneyPanel > header'),a=h.querySelector('h2').getBoundingClientRect(),b=h.querySelector('.account-stats-legend').getBoundingClientRect();return Math.abs(a.top+a.height/2-b.top-b.height/2)<1})()"),(theme,width,'inline legends'))
                        self.assertTrue(browser.value("(()=>{const [a,b]=document.querySelectorAll('.account-stats-chart-card');const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return Math.abs(x.width-y.width)<1 && Math.abs(x.top-y.top)<1 && Math.abs(x.height-y.height)<1})()"),(theme,width,'equal charts'))
                        self.assertTrue(browser.value("(()=>{const groups=[...document.querySelectorAll('#accountStatsMoneyChartLegend .account-stats-legend-group')].map(e=>e.getBoundingClientRect());return Math.abs(groups[0].top-groups[1].top)<1})()"),(theme,width,'compact legends one desktop row'))
                    self.assertTrue(browser.value("[...document.querySelectorAll('#accountStatsMoneyChartLegend button')].every(e=>Math.abs(e.getBoundingClientRect().height-24)<1 && e.scrollWidth<=e.clientWidth+1)"),(theme,width,'compact buttons fit'))
                    self.assertTrue(browser.value("(()=>{const buttons=[...document.querySelectorAll('#accountStatsMoneyChartLegend .is-previous')].map(e=>e.getBoundingClientRect());return Math.abs(buttons[0].top-buttons[1].top)<1})()"),(theme,width,'previous pair stays together'))
                    self.assertTrue(browser.value("[...document.querySelectorAll('.account-stats-method-legend li')].every(e=>e.scrollWidth<=e.clientWidth+1)"),(theme,width,'pie legend fits'))
                    self.assertEqual(browser.value("[...document.querySelectorAll('.account-stats-method-legend strong')].map(e=>e.textContent)"),['34,44%','1,39%','25,83%','2,78%','17,22%','4,17%','8,61%','5,56%'])
                    self.assertTrue(browser.value("(()=>{const sectors=[...document.querySelectorAll('[data-ring=tickets] .account-stats-pie-sector')];return sectors.length===8 && new Set(sectors.map(e=>e.getAttribute('stroke'))).size===8 && new Set(sectors.map(e=>e.getAttribute('r'))).size===1 && Math.abs(sectors.reduce((sum,e)=>sum+parseFloat(e.getAttribute('stroke-dasharray')),0)-100)<1e-8})()"),(theme,width,'one ring eight colors'))
                    self.assertTrue(browser.value("[...document.querySelectorAll('.account-stats-method-legend li')].every(row=>['count','won'].every((kind,i)=>getComputedStyle(row.querySelectorAll('i')[i]).backgroundColor===getComputedStyle(document.querySelector('[data-ring=tickets] [data-method='+row.dataset.method+'][data-kind='+kind+']')).stroke))"),(theme,width,'eight legend swatches match sectors'))
                    if width in (390,1440):
                        clip=browser.value("(()=>{const r=document.getElementById('accountStatsSection').getBoundingClientRect();return {x:Math.max(0,r.left),y:Math.max(0,r.top+scrollY),width:r.width,height:r.height,scale:1}})()")
                        image=browser.call('Page.captureScreenshot',{'clip':clip,'captureBeyondViewport':True},page=True)
                        (output/f'fixture_statistics_{theme}_{width}.png').write_bytes(base64.b64decode(image['data']))
                        browser.value("document.querySelector('.account-stats-table').open=true;window.scrollBy(0,document.querySelector('.account-stats-table').getBoundingClientRect().top-160)")
                        self.assertEqual(browser.value("[...document.querySelectorAll('.account-stats-table thead th')].map(e=>e.textContent)"),['Thời gian','Tiền nạp (₫)','Tiền Vé (₫)','Tiền Thưởng (₫)','Vé mua','Vé trúng'])
                        for scroll_top in (0,47,113,99999):
                            browser.value(f"(()=>{{const e=document.querySelector('.account-stats-table-scroll');e.scrollTop={scroll_top};e.scrollLeft=e.scrollWidth;}})()")
                            wait("(()=>{const p=document.querySelector('.account-stats-table-scroll').getBoundingClientRect(),h=document.querySelector('.account-stats-table thead').getBoundingClientRect();return Math.abs(p.top-h.top)<1})()")
                            self.assertTrue(browser.value("(()=>{const p=document.querySelector('.account-stats-table-scroll').getBoundingClientRect();return [...document.querySelectorAll('.account-stats-table thead th')].filter(e=>{const r=e.getBoundingClientRect();return Math.min(r.right,p.right)-Math.max(r.left,p.left)>8}).every(e=>{const r=e.getBoundingClientRect(),x=(Math.max(r.left,p.left)+Math.min(r.right,p.right))/2,y=r.top+r.height/2;return document.elementFromPoint(x,y)===e})})()"),(theme,width,scroll_top,'header covers scrolled rows'))
                        browser.value("document.querySelector('.account-stats-table-scroll').scrollTop=71")
                        clip=browser.value("(()=>{const r=document.querySelector('.account-stats-table').getBoundingClientRect();return {x:Math.max(0,r.left),y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                        image=browser.call('Page.captureScreenshot',{'clip':clip,'captureBeyondViewport':True},page=True)
                        (output/f'detail_table_scrolled_{theme}_{width}.png').write_bytes(base64.b64decode(image['data']))
                        browser.value("document.querySelector('.account-stats-table').open=false;document.querySelector('.account-stats-table-scroll').scrollTop=0;window.scrollTo(0,0)")
            # Reproduce the missing 22/10 label: seven buckets previously got
            # only six desktop labels (or three mobile labels).
            browser.value("document.getElementById('accountStatsDate').value='2026-10-20';document.querySelector('[data-account-period=week]').click()")
            wait("document.querySelectorAll('#accountStatsMoneyChart .account-stats-axis text').length===7 && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            for width in (320,390,768,1440):
                browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1800,'deviceScaleFactor':1,'mobile':False},page=True)
                for host,next_host in [('accountStatsMoneyChart','accountStatsTicketChart'),('accountStatsTicketChart','accountStatsMoneyChart')]:
                    wait(f"(()=>{{const h=document.getElementById('{host}');return Math.abs(h.clientWidth-h.querySelector('svg').viewBox.baseVal.width)<1}})()")
                    self.assertEqual(browser.value(f"[...document.querySelectorAll('#{host} .account-stats-axis text')].map(e=>e.textContent)"),['19/10','20/10','21/10','22/10','23/10','24/10','25/10'])
                    if host=='accountStatsMoneyChart':
                        self.assertEqual(browser.value("[...document.querySelectorAll('#accountStatsMoneyChart circle[data-metric=previousSpent]')].map(e=>e.dataset.key)"),['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-17','2026-10-18'])
                        self.assertTrue(browser.value("Number(document.querySelector('#accountStatsMoneyChart circle[data-metric=previousSpent]').getAttribute('cy'))>=20"),(width,'higher previous peak fits shared scale'))
                        self.assertEqual(browser.value("[...document.querySelectorAll('#accountStatsMoneyChart .account-stats-grid text')].at(-1).textContent"),'5.000 tỷ')
                    else:
                        self.assertEqual(browser.value("[...document.querySelectorAll('#accountStatsTicketChart circle[data-metric=previousBought]')].map(e=>e.dataset.key)"),['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-17','2026-10-18'])
                        self.assertTrue(browser.value("Number(document.querySelector('#accountStatsTicketChart circle[data-metric=previousBought]').getAttribute('cy'))>=20"),(width,'higher previous ticket peak fits'))
                        self.assertEqual(browser.value("[...document.querySelectorAll('#accountStatsTicketChart .account-stats-grid text')].at(-1).textContent"),'500 tr')
                    self.assertTrue(browser.value(f"(()=>{{const labels=[...document.querySelectorAll('#{host} .account-stats-axis text')].map(e=>e.getBoundingClientRect());return labels.every((a,i)=>labels.every((b,j)=>i===j || a.right<=b.left || b.right<=a.left || a.bottom<=b.top || b.bottom<=a.top))}})()"),(width,host,'all seven labels fit'))
                    metric='reward' if host=='accountStatsMoneyChart' else 'won'
                    self.assertEqual(browser.value(f"document.querySelectorAll('#{host} circle[data-metric={metric}]').length"),7)
                    self.assertTrue(browser.value(f"[...document.querySelectorAll('#{host} circle[data-metric={metric}]')].some(e=>e.dataset.key==='2026-10-19')"),(width,metric,'known positive survives'))
                    self.assertTrue(browser.value(f"[...document.querySelectorAll('#{host} circle[data-metric={metric}]')].find(e=>e.dataset.key==='2026-10-20').querySelector('title').textContent.includes(': 0')"),(width,metric,'scored zero is real'))
                    self.assertEqual(browser.value(f"[...document.querySelectorAll('#{host} circle[data-metric={metric}]')].filter(e=>e.dataset.key>='2026-10-21').length"),5)
                    self.assertTrue(browser.value(f"[...document.querySelectorAll('#{host} .account-stats-lines path')].every(e=>(e.getAttribute('d').match(/M/g)||[]).length===1 && (e.getAttribute('d').match(/L/g)||[]).length===6)"),(width,metric,'zero points remain connected'))
                    self.assertTrue(browser.value(f"[...document.querySelectorAll('#{host} circle[data-metric]')].every(e=>getComputedStyle(e).stroke!=='rgb(251, 191, 36)')"),(width,metric,'no yellow markers'))
                    if metric=='reward':
                        self.assertTrue(browser.value("document.querySelector('#accountStatsMoneyChart circle[data-metric=reward] title').textContent.includes('Tạm tính')"))
                    if width in (320,1440):
                        clip=browser.value("(()=>{const r=document.getElementById('accountStatsCarousel').getBoundingClientRect();return {x:r.left,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                        image=browser.call('Page.captureScreenshot',{'clip':clip,'captureBeyondViewport':True},page=True)
                        (output/f'week_axis_{host}_{width}.png').write_bytes(base64.b64decode(image['data']))
                    browser.value("document.getElementById('accountStatsNext').click()")
                    wait(f"!document.getElementById('{next_host}').closest('.account-stats-panel').hidden")
            self.assertTrue(browser.value("[...document.querySelectorAll('#accountStatsRows tr')].filter(e=>e.querySelector('th').textContent>='2026-10-21').every(e=>[...e.querySelectorAll('td')].every(cell=>cell.textContent.startsWith('0')))"))
            browser.value("window.statisticsChartMode='positive-partial';document.getElementById('accountStatsRefresh').click()")
            wait("document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false' && [...document.querySelectorAll('#accountStatsMoneyChart circle[data-metric=reward]')].some(e=>e.dataset.key==='2026-10-20' && e.querySelector('title').textContent.includes('117.400.660.000'))")
            browser.call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1800,'deviceScaleFactor':1,'mobile':False},page=True)
            for host in ('accountStatsMoneyChart','accountStatsTicketChart'):
                wait(f"(()=>{{const h=document.getElementById('{host}');return Math.abs(h.clientWidth-h.querySelector('svg').viewBox.baseVal.width)<1}})()")
                metric='reward' if host=='accountStatsMoneyChart' else 'won'
                self.assertEqual(browser.value(f"document.querySelectorAll('#{host} circle[data-metric={metric}]').length"),7)
                clip=browser.value("(()=>{const r=document.getElementById('accountStatsCarousel').getBoundingClientRect();return {x:r.left,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
                image=browser.call('Page.captureScreenshot',{'clip':clip,'captureBeyondViewport':True},page=True)
                (output/f'positive_partial_{host}_1440.png').write_bytes(base64.b64decode(image['data']))
                browser.value("document.getElementById('accountStatsNext').click()")
            browser.value("window.statisticsChartMode='unknown';document.getElementById('accountStatsRefresh').click()")
            wait("document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false' && document.querySelectorAll('#accountStatsRows tr')[1]?.querySelectorAll('td')[2]?.textContent==='0 *'")
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart circle[data-metric=reward]').length"),7)
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsRows tr')[1].querySelectorAll('td')[4].textContent"),'0 *')
            browser.value("window.statisticsChartMode='awaiting';document.getElementById('accountStatsRefresh').click()")
            wait("document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false' && document.querySelectorAll('#accountStatsRows tr')[1]?.querySelectorAll('td')[2]?.querySelector('span')?.title.includes('Chờ chấm thêm 40')")
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsRows tr')[1].querySelectorAll('td')[2].textContent"),'0 *')
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsRows tr')[1].querySelectorAll('td')[4].textContent"),'0 *')
            browser.value("window.statisticsChartMode='';document.getElementById('accountStatsDate').value='2026-10-18';document.querySelector('[data-account-period=month]').click()")
            wait("document.querySelectorAll('#accountStatsRows tr').length===31 && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            browser.value("window.statisticsPieMode='user-screenshot';document.getElementById('accountStatsRefresh').click()")
            wait("document.querySelector('.account-stats-donut-total')?.textContent==='261.527.392' && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            self.assertEqual(browser.value("document.querySelector('.account-stats-method-legend li .account-stats-method-value:last-child strong').textContent"),'3,53%')
            self.assertAlmostEqual(browser.value("parseFloat(document.querySelector('[data-ring=tickets] [data-method=web][data-kind=won]').getAttribute('stroke-dasharray'))/parseFloat(document.querySelector('[data-ring=tickets] [data-method=web][data-kind=count]').getAttribute('stroke-dasharray'))"),10746556/65381848,places=10)
            browser.value("document.body.classList.remove('light-theme')")
            browser.call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1800,'deviceScaleFactor':1,'mobile':False},page=True)
            wait("(()=>{const h=document.getElementById('accountStatsMoneyChart');return Math.abs(h.clientWidth-h.querySelector('svg').viewBox.baseVal.width)<1})()")
            clip=browser.value("(()=>{const r=document.getElementById('accountStatsMethodChart').closest('article').getBoundingClientRect();return {x:r.left,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
            image=browser.call('Page.captureScreenshot',{'clip':clip,'captureBeyondViewport':True},page=True)
            (output/'user_screenshot_eight_colors_dark_1440.png').write_bytes(base64.b64decode(image['data']))
            browser.value("window.statisticsPieMode='zero-wins';document.getElementById('accountStatsRefresh').click()")
            wait("document.querySelector('.account-stats-donut-won')?.textContent==='0' && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            self.assertEqual(browser.value("document.querySelectorAll('[data-kind=won]').length"),0)
            self.assertEqual(browser.value("document.querySelectorAll('[data-kind=count]').length"),4)
            self.assertFalse(browser.value("document.getElementById('accountStatsMethodChart').innerHTML.includes('NaN')"))
            browser.value("window.statisticsPieMode='zero-purchases';document.getElementById('accountStatsRefresh').click()")
            wait("document.getElementById('accountStatsMethodChart').textContent.includes('Chưa có vé') && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-pie-sector').length"),0)
            browser.value("window.statisticsPieMode='unknown';document.getElementById('accountStatsRefresh').click()")
            wait("document.querySelector('[data-kind=won] title')?.textContent.includes('chưa phân loại') && document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false'")
            self.assertTrue(browser.value("document.querySelector('.account-stats-method-legend li .account-stats-method-value:last-child').title.includes('7 vé chưa phân loại')"))
            browser.value("window.fetch=statisticsOriginalFetch")
            browser.value("document.querySelector('[data-account-period=all]').click()")
            wait("document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false' && document.querySelectorAll('.account-stats-change').length===0")
            browser.value("document.querySelector('[data-account-line=spent]').click()")
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsMoneyChart .account-stats-lines path').length"),2)
            self.assertTrue(browser.value("document.activeElement.dataset.accountLine==='spent' && document.activeElement.getAttribute('aria-pressed')==='false'"))
            browser.value("document.getElementById('accountStatsNext').click()")
            browser.value("document.querySelector('[data-account-line=won]').click()")
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChart .account-stats-lines path').length"),1)
            self.assertTrue(browser.value("document.activeElement.dataset.accountLine==='won'"))
            browser.value("document.getElementById('accountStatsDate').value='2099-10-21';document.querySelector('[data-account-period=day]').click()")
            wait("document.getElementById('accountStatsSection').getAttribute('aria-busy')==='false' && document.querySelectorAll('#accountStatsCards article strong').length===5 && [...document.querySelectorAll('#accountStatsCards article strong')].every(e=>e.textContent==='0' || e.textContent==='0 ₫')")
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-change').length"),0)
            browser.value("document.querySelector('[data-account-line=won]').click()")
            self.assertEqual(browser.value("document.querySelectorAll('#accountStatsTicketChart circle[data-metric=won]').length"),24)
            browser.value("document.getElementById('homeMenuBtn').click()")
            wait("document.getElementById('accountStatsSection').hidden && !document.getElementById('mainContentGrid').hidden")
            self.assertEqual(browser.value('chartRotations.size'),0)
            browser.call('Network.setCookie',dict(name='LOTTO_AUTH',value=self.member.split(';')[0].split('=',1)[1],url=self.url),page=True)
            browser.call('Page.navigate',{'url':self.url+'/bieu-do'},page=True)
            wait("typeof currentUser!=='undefined' && currentUser==='member_fixture' && document.querySelector('#accountStatsCards article strong')?.textContent==='20.000 ₫'")
            self.assertEqual(browser.value('chartRotations.size'),1)
            browser.value("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
            self.assertEqual(browser.value('chartRotations.size'),0)
            browser.value("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
            self.assertEqual(browser.value('chartRotations.size'),1)
            browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:false}}))")
            self.assertEqual(browser.value("document.getElementById('accountStatsCards').textContent"),'')
            self.assertEqual(browser.value("document.querySelectorAll('.account-stats-legend button').length"),0)
            self.assertEqual(browser.value('chartRotations.size'),0)
            self.assertEqual(browser.value("document.getElementById('accountStatsMethodChart').textContent"),'')
            self.assertEqual(browser.value('chartErrors'),[])
        finally:
            browser.close()
