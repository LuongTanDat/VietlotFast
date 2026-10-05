"""Render isolated redesign previews with explicit demonstration data, no real accounts."""
import argparse
import base64
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.browser_cdp import Browser

parser = argparse.ArgumentParser()
parser.add_argument('stage', choices=('before', 'after'))
args = parser.parse_args()
directory = Path(__file__).resolve().parent
backup = ROOT / 'Bin/session_1_latest/files/frontend'
source = backup if args.stage == 'before' else ROOT / 'frontend'
html = (source / 'vietlott-web.html').read_text(encoding='utf-8')
section = html[html.index('      <section id="predictRootEffectiveness"'):html.index('      <section id="predictRootManual"')]
page = ('<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="stylesheet" href="/vietlott-web.css"><link rel="stylesheet" href="/vietlott-web-extra.css">'
        '<body><main style="max-width:1180px;padding:24px;margin:auto"><p style="font-size:11px;opacity:.65;margin:0 0 12px">Bản xem thử giao diện · dữ liệu minh họa</p>'
        + section + '</main><script src="/vietlott-web-effectiveness.js"></script></body></html>')
keys = ['web', 'random', 'bayesian', 'ewma']
labels = ['Pipeline web', 'Ngẫu nhiên', 'Bayesian', 'EWMA']
report = {'ok': True, 'type': 'LOTO_6_45', 'label': 'Mega 6/45', 'canManage': True,
          'settings': {'enabled': True, 'ticketCount': 3},
          'counts': {'total': 28, 'scored': 27, 'locked': 1},
          'methods': [{'key': key, 'label': labels[i], 'sampleCount': 27,
                       'meanHits': [.82,.78,.81,.76][i], 'rate3': [.08,.06,.07,.06][i],
                       'rate4': [0,0,0,0][i], 'deltaVsRandom': [.04,0,.03,-.02][i],
                       'ci95': {'lower': -.09, 'upper': .17}, 'decision': 'insufficient_evidence',
                       'brierScore': [.117,.1156,.116,.118][i], 'logLoss': [.41,.39,.4,.42][i]} for i,key in enumerate(keys)],
          'notes': ['Chỉ đánh giá kỳ đã khóa trước giờ quay; không dựng lại dự đoán lịch sử.',
                    'So bốn phương pháp cùng kỳ và cùng số vé. Chỉ chấm số chính; số đặc biệt đối chứng được lấy ngẫu nhiên.',
                    'Brier/log loss dùng xác suất biên chưa hiệu chỉnh. CI bootstrap ghép cặp theo kỳ, chưa điều chỉnh thử nhiều phương pháp.',
                    'Dưới 30 kỳ hoặc CI chứa 0: chưa đủ bằng chứng lợi thế. Kết quả quá khứ không bảo đảm kỳ sau.'],
          'cycles': []}
for draw in (1572,1571,1570):
    pending = draw == 1572
    report['cycles'].append({'cycleId': 'preview_'+str(draw), 'targetDrawId': str(draw), 'cutoffDrawId': str(draw-1),
                            'createdAt': '2026-10-04T12:38:00Z', 'deadline': '2026-10-07T11:00:00+00:00',
                            'config': {'ticketCount': 3}, 'status': 'locked' if pending else 'scored',
                            'actualMain': [] if pending else [1,6,17,28,34,42],
                            'methods': {key:{'tickets': [{'main':[1,6,12,23,34,42]},
                                                        {'main':[3,9,17,24,30,41]},
                                                        {'main':[7,14,18,22,28,36]}],
                                            'meanHits': None if pending else 2,
                                            'bestHits': None if pending else 4,
                                            'engine': 'classic' if key == 'web' else key,
                                            'modelId': 'execution_effectiveness_cdd6718ee124ce7118963935c3ea'} for key in keys}})

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path.startswith('/api/ml/effectiveness?'):
            data,kind=json.dumps(report).encode(),'application/json'
        elif self.path == '/':
            data,kind=page.encode(),'text/html;charset=utf-8'
        else:
            file=(source/self.path.lstrip('/'))
            if not file.is_file(): file=ROOT/'frontend'/self.path.lstrip('/')
            if not file.is_file() or file.suffix not in ('.js','.css'):
                self.send_error(404); return
            data,kind=file.read_bytes(), 'text/css' if file.suffix=='.css' else 'text/javascript'
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='ui-preview-',dir=ROOT/'runtime') as temp:
        browser=Browser('C:/Program Files/Google/Chrome/Application/chrome.exe',Path(temp))
        try:
            browser.call('Emulation.setDeviceMetricsOverride', {'width':1400,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
            browser.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/'},page=True)
            for _ in range(100):
                if browser.value('!!window.VietlottEffectiveness'): break
                time.sleep(.05)
            browser.value("document.getElementById('predictRootEffectiveness').hidden=false;document.getElementById('effectivenessType').value='LOTO_6_45';VietlottEffectiveness.activate(true);window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'preview'}}));")
            for _ in range(100):
                if browser.value("document.querySelectorAll('.effectiveness-cycle').length===3"): break
                time.sleep(.05)
            browser.value("document.querySelectorAll('.effectiveness-cycle').forEach((el,i)=>el.open=i===1)")
            for width,mobile in [(1400,False),(390,True)]:
                browser.call('Emulation.setDeviceMetricsOverride', {'width':width,'height':1000 if not mobile else 844,'deviceScaleFactor':1,'mobile':mobile},page=True)
                browser.value('window.scrollTo(0,0)')
                time.sleep(.12)
                size=browser.call('Page.getLayoutMetrics',page=True)['cssContentSize']
                shot=browser.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':width,'height':min(size['height'],3200),'scale':1}},page=True)
                (directory/f'{args.stage}_{"mobile" if mobile else "desktop"}.png').write_bytes(base64.b64decode(shot['data']))
                rect=browser.value("(()=>{const r=document.getElementById('effectivenessCycles').getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height}})()")
                clip={**rect,'height':min(rect['height'],1600),'scale':1}
                shot=browser.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':clip},page=True)
                (directory/f'{args.stage}_cycles_{"mobile" if mobile else "desktop"}.png').write_bytes(base64.b64decode(shot['data']))
            if args.stage == 'after':
                browser.call('Emulation.setDeviceMetricsOverride', {'width':1400,'height':1000,'deviceScaleFactor':1,'mobile':False},page=True)
                browser.value("document.body.classList.add('light-theme');window.scrollTo(0,0)")
                time.sleep(.12)
                size=browser.call('Page.getLayoutMetrics',page=True)['cssContentSize']
                shot=browser.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':1400,'height':min(size['height'],3200),'scale':1}},page=True)
                (directory/'after_light_desktop.png').write_bytes(base64.b64decode(shot['data']))
            print(json.dumps({'stage':args.stage,'desktop':str(directory/f'{args.stage}_desktop.png'),'mobile':str(directory/f'{args.stage}_mobile.png')}))
        finally: browser.close()
finally:
    server.shutdown();server.server_close()
