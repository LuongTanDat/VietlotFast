"""Full frontend login and server-backed wheel in a disposable HTTP/DB fixture."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.test_prize_web import JAVA, JAVAC, CHROME
from cdp_browser import Browser

script = r'''
<pre id="securitySmokeResult" style="position:fixed;bottom:0;z-index:99999">PENDING</pre>
<script>
window.addEventListener('load', async () => {
 const out = document.getElementById('securitySmokeResult');
 const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
 const check = (v,label) => { if(!v) throw new Error(label); };
 try {
  await pause(250);
  const rememberedKey = Object.keys(localStorage).find(k => k.includes('remember'));
  if(rememberedKey) check(!JSON.parse(localStorage.getItem(rememberedKey)).pass,'legacy plaintext password retained');
  await fetch('/api/register', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'username=browser_owner&password=fixture_browser_only'});
  document.getElementById('loginUser').value='browser_owner';
  document.getElementById('loginPass').value='fixture_browser_only';
  document.getElementById('rememberCreds').checked=true;
  document.getElementById('loginBtn').click();
  for(let i=0;i<40 && getComputedStyle(document.getElementById('appShell')).display==='none';i++) await pause(100);
  check(getComputedStyle(document.getElementById('appShell')).display!=='none','login did not enter app');
  check(document.documentElement.dataset.vipMembership==='active','admin VIP render');
  const key = Object.keys(localStorage).find(k => k.includes('remember'));
  const saved = JSON.parse(localStorage.getItem(key));
  check(saved.user==='browser_owner' && !('pass' in saved),'password saved in localStorage');
  check(typeof window.setVipMembershipExpiry==='undefined','client VIP setter remains public');
  await saveStore();
  await spinLuckyWheel();
  check(Number(store.walletVersion)===1,'wallet response not applied');
  check(store.luckyWheelHistory.length===1,'server reward history not applied');
  const account = await api('/api/store');
  check(account.store.diamondBalance===store.diamondBalance && account.store.paypalBalance===store.paypalBalance,'wallet/server mismatch');
  check(!document.getElementById('bootErrorBanner'),'frontend boot error');
  for(const type of ['MAX_3D','MAX_3D_PRO']) {
    const headers=getDataTableHeaders(type);
    check(!headers.includes('Giờ') && !headers.includes('ĐB'),'Max contains unused columns');
    const maxFeed={order:['1'],results:{'1':{date:'01/10/2026',displayLines:['Đặc biệt: 005 - 005','Giải nhất: 010']}}};
    const row=buildDataTableRows(type,maxFeed,'all',{});
    check(row[0].length===headers.length && row[0][3].includes('Đặc biệt: 005 - 005'),'Max lost group label, leading zero or duplicate result');
  }
  out.textContent=JSON.stringify({ok:true,remembered:saved,walletVersion:store.walletVersion,historyCount:store.luckyWheelHistory.length,unusedMaxColumns:false});
 } catch(error) { out.textContent='FAIL: '+error.stack; }
});
</script>
'''

with tempfile.TemporaryDirectory(prefix='full-ui-fixture-', dir=ROOT/'runtime') as folder:
    work = Path(folder)
    (work/'runtime').mkdir()
    shutil.copytree(ROOT/'frontend',work/'frontend')
    html = work/'frontend/vietlott-web.html'
    html.write_text(html.read_text(encoding='utf-8').replace('</body>',script+'</body>'),encoding='utf-8')
    build = work/'build'
    build.mkdir()
    compile = subprocess.run([JAVAC,'-encoding','UTF-8','-d',str(build.relative_to(ROOT)),'backend/LottoWebServer.java'],cwd=ROOT,capture_output=True)
    assert compile.returncode == 0, compile.stderr.decode(errors='replace')
    jar = ROOT/'backend/lib/sqlite-jdbc-3.51.2.0.jar'
    shutil.copy2(jar, work/'sqlite-jdbc.jar')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    flags=0x08000000 if os.name=='nt' else 0
    with (work/'java.log').open('wb') as log:
        server=subprocess.Popen([JAVA,'-Dfile.encoding=UTF-8',f'-Dlotto.port={port}','-cp','build'+os.pathsep+'sqlite-jdbc.jar','LottoWebServer'],cwd=work,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        try:
            url=f'http://127.0.0.1:{port}/'
            for _ in range(80):
                try:
                    with urllib.request.urlopen(url,timeout=1): break
                except Exception:
                    if server.poll() is not None: raise RuntimeError((work/'java.log').read_text(errors='replace'))
                    time.sleep(.1)
            browser=Browser(CHROME,work/'profile')
            try:
                browser.call('Page.navigate',{'url':url},page=True)
                for _ in range(150):
                    result=browser.value("document.getElementById('securitySmokeResult')?.textContent || 'PENDING'")
                    if result != 'PENDING': break
                    time.sleep(.1)
                if not result.startswith('{'):
                    result += '\nDiagnostics: '+str(browser.value("JSON.stringify({auth:document.getElementById('authMsg')?.textContent,boot:document.getElementById('bootErrorBanner')?.textContent})"))
            finally:
                browser.close()
            (ROOT/'runtime/audit_2026-10-04/fix_browser_smoke_result.txt').write_text(result,encoding='utf-8')
            assert result.startswith('{'),result
            report=json.loads(result)
            assert report['ok'],report
            print(json.dumps(report,ensure_ascii=False))
        finally:
            server.terminate()
            server.wait(timeout=10)
