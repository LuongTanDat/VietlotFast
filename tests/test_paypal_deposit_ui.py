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
        names = ('ensurePaypalTopupState', 'getPaypalTopupPackageById', 'convertRealMoneyToPaypal', 'getPaypalBonusPackage', 'calculatePaypalCredit', 'formatPaypalCredit', 'formatPaypalPercent', 'renderPaypalRatePreview', 'getPaypalDepositAmount', 'showPaypalDepositMessage', 'setSelectedPaypalTopupPackage', 'resetPaypalDepositForm', 'renderPaypalTopupPackages', 'renderPaypalTopupHistory', 'renderPaypalDepositSection', 'setupPaypalDepositForm', 'formatLuckyWheelAmount')
        code = constants+'\n'.join(js_function(core, name) for name in names)
        fixture = '''
let selectedPaypalTopupPackageId='',currentUser='fixture',store={paypalBalance:123456,walletVersion:0,paypalTopups:[]};
let config={configured:false,environment:'production',minimum:10000,maximum:10000000,step:1000};
let orders=[],serverWallet={paypalBalance:123456,walletVersion:0},fetchCalls=[],hold=false,held=[];
const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const applyServerWallet=wallet=>{if((wallet.walletVersion||0)>=(store.walletVersion||0))Object.assign(store,wallet)};
const renderCurrencyBar=()=>{document.getElementById('depositPaypalBalance').textContent=store.paypalBalance.toLocaleString('vi-VN')};
window.fetch=async(path,opts)=>{
 fetchCalls.push({path,body:opts.body||'',user:currentUser});
 let data;
 if(path.endsWith('/config'))data={ok:true,...config};
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
                self.assertTrue(b.value('document.getElementById("depositCreateBtn").disabled'))
                self.assertFalse(b.value('!!document.getElementById("depositPaypalEmail")'))
                b.value('store.paypalTopups=[{amount:20000,status:"PAID",txnCode:"<img src=x onerror=alert(1)>"}];renderPaypalTopupHistory()')
                self.assertTrue(b.value('document.getElementById("depositHistoryList").textContent.includes("Chưa xác minh")&&document.querySelectorAll("#depositHistoryList img").length===0'))
                b.value('store.paypalTopups=[]')
                b.value('config.configured=true;VietlottBankTopup.refresh()')
                wait('!document.getElementById("depositCreateBtn").disabled')
                for package_id, amount, total in [('mini',10000,12500),('small',20000,25000),('starter',50000,63125),('boost',100000,126875),('plus',200000,255000),('pro',500000,640625)]:
                    b.value(f'document.querySelector("[data-package-id={package_id}]").click()')
                    self.assertEqual(b.value('getPaypalDepositAmount()'), amount)
                    self.assertEqual(b.value('calculatePaypalCredit(getPaypalDepositAmount(),selectedPaypalTopupPackageId).totalCredit'), total)
                b.value('document.getElementById("depositAmount").focus();document.getElementById("depositAmount").select()')
                for text in ('2','20','200','2000','20000','200000'):
                    b.call('Input.imeSetComposition', {'text':text,'selectionStart':len(text),'selectionEnd':len(text)}, page=True)
                b.call('Input.insertText', {'text':'200000'}, page=True)
                self.assertEqual(b.value('document.getElementById("depositAmount").value'), '200.000')
                b.value('document.getElementById("depositAmount").value="10001";document.getElementById("paypalDepositForm").requestSubmit()')
                self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'), 0)
                b.value('document.querySelector("[data-package-id=starter]").click();document.getElementById("paypalDepositForm").requestSubmit()')
                wait('!!document.querySelector(".deposit-checkout-link")')
                self.assertEqual(b.value('fetchCalls.filter(call=>call.body).length'), 1)
                self.assertEqual(b.value('store.paypalBalance'), 123456)
                self.assertTrue(b.value('document.querySelector(".deposit-checkout-link").href.startsWith("https://pay.vnpay.vn/vpcpay.html?")'))
                self.assertTrue(b.value('document.querySelector(".deposit-status-pill").textContent.includes("Chờ thanh toán")'))
                images=ROOT/'Bin/session_1_latest/vnpay_ui_images';images.mkdir(exist_ok=True)
                for width in (320,390,560,768,820,1024,1440,1920):
                    b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                    for light in (False,True):
                        b.value(f'document.body.classList.toggle("light-theme",{str(light).lower()})')
                        self.assertTrue(b.value('document.documentElement.scrollWidth<=innerWidth+1&&[...document.querySelectorAll(".deposit-package-item,.deposit-form-card,.deposit-payment-panel")].every(el=>el.scrollWidth<=el.clientWidth+1)'),(width,light))
                        if (width,light) in ((1440,False),(390,True)):
                            shot=b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':width,'height':b.value('document.documentElement.scrollHeight'),'scale':1}},page=True)
                            (images/f'{width}_{"light" if light else "dark"}.png').write_bytes(base64.b64decode(shot['data']))
                b.value('orders[0].status="PAID";serverWallet={paypalBalance:186581,walletVersion:1};VietlottBankTopup.refresh()')
                wait('store.paypalBalance===186581')
                self.assertTrue(b.value('document.getElementById("depositPaymentPanel").textContent.includes("Đã cộng ví")'))
                b.value('orders[0].status="TEST_PAID";orders[0].environment="sandbox";config.environment="sandbox";VietlottBankTopup.refresh()')
                wait('document.getElementById("depositGatewayNotice").textContent.includes("thử nghiệm")')
                self.assertEqual(b.value('store.paypalBalance'),186581)
                b.value('hold=true;VietlottBankTopup.refresh()')
                wait('held.length===2')
                b.value('currentUser="other";store={paypalBalance:0,walletVersion:0,paypalTopups:[]};hold=false;window.dispatchEvent(new Event("dvlf:auth-changed"));for(const reply of held.splice(0))reply()')
                wait('!document.getElementById("depositCreateBtn").disabled')
                self.assertEqual(b.value('store.paypalBalance'),0)
                self.assertFalse(b.value('document.getElementById("depositHistoryList").textContent.includes("50.000 VNĐ")'))
                b.value('orders[0].status="PENDING";currentUser="fixture";window.dispatchEvent(new Event("dvlf:auth-changed"))')
                wait('!!document.querySelector("[data-payment-status=PENDING]")')
                b.value('currentUser=null;window.dispatchEvent(new Event("dvlf:auth-changed"))')
                count=b.value('fetchCalls.length');time.sleep(5.2)
                self.assertEqual(b.value('fetchCalls.length'),count)
                self.assertTrue(b.value('document.getElementById("depositCreateBtn").disabled'))
                for name,source in [('core',core),('payments',payments)]:
                    self.assertNotIn('exceptionDetails',b.call('Runtime.compileScript',{'expression':source,'sourceURL':name+'.js','persistScript':False},page=True))
                self.assertEqual(b.value('uiErrors'),[])
                proof={'ok':True,'layouts':16,'allPackageRatesPreserved':True,'ime200kExact':True,'disabledUntilConfigured':True,'noClientCredit':True,'serverWalletApplied':True,'sandboxLabeled':True,'staleAccountResponseIgnored':True,'logoutStopsPolling':True,'realGatewayCalled':False}
                (ROOT/'Bin/session_1_latest/vnpay_ui_verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
            finally:
                b.close()
