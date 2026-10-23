"""Deposit packages and VNPAY controller on a fake gateway with no real payments."""
import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from tests.browser_cdp import Browser
from tests.test_prize_web import CHROME, ROOT, js_function


class PaypalDepositUITests(unittest.TestCase):
    def test_automatic_checkout_packages_history_wallet_and_session(self):
        html = (ROOT/'frontend/vietlott-web.html').read_text(encoding='utf-8')
        section = html[html.index('    <section id="paypalDepositSection"'):html.index('    <section id="liveBoardSection"')]
        core = (ROOT/'frontend/vietlott-web-core.js').read_text(encoding='utf-8')
        constants = core[core.index('    const MAX_PAYPAL_TOPUPS'):core.index('    const MAX_LUCKY_WHEEL_HISTORY')]
        names = ('ensurePaypalTopupState', 'getPaypalTopupPackageById', 'convertRealMoneyToPaypal', 'getPaypalBonusPackage', 'calculatePaypalCredit', 'formatPaypalCredit', 'formatPaypalPercent', 'isValidPaypalDepositAmount', 'renderPaypalRatePreview', 'getPaypalDepositAmount', 'showPaypalDepositMessage', 'setSelectedPaypalTopupPackage', 'resetPaypalDepositForm', 'renderPaypalTopupPackages', 'renderPaypalTopupHistory', 'renderPaypalDepositSection', 'setupPaypalDepositForm', 'formatLuckyWheelAmount')
        code = constants+'\n'.join(js_function(core, name) for name in names)
        fixture = '''
let selectedPaypalTopupPackageId='',currentUser='fixture',currentAccountId='123456789012',store={paypalBalance:123456,walletVersion:0,paypalTopups:[]};
let config={configured:false,environment:'production',minimum:1000000,maximum:1000000000,step:100000};
let migratedKeys=[],manualOrders=[],orders=[],serverWallet={paypalBalance:123456,walletVersion:0},fetchCalls=[],hold=false,held=[];
let manualInstructions='Thông tin nhận tiền thử';
const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const applyServerWallet=wallet=>{if((wallet.walletVersion||0)>=(store.walletVersion||0))Object.assign(store,wallet)};
const renderCurrencyBar=()=>{document.getElementById('depositPaypalBalance').textContent=store.paypalBalance.toLocaleString('vi-VN')};
window.fetch=async(path,opts)=>{
 fetchCalls.push({path,body:opts.body||'',user:currentUser});
 let data;
 if(path.endsWith('/config'))data={ok:true,...config};
 else if(path==='/api/payments/manual')data={ok:true,instructions:manualInstructions,orders:manualOrders,legacyKeys:migratedKeys,store:currentUser==='fixture'?serverWallet:{paypalBalance:0,walletVersion:0}};
 else if(opts.method==='POST'){
  const form=new URLSearchParams(opts.body),amount=Number(form.get('amount'));
  const order={id:'a'.repeat(32),environment:config.environment,status:'PENDING',amount,baseCredit:amount*1.25,bonusCredit:amount===50000?625:0,credit:amount===50000?63125:amount*1.25,createdAt:new Date().toISOString(),expiresAt:new Date(Date.now()+900000).toISOString()};
  orders=[order];data={ok:true,order,paymentUrl:'https://pay.vnpay.vn/vpcpay.html?vnp_TxnRef='+order.id};
 }else data={ok:true,orders:currentUser==='fixture'?orders:[],store:currentUser==='fixture'?serverWallet:{paypalBalance:0,walletVersion:0}};
 const reply=()=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 if(hold)return new Promise(resolve=>held.push(()=>resolve(reply())));
 return reply();
};
window.uiErrors=[];window.addEventListener('error',event=>uiErrors.push(event.message));
'''
        assets = ''.join(f'<link rel="stylesheet" href="{(ROOT/"frontend"/name).as_uri()}">' for name in ('vietlott-web.css', 'vietlott-web-extra.css'))
        assets += f'<script src="{(ROOT/"frontend/vietlott-web-numeric.js").as_uri()}"></script>'
        payments = (ROOT/'frontend/vietlott-web-payments.js').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='vnpay_ui_', dir=ROOT/'runtime') as folder:
            work = Path(folder); page = work/'fixture.html'
            page.write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+assets+section+'<script>'+fixture+'</script><script>'+payments+'</script><script>'+code+'\ndocument.getElementById("paypalDepositSection").hidden=false;setupPaypalDepositForm();renderPaypalDepositSection();</script>', encoding='utf-8')
            b = Browser(CHROME, work/'profile')
            def wait(expression):
                deadline = time.monotonic()+10
                while time.monotonic()<deadline:
                    if b.value(expression):
                        return
                    time.sleep(.03)
                self.fail('Timeout: '+expression+' '+str(b.value('window.uiErrors')))
            try:
                b.call('Page.enable', page=True); b.call('Runtime.enable', page=True)
                b.call('Page.navigate', {'url': page.as_uri()}, page=True)
                wait('document.getElementById("depositGatewayBadge")?.textContent==="Chưa kết nối"')
                self.assertFalse(b.value('document.getElementById("depositManualPane").hidden'))
                self.assertFalse(b.value('document.getElementById("depositHistoryDialog").open'))
                b.value('document.getElementById("depositHistoryOpen").focus();document.getElementById("depositHistoryOpen").click()')
                self.assertTrue(b.value('document.getElementById("depositHistoryDialog").open&&!!document.querySelector("#depositHistoryList .deposit-empty")'))
                b.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27},page=True)
                b.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27},page=True)
                self.assertTrue(b.value('!document.getElementById("depositHistoryDialog").open&&document.activeElement===document.getElementById("depositHistoryOpen")'))
                b.value('manualInstructions="MB Bank\\n0328197771\\nTên người nhận: LuongTanDat";VietlottBankTopup.refresh()')
                wait('!!document.querySelector("[data-bank-account]")')
                self.assertEqual(b.value('document.querySelector("[data-bank-account]").textContent'),'0328197771')
                self.assertEqual(b.value('document.querySelector("[data-bank-recipient]").textContent'),'LuongTanDat')
                self.assertTrue(b.value('document.getElementById("depositManualInstructions").textContent.includes("MB Bank")'))
                b.value('window.copiedBankAccount=null;Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>{window.copiedBankAccount=text}}});document.querySelector("[data-copy-bank-account]").click()')
                wait('window.copiedBankAccount==="0328197771"')
                self.assertTrue(b.value('document.querySelector("[data-copy-bank-account]").textContent.includes("Đã sao chép")'))
                for width in (320,390,1440):
                    b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                    for light in (False,True):
                        b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                        self.assertTrue(b.value('(()=>{const h=document.getElementById("depositManualInstructions");return h.scrollWidth<=h.clientWidth+1&&[...h.children].every(e=>e.scrollWidth<=e.clientWidth+1)})()'),(width,light))
                        self.assertTrue(b.value('(()=>{const n=document.querySelector(".deposit-bank-number").getBoundingClientRect(),h=document.querySelector(".deposit-bank-heading").getBoundingClientRect(),r=document.querySelector(".deposit-bank-recipient").getBoundingClientRect();return n.left>=h.right-1&&Math.abs(n.top-h.top)<3&&r.top>=n.bottom})()'),(width,light))
                        if (width,light) in ((390,True),(1440,False)):
                            box=b.value('(()=>{const r=document.getElementById("depositManualInstructions").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()')
                            shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box},page=True)
                            (ROOT/f'Bin/session_1_latest/bank_card_layout_{width}.png').write_bytes(base64.b64decode(shot['data']))
                # Long balances and the largest quote must remain readable in
                # the manual form as its two columns collapse on smaller screens.
                b.value('document.querySelector(".account-id-chip").hidden=false;document.querySelector(".account-id-chip").textContent="ID: "+currentAccountId;document.getElementById("depositPaypalBalance").textContent="999.289.033.087.875";document.querySelector("[data-package-id=custom]").click();document.getElementById("depositAmount").value="100.000.000";document.getElementById("depositAmount").dispatchEvent(new Event("input"));document.getElementById("depositAmount").blur()')
                for width in (320,390,560,768,960,1024,1440):
                    b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                    for light in (False,True):
                        b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()});window.scrollTo(0,0)')
                        self.assertTrue(b.value('document.documentElement.scrollWidth<=innerWidth+1&&[...document.querySelectorAll(".deposit-balance-box,.deposit-package-card,.deposit-form-card,.deposit-checkout-card,.deposit-preview-row,.deposit-preview-final,.deposit-memo-input")].every(e=>e.scrollWidth<=e.clientWidth+1)'),(width,light,'manual max amount'))
                        self.assertTrue(b.value('(()=>{const r=document.querySelector(".deposit-checkout-actions").getBoundingClientRect(),b=document.getElementById("depositManualSubmit").getBoundingClientRect(),q=document.getElementById("depositRatePreview").getBoundingClientRect();return Math.abs(r.width-b.width)<1&&b.top>=q.bottom&&document.getElementById("depositManualSubmit").form===document.getElementById("manualDepositForm")})()'))
                        if (width,light) in ((390,True),(1024,False),(1440,False)):
                            box=b.value('(()=>{const r=document.getElementById("paypalDepositSection").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()')
                            shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box},page=True)
                            (ROOT/f'Bin/session_1_latest/deposit_compact_manual_{width}.png').write_bytes(base64.b64decode(shot['data']))
                b.value('setSelectedPaypalTopupPackage("small");renderPaypalTopupPackages();renderCurrencyBar();document.body.classList.remove("light-theme")')
                b.value('document.getElementById("depositFastTab").click()')
                self.assertTrue(b.value('document.querySelector(".deposit-checkout-actions").hidden'))
                self.assertTrue(b.value('document.getElementById("depositCreateBtn").disabled'))
                self.assertFalse(b.value('!!document.getElementById("depositPaypalEmail")'))
                b.value('store.paypalTopups=[{amount:20000,status:"PAID",txnCode:"<img src=x onerror=alert(1)>"}];renderPaypalTopupHistory()')
                self.assertTrue(b.value('document.getElementById("depositHistoryList").textContent.includes("Chưa xác minh")&&document.querySelectorAll("#depositHistoryList img").length===0'))
                b.value('manualOrders=[{id:"b".repeat(32),environment:"manual",status:"PENDING",amount:20000,credit:25000,bonusCredit:0,createdAt:new Date().toISOString(),sender:"Người chuyển cũ",channel:"Chưa ghi ngân hàng / ví",reference:"old-ref",legacyEmail:"fixture@example.test"}];migratedKeys=["fields:"+JSON.stringify(["amount","createdAt","txnCode","txnTime","senderName","email","note"].map(key=>String(store.paypalTopups[0][key]??"")))];VietlottBankTopup.refresh()')
                wait('document.getElementById("depositHistoryList").textContent.includes("Chờ admin duyệt")')
                self.assertFalse(b.value('document.getElementById("depositHistoryList").textContent.includes("Chưa xác minh")'))
                self.assertEqual(b.value('document.querySelectorAll("#depositHistoryList .deposit-history-item").length'),1)
                b.value('manualOrders[0].amount=100000000;manualOrders[0].credit=131250000;manualOrders[0].bonusCredit=6250000;orders=[{id:"c".repeat(32),environment:"sandbox",status:"TEST_PAID",amount:50000,credit:63125,bonusCredit:625,transactionNo:"qr-test",createdAt:new Date().toISOString()}];VietlottBankTopup.refresh()')
                wait('document.querySelectorAll("#depositHistoryList .deposit-method-label").length===2')
                self.assertEqual(set(b.value('[...document.querySelectorAll(".deposit-method-label")].map(e=>e.textContent)')),{'Thủ Công','Nạp Nhanh'})
                self.assertTrue(b.value('document.getElementById("depositHistoryList").textContent.includes("Thử nghiệm — không cộng ví thật")'))
                b.value('document.getElementById("depositHistoryOpen").click()')
                for width in (320,390,768,1440):
                    b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                    for light in (False,True):
                        b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                        self.assertTrue(b.value('(()=>{const d=document.getElementById("depositHistoryDialog"),r=d.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&d.scrollWidth<=d.clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1})()'),(width,light,'history dialog'))
                        self.assertTrue(b.value('[...document.querySelectorAll(".deposit-transaction-row td")].every(e=>e.scrollWidth<=e.clientWidth+1)'),(width,light,'transaction contents'))
                        if width<680:
                            self.assertTrue(b.value('(()=>{const e=document.getElementById("depositHistoryList");e.scrollLeft=100;const moved=e.scrollLeft>0;e.scrollLeft=0;return moved})()'))
                        if (width,light) in ((390,True),(1440,False)):
                            shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False},page=True)
                            (ROOT/f'Bin/session_1_latest/deposit_history_dialog_{width}.png').write_bytes(base64.b64decode(shot['data']))
                b.value('document.querySelector("[data-history-toggle]").focus()')
                self.assertTrue(b.value('document.activeElement===document.querySelector("[data-history-toggle]")'))
                b.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','text':'\r','windowsVirtualKeyCode':13},page=True)
                b.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13},page=True)
                self.assertTrue(b.value('(()=>{const b=document.querySelector("[data-history-toggle]");return b.getAttribute("aria-expanded")==="true"&&!document.getElementById(b.getAttribute("aria-controls")).hidden})()'))
                b.value('window.savedHistoryButton=document.activeElement;window.expandedHistoryKey=document.activeElement.dataset.historyKey;window.previousFetches=fetchCalls.length;VietlottBankTopup.refresh()')
                wait('fetchCalls.length>=previousFetches+3')
                wait('!savedHistoryButton.isConnected&&document.activeElement?.dataset.historyKey===expandedHistoryKey&&document.activeElement.getAttribute("aria-expanded")==="true"')
                for width in (390,1440):
                    b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                    shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False},page=True)
                    (ROOT/f'Bin/session_1_latest/deposit_history_expanded_{width}.png').write_bytes(base64.b64decode(shot['data']))
                b.value('document.activeElement.click()')
                self.assertTrue(b.value('document.querySelector(".deposit-transaction-details").hidden'))
                b.value('document.getElementById("depositHistoryClose").click()')
                self.assertFalse(b.value('document.getElementById("depositHistoryDialog").open'))
                b.value('document.getElementById("depositHistoryOpen").click()')
                b.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':0,'y':0,'button':'left','clickCount':1},page=True)
                b.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':0,'y':0,'button':'left','clickCount':1},page=True)
                self.assertFalse(b.value('document.getElementById("depositHistoryDialog").open'))
                b.value('store.paypalTopups=[];manualOrders=[];orders=[];migratedKeys=[]')
                b.value('config.configured=true;VietlottBankTopup.refresh()')
                wait('!document.getElementById("depositCreateBtn").disabled')
                self.assertEqual(b.value('[...document.querySelectorAll(".deposit-package-item")].map(button=>button.dataset.packageId)'), ['small','starter','boost','plus','pro','custom'])
                self.assertTrue(b.value('document.getElementById("depositCustomAmountField").hidden'))
                for package_id, amount, total in [('small',20000,25000),('starter',50000,63125),('boost',100000,126875),('plus',200000,255000),('pro',500000,640625)]:
                    b.value(f'document.querySelector("[data-package-id={package_id}]").click()')
                    self.assertTrue(b.value('document.getElementById("depositCustomAmountField").hidden'))
                    self.assertEqual(b.value('getPaypalDepositAmount()'), amount)
                    self.assertEqual(b.value('calculatePaypalCredit(getPaypalDepositAmount(),selectedPaypalTopupPackageId).totalCredit'), total)
                b.value('document.querySelector("[data-package-id=custom]").click()')
                self.assertFalse(b.value('document.getElementById("depositCustomAmountField").hidden'))
                self.assertTrue(b.value('document.activeElement===document.getElementById("depositAmount")'))
                # Group the visible amount while the native IME edit is still
                # open, without changing the IME's actual replacement range.
                for raw in ('100','1000','10000','100000','1000000','10000000','100000000','1000000000','1100000','220000'):
                    b.value('document.getElementById("depositAmount").select()')
                    for length in range(1,len(raw)+1):
                        text=raw[:length]
                        b.call('Input.imeSetComposition',{'text':text,'selectionStart':length,'selectionEnd':length},page=True)
                        expected=f'{min(int(text),100000000):,}'.replace(',','.')
                        self.assertEqual(b.value('document.querySelector(".deposit-amount-live").textContent'),expected)
                        self.assertEqual(b.value('document.getElementById("depositAmount").value'),text)
                        self.assertEqual(b.value('getPaypalDepositAmount()'),min(int(text),100000000))
                        self.assertTrue(b.value('!document.querySelector(".deposit-amount-live").hidden && document.getElementById("depositAmount").classList.contains("has-live-composition")'))
                    if raw=='10000000':
                        self.assertEqual(b.value('getComputedStyle(document.getElementById("depositAmount")).webkitTextFillColor'),'rgba(0, 0, 0, 0)')
                        self.assertNotEqual(b.value('getComputedStyle(document.querySelector(".deposit-amount-live")).color'),'rgba(0, 0, 0, 0)')
                        for width in (320,390,560,1440):
                            b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                            for light in (False,True):
                                b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                                self.assertTrue(b.value('(()=>{const d=document.querySelector(".deposit-amount-live");return !d.hidden && d.textContent==="10.000.000" && d.scrollWidth<=d.clientWidth+1})()'),(width,light))
                                if (width,light) in ((390,True),(1440,False)):
                                    box=b.value('(()=>{const r=document.querySelector(".deposit-amount-panel").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()')
                                    shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box},page=True)
                                    (ROOT/f'Bin/session_1_latest/deposit_live_grouping_active_{width}.png').write_bytes(base64.b64decode(shot['data']))
                        b.value('document.body.classList.remove("light-theme")')
                    b.call('Input.insertText',{'text':raw},page=True)
                    wait('document.getElementById("depositAmount").value==='+json.dumps(expected)+' && !document.getElementById("depositAmount").classList.contains("has-live-composition")')
                # Use native keyboard/IME edits, not assigned values: formatting
                # must never turn 100 into 110 or replay a committed digit.
                for raw in ('100','100000','1100000','1000000000'):
                    b.value('document.getElementById("depositAmount").select()')
                    for digit in raw:
                        for kind in ('keyDown','keyUp'):
                            b.call('Input.dispatchKeyEvent',{'type':kind,'key':digit,'code':'Digit'+digit,
                                   'text':digit if kind=='keyDown' else '', 'windowsVirtualKeyCode':ord(digit)},page=True)
                    self.assertEqual(b.value('document.getElementById("depositAmount").value'),f'{min(int(raw),100000000):,}'.replace(',','.'))
                for pasted in ('1000000000','1.000.000.000'):
                    b.value('document.getElementById("depositAmount").select()')
                    b.call('Input.insertText',{'text':pasted},page=True)
                    self.assertEqual(b.value('document.getElementById("depositAmount").value'),'100.000.000')
                    self.assertEqual(b.value('getPaypalDepositAmount()'),100000000)
                    self.assertTrue(b.value('document.querySelector(".deposit-preview-final").textContent.includes("131.250.000")'))
                self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'),0)
                b.value('document.getElementById("depositAmount").select()')
                for index,digit in enumerate('100000'):
                    b.call('Input.imeSetComposition',{'text':digit,'selectionStart':1,'selectionEnd':1},page=True)
                    expected = f'{int("100000"[:index+1]):,}'.replace(',','.')
                    self.assertEqual(b.value('document.querySelector(".deposit-amount-live").textContent'),expected)
                    b.call('Input.insertText',{'text':digit},page=True)
                    expected = f'{int("100000"[:index+1]):,}'.replace(',','.')
                    wait('document.getElementById("depositAmount").value==='+json.dumps(expected))
                b.value('document.getElementById("depositAmount").setSelectionRange(0,1)')
                b.call('Input.insertText',{'text':'2'},page=True)
                self.assertEqual(b.value('document.getElementById("depositAmount").value'),'200.000')
                b.value('document.getElementById("depositAmount").select()')
                b.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Backspace','code':'Backspace','windowsVirtualKeyCode':8},page=True)
                b.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Backspace','code':'Backspace','windowsVirtualKeyCode':8},page=True)
                self.assertEqual(b.value('document.getElementById("depositAmount").value'),'')
                b.value('document.getElementById("depositAmount").value="10000";document.getElementById("depositAmount").dispatchEvent(new Event("input"))')
                self.assertEqual(b.value('calculatePaypalCredit(getPaypalDepositAmount(),selectedPaypalTopupPackageId).totalCredit'),12500)
                self.assertTrue(b.value('!!document.querySelector("#depositRatePreview .is-empty")'))
                b.value('document.getElementById("depositAmount").select()')
                for text in ('2','20','200','2000','20000','200000'):
                    b.call('Input.imeSetComposition', {'text':text,'selectionStart':len(text),'selectionEnd':len(text)}, page=True)
                b.call('Input.insertText', {'text':'200000'}, page=True)
                wait('document.getElementById("depositAmount").value==="200.000"')
                self.assertEqual(b.value('document.getElementById("depositAmount").value'), '200.000')
                self.assertEqual(b.value('selectedPaypalTopupPackageId'),'custom')
                self.assertFalse(b.value('document.getElementById("depositCustomAmountField").hidden'))
                self.assertTrue(b.value('document.querySelector("[data-package-id=custom]").classList.contains("active")'))
                self.assertEqual(b.value('calculatePaypalCredit(getPaypalDepositAmount(),selectedPaypalTopupPackageId).totalCredit'),255000)
                self.assertTrue(b.value('!!document.querySelector("#depositRatePreview .is-empty")'))
                b.value('renderPaypalDepositSection()')
                self.assertEqual(b.value('getPaypalDepositAmount()'),200000)
                self.assertFalse(b.value('document.getElementById("depositCustomAmountField").hidden'))
                self.assertEqual(b.value('document.getElementById("depositAmountHint").textContent'),'Nạp tối thiểu Từ 1.000.000 đến tối đa 100.000.000 VNĐ, Bội số 100.000 VNĐ.')
                self.assertEqual(b.value('document.querySelector(".deposit-bonus-hint").textContent'),'Thưởng đến 5%')
                for amount, bonus, credit in [(1000000,62500,1312500),(1100000,68750,1443750),
                                              (10000000,625000,13125000),(99900000,6243750,131118750),
                                              (100000000,6250000,131250000)]:
                    b.value(f'document.getElementById("depositAmount").value="{amount}";document.getElementById("depositAmount").dispatchEvent(new Event("input"))')
                    self.assertEqual(b.value('calculatePaypalCredit(getPaypalDepositAmount(),selectedPaypalTopupPackageId).bonusCredit'),bonus)
                    self.assertEqual(b.value('calculatePaypalCredit(getPaypalDepositAmount(),selectedPaypalTopupPackageId).totalCredit'),credit)
                    self.assertTrue(b.value('document.getElementById("depositRatePreview").textContent.includes("Thưởng 5%")'))
                    self.assertEqual(b.value('document.querySelector(".deposit-preview-row > span").textContent'),'Nạp Tiền')
                    self.assertEqual(b.value('document.querySelectorAll(".deposit-preview-row").length'),3)
                    self.assertEqual(b.value('document.querySelector(".deposit-preview-vip > span").textContent'),'VIP — · —%')
                    self.assertEqual(b.value('document.querySelector(".deposit-preview-vip > strong").textContent'),'+0 PayPal')
                    self.assertEqual(b.value('selectedPaypalTopupPackageId'),'custom')
                    if amount==1000000:
                        box=b.value('(()=>{const r=document.querySelector(".deposit-checkout-card").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()')
                        shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box},page=True)
                        (ROOT/'Bin/session_1_latest/deposit_three_rows_1m.png').write_bytes(base64.b64decode(shot['data']))
                    if amount==100000000:
                        for width in (320,390,560,1440):
                            b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                            self.assertTrue(b.value('(()=>{const p=document.getElementById("depositRatePreview"),rows=[...p.children];return p.scrollWidth<=p.clientWidth+1 && rows.every(row=>{const l=row.firstElementChild.getBoundingClientRect(),r=row.lastElementChild.getBoundingClientRect();return row.scrollWidth<=row.clientWidth+1 && (l.right<=r.left+1 || l.bottom<=r.top+1)})})()'),width)
                            if width in (390,1440):
                                box=b.value('(()=>{const r=document.querySelector(".deposit-checkout-card").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()')
                                shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':box},page=True)
                                (ROOT/f'Bin/session_1_latest/deposit_three_rows_{width}.png').write_bytes(base64.b64decode(shot['data']))
                for invalid in (500000,900000,1000001,1050000):
                    b.value(f'document.getElementById("depositAmount").value="{invalid}";document.getElementById("depositAmount").dispatchEvent(new Event("input"));document.getElementById("paypalDepositForm").requestSubmit()')
                    self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'),0)
                    self.assertTrue(b.value('!!document.querySelector("#depositRatePreview .is-empty")'))
                self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'),0)
                self.assertTrue(b.value('!!document.querySelector("#depositRatePreview .is-empty")'))
                self.assertTrue(b.value('document.getElementById("depositMsg").textContent.includes("100.000.000")'))
                b.value('document.getElementById("depositAmount").value="10001";document.getElementById("paypalDepositForm").requestSubmit()')
                self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'), 0)
                b.value('document.querySelector("[data-package-id=starter]").click();document.getElementById("paypalDepositForm").requestSubmit()')
                wait('!!document.querySelector(".deposit-checkout-link")')
                self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'), 1)
                self.assertEqual(b.value('store.paypalBalance'), 123456)
                self.assertTrue(b.value('document.querySelector(".deposit-checkout-link").href.startsWith("https://pay.vnpay.vn/vpcpay.html?")'))
                self.assertTrue(b.value('document.querySelector(".deposit-status-pill").textContent.includes("Chờ thanh toán")'))
                images=ROOT/'Bin/session_1_latest/deposit_packages_images';images.mkdir(exist_ok=True)
                for width in (320,390,560,768,820,1024,1440,1920):
                    b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                    for light in (False,True):
                        b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                        self.assertTrue(b.value('document.documentElement.scrollWidth<=innerWidth+1&&[...document.querySelectorAll(".deposit-package-item,.deposit-form-card,.deposit-payment-panel")].every(el=>el.scrollWidth<=el.clientWidth+1)'),(width,light))
                        if (width,light) in ((1440,False),(390,True)):
                            shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':width,'height':b.value('document.documentElement.scrollHeight'),'scale':1}},page=True)
                            (images/f'{width}_{"light" if light else "dark"}.png').write_bytes(base64.b64decode(shot['data']))
                            if width==1440 and not light:
                                b.value('document.querySelector("[data-package-id=custom]").click()')
                                shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True},page=True)
                                (images/'custom_1440.png').write_bytes(base64.b64decode(shot['data']))
                                b.value('document.querySelector("[data-package-id=starter]").click()')
                b.value('orders[0].status="PAID";serverWallet={paypalBalance:186581,walletVersion:1};VietlottBankTopup.refresh()')
                wait('store.paypalBalance===186581')
                self.assertTrue(b.value('document.getElementById("depositPaymentPanel").textContent.includes("Đã cộng ví")'))
                b.value('orders[0].status="TEST_PAID";orders[0].environment="sandbox";config.environment="sandbox";VietlottBankTopup.refresh()')
                wait('document.getElementById("depositGatewayNotice").textContent.includes("thử nghiệm")')
                self.assertEqual(b.value('store.paypalBalance'),186581)
                b.value('hold=true;VietlottBankTopup.refresh()')
                wait('held.length===3')
                b.value('document.getElementById("depositHistoryOpen").click();currentUser="other";currentAccountId="987654321098";store={paypalBalance:0,walletVersion:0,paypalTopups:[]};hold=false;window.dispatchEvent(new Event("dvlf:auth-changed"));for(const reply of held.splice(0))reply()')
                wait('!document.getElementById("depositCreateBtn").disabled')
                self.assertFalse(b.value('document.getElementById("depositHistoryDialog").open'))
                self.assertEqual(b.value('store.paypalBalance'),0)
                self.assertEqual(b.value('document.getElementById("depositManualAccountId").value'),'987654321098')
                self.assertFalse(b.value('document.getElementById("depositHistoryList").textContent.includes("50.000 VNĐ")'))
                b.value('orders[0].status="PENDING";currentUser="fixture";window.dispatchEvent(new Event("dvlf:auth-changed"))')
                wait('!!document.querySelector("[data-payment-status=PENDING]")')
                b.value('currentUser=null;currentAccountId="";window.dispatchEvent(new Event("dvlf:auth-changed"))')
                count=b.value('fetchCalls.length');time.sleep(5.2)
                self.assertEqual(b.value('fetchCalls.length'),count)
                self.assertTrue(b.value('document.getElementById("depositCreateBtn").disabled'))
                self.assertEqual(b.value('document.getElementById("depositManualAccountId").value'),'')
                for name,source in [('core',core),('payments',payments)]:
                    self.assertNotIn('exceptionDetails',b.call('Runtime.compileScript',{'expression':source,'sourceURL':name+'.js','persistScript':False},page=True))
                self.assertEqual(b.value('uiErrors'),[])
                proof={'ok':True,'layouts':16,'fivePresetsAndCustom':True,'inputOnlyShownForCustom':True,'customModePreservedForMatchingPresetAmount':True,'allPackageRatesPreserved':True,'ime200kExact':True,'disabledUntilConfigured':True,'noClientCredit':True,'serverWalletApplied':True,'sandboxLabeled':True,'staleAccountResponseIgnored':True,'logoutStopsPolling':True,'realGatewayCalled':False}
                (ROOT/'Bin/session_1_latest/deposit_packages_ui_verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
            finally:
                b.close()
